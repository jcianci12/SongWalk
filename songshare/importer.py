from __future__ import annotations

import base64
import importlib.util
import json
import mimetypes
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .album_lookup import LookupError, MusicMetadataClient
from .store import ALLOWED_AUDIO_EXTENSIONS, Store, Track, UploadedTrack


class ImportError(RuntimeError):
    pass


@dataclass
class ImportProgressUpdate:
    phase: str
    message: str
    percent: int | None = None
    current_item: str = ""


@dataclass
class ImportOutcome:
    uploaded: int = 0
    errors: list[str] = field(default_factory=list)
    tracks: list[Track] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.uploaded > 0


class CommandRunner:
    def run(
        self,
        command: list[str],
        *,
        cwd: Path,
        progress_callback: Callable[[str], None] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        try:
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise ImportError(f"{command[0]} is not installed on this host.") from exc

        try:
            output_lines: list[str] = []
            assert process.stdout is not None
            for line in process.stdout:
                output_lines.append(line)
                if progress_callback:
                    progress_callback(line.rstrip())

            returncode = process.wait(timeout=1800)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            raise ImportError(f"{command[0]} took too long to finish.") from exc

        return subprocess.CompletedProcess(
            args=command,
            returncode=returncode,
            stdout="".join(output_lines),
            stderr="",
        )


class LibraryImportService:
    def __init__(
        self,
        *,
        store: Store,
        lookup_client: MusicMetadataClient,
        command_runner: CommandRunner | None = None,
        work_root: Path | None = None,
        youtube_command: str | None = None,
        spotify_command: str | None = None,
        spotify_client_id: str | None = None,
        spotify_client_secret: str | None = None,
    ):
        self._store = store
        self._lookup_client = lookup_client
        self._command_runner = command_runner or CommandRunner()
        self._work_root = Path(work_root or store.root_dir / ".import-work")
        self._youtube_command = youtube_command.strip() if youtube_command else ""
        self._spotify_command = spotify_command.strip() if spotify_command else ""
        self._spotify_client_id = (spotify_client_id or os.getenv("SONGSHARE_SPOTIFY_CLIENT_ID", "")).strip()
        self._spotify_client_secret = (spotify_client_secret or os.getenv("SONGSHARE_SPOTIFY_CLIENT_SECRET", "")).strip()
        self._spotify_access_token = ""
        self._spotify_access_token_expires_at = 0.0
        self._work_root.mkdir(parents=True, exist_ok=True)

    def import_uploaded_files(self, library_id: str, uploads: Iterable[UploadedTrack]) -> ImportOutcome:
        outcome = ImportOutcome()
        for upload in uploads:
            try:
                track = self._store.add_track(library_id, upload)
                finalized = self._finalize_track(library_id, track)
                outcome.uploaded += 1
                outcome.tracks.append(finalized)
            except ValueError as exc:
                outcome.errors.append(str(exc))
        return outcome

    def import_youtube_url(
        self,
        library_id: str,
        source_url: str,
        *,
        progress_callback: Callable[[ImportProgressUpdate], None] | None = None,
    ) -> ImportOutcome:
        return self._import_remote_url(
            library_id,
            source_url=source_url,
            command=self._build_youtube_command(source_url),
            progress_callback=progress_callback,
        )

    def import_spotify_url(
        self,
        library_id: str,
        source_url: str,
        *,
        progress_callback: Callable[[ImportProgressUpdate], None] | None = None,
    ) -> ImportOutcome:
        return self._import_remote_url(
            library_id,
            source_url=source_url,
            command=self._build_spotify_command(source_url),
            progress_callback=progress_callback,
        )

    def search_youtube(self, query: str, *, limit: int = 6) -> list[dict[str, str]]:
        clean_query = query.strip()
        if len(clean_query) < 2:
            raise ImportError("Enter at least two characters to search YouTube.")

        result = self._command_runner.run(
            self._build_youtube_search_command(clean_query, limit),
            cwd=self._work_root,
        )
        if result.returncode != 0:
            detail = (result.stdout or "").strip()
            message = detail.splitlines()[-1] if detail else "YouTube search failed."
            raise ImportError(message)

        items: list[dict[str, str]] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue

            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            video_id = str(payload.get("id", "")).strip()
            if not video_id:
                continue

            duration_seconds = int(payload.get("duration") or 0)
            items.append(
                {
                    "title": str(payload.get("title", "")).strip() or "Untitled result",
                    "channel": str(payload.get("channel", "") or payload.get("uploader", "")).strip(),
                    "duration": _format_duration(duration_seconds),
                    "thumbnail": _best_thumbnail_url(payload),
                    "url": str(payload.get("webpage_url", "")).strip() or f"https://www.youtube.com/watch?v={video_id}",
                }
            )

        return items

    def search_spotify(self, query: str, *, limit: int = 6) -> list[dict[str, str]]:
        clean_query = query.strip()
        if len(clean_query) < 2:
            raise ImportError("Enter at least two characters to search Spotify.")
        if not self._spotify_client_id or not self._spotify_client_secret:
            raise ImportError("Spotify search requires SONGSHARE_SPOTIFY_CLIENT_ID and SONGSHARE_SPOTIFY_CLIENT_SECRET.")

        payload = self._spotify_request_json(
            "https://api.spotify.com/v1/search",
            query_params={
                "q": clean_query,
                "type": "track,album,playlist",
                "limit": str(max(1, min(limit, 10))),
            },
        )

        items: list[dict[str, str]] = []

        for track in (payload.get("tracks") or {}).get("items", []):
            artist_names = _spotify_artist_names(track.get("artists"))
            album_name = str((track.get("album") or {}).get("name", "")).strip()
            items.append(
                {
                    "kind": "track",
                    "title": str(track.get("name", "")).strip() or "Untitled track",
                    "subtitle": " · ".join(part for part in (artist_names, album_name) if part),
                    "thumbnail": _spotify_image_url((track.get("album") or {}).get("images")),
                    "url": str((track.get("external_urls") or {}).get("spotify", "")).strip(),
                }
            )

        for album in (payload.get("albums") or {}).get("items", []):
            artist_names = _spotify_artist_names(album.get("artists"))
            items.append(
                {
                    "kind": "album",
                    "title": str(album.get("name", "")).strip() or "Untitled album",
                    "subtitle": " · ".join(part for part in (artist_names, "Album") if part),
                    "thumbnail": _spotify_image_url(album.get("images")),
                    "url": str((album.get("external_urls") or {}).get("spotify", "")).strip(),
                }
            )

        for playlist in (payload.get("playlists") or {}).get("items", []):
            owner_name = str((playlist.get("owner") or {}).get("display_name", "")).strip()
            items.append(
                {
                    "kind": "playlist",
                    "title": str(playlist.get("name", "")).strip() or "Untitled playlist",
                    "subtitle": " · ".join(part for part in (owner_name, "Playlist") if part),
                    "thumbnail": _spotify_image_url(playlist.get("images")),
                    "url": str((playlist.get("external_urls") or {}).get("spotify", "")).strip(),
                }
            )

        return [item for item in items if item["url"]][: max(1, limit)]

    def _import_remote_url(
        self,
        library_id: str,
        *,
        source_url: str,
        command: list[str],
        progress_callback: Callable[[ImportProgressUpdate], None] | None = None,
    ) -> ImportOutcome:
        if not source_url.strip():
            return ImportOutcome(errors=["Paste a valid source URL."])

        with tempfile.TemporaryDirectory(dir=self._work_root) as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            _emit_progress(progress_callback, phase="preparing", message="Preparing import...")
            result = self._command_runner.run(
                command,
                cwd=temp_dir,
                progress_callback=lambda line: self._handle_remote_progress_line(line, progress_callback),
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip()
                message = detail.splitlines()[-1] if detail else "Downloader failed."
                raise ImportError(message)

            outcome = ImportOutcome()
            produced_files = [
                file_path
                for file_path in sorted(temp_dir.rglob("*"))
                if file_path.is_file() and file_path.suffix.lower() in ALLOWED_AUDIO_EXTENSIONS
            ]

            total_files = len(produced_files)
            for index, file_path in enumerate(produced_files, start=1):
                item_label = _clean_title(file_path.stem)
                _emit_progress(
                    progress_callback,
                    phase="tagging",
                    message=f"Adding track {index} of {total_files} to the library...",
                    percent=100 if total_files == 0 else min(99, int((index - 1) / total_files * 100)),
                    current_item=item_label,
                )

                with file_path.open("rb") as handle:
                    track = self._store.add_track(
                        library_id,
                        UploadedTrack(
                            filename=file_path.name,
                            content_type=mimetypes.guess_type(file_path.name)[0] or "application/octet-stream",
                            stream=handle,
                            size=file_path.stat().st_size,
                        ),
                    )
                _emit_progress(
                    progress_callback,
                    phase="tagging",
                    message=f"Matching metadata for {track.title or item_label}...",
                    percent=100 if total_files == 0 else min(99, int(index / total_files * 100)),
                    current_item=track.title or item_label,
                )
                finalized = self._finalize_track(library_id, track)
                outcome.uploaded += 1
                outcome.tracks.append(finalized)

            if not outcome.uploaded:
                outcome.errors.append("No supported audio files were produced.")
            else:
                _emit_progress(progress_callback, phase="complete", message="Import finished.", percent=100)
            return outcome

    def _finalize_track(self, library_id: str, track: Track) -> Track:
        track = self._normalize_track_metadata(library_id, track)

        present_fields = sum(bool(value.strip()) for value in (track.title, track.artist, track.album))
        if present_fields < 2 or all(value.strip() for value in (track.title, track.artist, track.album)):
            return track

        try:
            candidates = self._lookup_client.search_release_candidates(
                title=track.title,
                artist=track.artist,
                album=track.album,
                limit=1,
            )
        except LookupError:
            return track

        if not candidates:
            return track

        candidate = candidates[0]
        try:
            cover_bytes, cover_extension = self._lookup_client.fetch_cover_art(
                release_id=candidate.release_id,
                release_group_id=candidate.release_group_id,
            )
        except LookupError:
            cover_bytes, cover_extension = None, ".jpg"

        return self._store.apply_album_info(
            library_id,
            track.id,
            title=candidate.track_title or track.title,
            artist=candidate.artist or track.artist,
            album=candidate.title or track.album,
            musicbrainz_release_id=candidate.release_id,
            musicbrainz_release_group_id=candidate.release_group_id,
            cover_art_bytes=cover_bytes,
            cover_art_extension=cover_extension,
        )

    def _normalize_track_metadata(self, library_id: str, track: Track) -> Track:
        title = _clean_title(track.title or Path(track.original_name).stem)
        artist = track.artist.strip()
        album = track.album.strip()

        guessed_artist, guessed_title = _split_artist_title(title)
        if not artist and guessed_artist and guessed_title:
            artist = guessed_artist
            title = guessed_title

        if title == track.title and artist == track.artist and album == track.album:
            return track

        return self._store.update_track(
            library_id,
            track.id,
            title=title,
            artist=artist,
            album=album,
            rating=track.rating,
        )

    def _build_youtube_command(self, source_url: str) -> list[str]:
        prefix = _resolve_command(
            self._youtube_command,
            module_fallbacks=("yt_dlp", "youtube_dl"),
            binary_fallbacks=(["yt-dlp"], ["youtube-dl"]),
        )
        ffmpeg_args = _resolve_ffmpeg_args("--ffmpeg-location")
        return prefix + [
            "--ignore-config",
            "--extract-audio",
            "--audio-format",
            "mp3",
            "--restrict-filenames",
            "-o",
            "%(uploader)s - %(title)s [%(id)s].%(ext)s",
            *ffmpeg_args,
            source_url.strip(),
        ]

    def _build_youtube_search_command(self, query: str, limit: int) -> list[str]:
        prefix = _resolve_command(
            self._youtube_command,
            module_fallbacks=("yt_dlp", "youtube_dl"),
            binary_fallbacks=(["yt-dlp"], ["youtube-dl"]),
        )
        return prefix + [
            "--ignore-config",
            "--flat-playlist",
            "--dump-json",
            "--no-warnings",
            f"ytsearch{max(1, min(limit, 10))}:{query}",
        ]

    def _build_spotify_command(self, source_url: str) -> list[str]:
        prefix = _resolve_command(
            self._spotify_command,
            module_fallbacks=("spotdl",),
            binary_fallbacks=(["spotdl"],),
        )
        ffmpeg_args = _resolve_ffmpeg_args("--ffmpeg")
        return prefix + [
            "download",
            source_url.strip(),
            "--format",
            "mp3",
            "--output",
            "{artists} - {title}.{output-ext}",
            "--overwrite",
            "force",
            "--print-errors",
            *ffmpeg_args,
        ]

    def _handle_remote_progress_line(
        self,
        line: str,
        progress_callback: Callable[[ImportProgressUpdate], None] | None,
    ) -> None:
        clean_line = line.strip()
        if not clean_line:
            return

        percent_match = re.search(r"(\d{1,3}(?:\.\d+)?)%", clean_line)
        percent = None
        if percent_match:
            percent = max(0, min(99, int(float(percent_match.group(1)))))

        current_item = ""
        if "Destination:" in clean_line:
            current_item = clean_line.split("Destination:", 1)[1].strip()
        elif '"' in clean_line:
            quoted = re.findall(r'"([^"]+)"', clean_line)
            if quoted:
                current_item = quoted[-1].strip()

        phase = "downloading"
        if "search" in clean_line.lower():
            phase = "searching"
        elif "metadata" in clean_line.lower() or "match" in clean_line.lower():
            phase = "tagging"

        _emit_progress(
            progress_callback,
            phase=phase,
            message=_clean_progress_line(clean_line),
            percent=percent,
            current_item=_clean_title(current_item),
        )

    def _spotify_request_json(self, url: str, *, query_params: dict[str, str]) -> dict:
        token = self._spotify_token()
        query_string = urllib.parse.urlencode(query_params)
        request = urllib.request.Request(
            f"{url}?{query_string}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise ImportError("Spotify search failed.") from exc

    def _spotify_token(self) -> str:
        now = time.time()
        if self._spotify_access_token and now < self._spotify_access_token_expires_at:
            return self._spotify_access_token

        auth_value = base64.b64encode(
            f"{self._spotify_client_id}:{self._spotify_client_secret}".encode("utf-8")
        ).decode("ascii")
        body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("utf-8")
        request = urllib.request.Request(
            "https://accounts.spotify.com/api/token",
            data=body,
            headers={
                "Authorization": f"Basic {auth_value}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise ImportError("Spotify authentication failed.") from exc

        token = str(payload.get("access_token", "")).strip()
        expires_in = int(payload.get("expires_in") or 3600)
        if not token:
            raise ImportError("Spotify authentication failed.")

        self._spotify_access_token = token
        self._spotify_access_token_expires_at = now + max(expires_in - 30, 60)
        return token


def _resolve_command(
    configured: str,
    *,
    module_fallbacks: tuple[str, ...],
    binary_fallbacks: tuple[list[str], ...],
) -> list[str]:
    if configured:
        return shlex.split(configured)

    for module_name in module_fallbacks:
        if importlib.util.find_spec(module_name):
            return [sys.executable, "-m", module_name]

    for candidate in binary_fallbacks:
        if shutil.which(candidate[0]):
            return candidate

    missing = binary_fallbacks[0][0]
    raise ImportError(f"{missing} is not installed on this host.")


def _resolve_ffmpeg_args(flag_name: str) -> list[str]:
    ffmpeg_binary = shutil.which("ffmpeg")
    if ffmpeg_binary:
        return [flag_name, ffmpeg_binary]

    try:
        from imageio_ffmpeg import get_ffmpeg_exe
    except Exception as exc:
        raise ImportError("FFmpeg is required for YouTube and Spotify imports.") from exc

    return [flag_name, get_ffmpeg_exe()]


def _emit_progress(
    progress_callback: Callable[[ImportProgressUpdate], None] | None,
    *,
    phase: str,
    message: str,
    percent: int | None = None,
    current_item: str = "",
) -> None:
    if not progress_callback:
        return

    progress_callback(
        ImportProgressUpdate(
            phase=phase,
            message=message,
            percent=percent,
            current_item=current_item,
        )
    )


def _clean_progress_line(value: str) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", value or "")
    return re.sub(r"\s+", " ", text).strip()


def _clean_title(value: str) -> str:
    title = re.sub(r"_+", " ", value or "")
    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(r"\s+\[[A-Za-z0-9_-]{6,}\]$", "", title)
    title = re.sub(r"\s+[A-Za-z0-9_-]{10,}$", "", title)
    return title.strip()


def _split_artist_title(value: str) -> tuple[str, str]:
    cleaned = _clean_title(value)
    if " - " not in cleaned:
        return "", cleaned

    artist, title = cleaned.split(" - ", 1)
    return artist.strip(), title.strip()


def _best_thumbnail_url(payload: dict) -> str:
    thumbnails = payload.get("thumbnails")
    if isinstance(thumbnails, list) and thumbnails:
        for item in reversed(thumbnails):
            if isinstance(item, dict) and item.get("url"):
                return str(item["url"])
    return ""


def _spotify_artist_names(payload) -> str:
    if not isinstance(payload, list):
        return ""
    return ", ".join(
        str(item.get("name", "")).strip()
        for item in payload
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    )


def _spotify_image_url(payload) -> str:
    if not isinstance(payload, list):
        return ""
    for item in payload:
        if isinstance(item, dict) and item.get("url"):
            return str(item["url"])
    return ""


def _format_duration(seconds: int) -> str:
    if seconds <= 0:
        return ""
    minutes, remainder = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{remainder:02d}"
    return f"{minutes}:{remainder:02d}"
