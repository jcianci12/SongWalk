from __future__ import annotations

import mimetypes
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse
from collections.abc import Iterable
from typing import Callable

from .audio_tags import clamp_rating
from .store import Store


WMP_LIBRARY_NAME = "Windows Media Player"
WMP_SOURCE_KIND = "wmp"
WMP_PLAYLIST_SOURCE_KIND = "wmp_playlist"


class WmpUnavailableError(RuntimeError):
    pass


@dataclass
class WmpStatus:
    available: bool
    platform: str
    access_rights: str = ""
    item_count: int = 0
    message: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WmpSyncResult:
    ok: bool
    library_id: str = ""
    created: int = 0
    updated: int = 0
    skipped: int = 0
    marked_unavailable: int = 0
    total: int = 0
    message: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WmpSyncProgressUpdate:
    phase: str
    message: str
    percent: int | None = None
    current_item: str = ""


@dataclass
class WmpTrack:
    title: str
    artist: str
    album: str
    source_path: str
    source_external_id: str
    original_name: str
    content_type: str
    size: int = 0
    rating: int = 0
    duration_seconds: float = 0.0
    genre: str = ""
    album_artist: str = ""
    play_count: int = 0
    last_played_at: str = ""
    source_available: bool = True

    def to_store_payload(self) -> dict:
        return asdict(self)


@dataclass
class WmpPlaylist:
    name: str
    source_external_id: str
    track_source_external_ids: list[str]
    track_source_paths: list[str]

    def to_store_payload(self) -> dict:
        return asdict(self)


class DisabledWmpLibraryService:
    def status(self) -> WmpStatus:
        return WmpStatus(
            available=False,
            platform=sys.platform,
            message="Windows Media Player sync is disabled in this runtime.",
        )

    def sync_to_store(
        self,
        store: Store,
        *,
        library_id: str | None = None,
        limit: int | None = None,
        progress_callback: Callable[[WmpSyncProgressUpdate], None] | None = None,
    ) -> WmpSyncResult:
        return WmpSyncResult(ok=False, message="Windows Media Player sync is disabled.", error="Windows Media Player sync is disabled.")


class WmpLibraryService:
    def __init__(
        self,
        *,
        chunk_size: int = 25,
        powershell_runner: Callable[[str, int], Iterable[str]] | None = None,
    ):
        self._chunk_size = max(1, int(chunk_size))
        self._powershell_runner = powershell_runner or _iter_powershell_lines

    def status(self) -> WmpStatus:
        if os.name != "nt":
            return WmpStatus(
                available=False,
                platform=sys.platform,
                message="Windows Media Player library sync is only available on Windows.",
            )

        try:
            payload = _run_powershell_json(_STATUS_SCRIPT, timeout_seconds=20)
            return WmpStatus(
                available=bool(payload.get("available")),
                platform=sys.platform,
                access_rights=str(payload.get("access_rights", "")),
                item_count=int(payload.get("item_count", 0) or 0),
                message=str(payload.get("message", "")) or "Windows Media Player is available.",
            )
        except WmpUnavailableError as exc:
            return WmpStatus(available=False, platform=sys.platform, message=str(exc))
        except Exception as exc:
            return WmpStatus(available=False, platform=sys.platform, message=f"Windows Media Player is not available: {exc}")

    def sync_to_store(
        self,
        store: Store,
        *,
        library_id: str | None = None,
        limit: int | None = None,
        progress_callback: Callable[[WmpSyncProgressUpdate], None] | None = None,
    ) -> WmpSyncResult:
        try:
            library = _find_or_create_wmp_library(store, library_id=library_id)
            stats = {
                "created": 0,
                "updated": 0,
                "skipped": 0,
                "marked_unavailable": 0,
                "total": 0,
            }
            seen_external_ids: set[str] = set()
            batch: list[dict] = []
            last_item = ""

            total_hint = max(0, int(limit or 0))
            _emit_sync_progress(
                progress_callback,
                phase="syncing_tracks",
                message="Syncing Windows Media Player tracks...",
                percent=5,
            )

            for index, track in enumerate(self.iter_audio_tracks(limit=limit), start=1):
                percent = None
                if total_hint:
                    percent = 5 + int((index / total_hint) * 85)
                current_item = track.source_path or track.title or track.original_name
                _emit_sync_progress(
                    progress_callback,
                    phase="syncing_tracks",
                    message=f"Syncing WMP track {index}{f' of {total_hint}' if total_hint else ''}...",
                    percent=min(90, percent) if percent is not None else None,
                    current_item=current_item,
                )
                last_item = current_item
                batch.append(track.to_store_payload())
                seen_external_ids.add(track.source_external_id)
                if len(batch) < self._chunk_size:
                    continue

                _merge_stats(
                    stats,
                    store.sync_linked_tracks(
                        library.id,
                        source_kind=WMP_SOURCE_KIND,
                        tracks=batch,
                        mark_missing_unavailable=False,
                    ),
                )
                batch = []

            if batch:
                _merge_stats(
                    stats,
                    store.sync_linked_tracks(
                        library.id,
                        source_kind=WMP_SOURCE_KIND,
                        tracks=batch,
                        mark_missing_unavailable=False,
                    ),
                )

            stats["marked_unavailable"] += store.mark_linked_tracks_unavailable_except(
                library.id,
                source_kind=WMP_SOURCE_KIND,
                source_external_ids=seen_external_ids,
            )
            playlists = self.read_playlists()
            if playlists:
                _emit_sync_progress(
                    progress_callback,
                    phase="syncing_playlists",
                    message="Syncing Windows Media Player playlists...",
                    percent=95,
                    current_item=playlists[0].name,
                )
                last_item = playlists[-1].name
            playlist_stats = store.sync_linked_collections(
                library.id,
                source_kind=WMP_PLAYLIST_SOURCE_KIND,
                collections=[playlist.to_store_payload() for playlist in playlists],
            )
            _emit_sync_progress(
                progress_callback,
                phase="complete",
                message="Windows Media Player sync finished.",
                percent=100,
                current_item=last_item,
            )
            return WmpSyncResult(
                ok=True,
                library_id=library.id,
                created=stats["created"],
                updated=stats["updated"],
                skipped=stats["skipped"],
                marked_unavailable=stats["marked_unavailable"],
                total=stats["total"],
                message=(
                    f"Synced {stats['total']} WMP track"
                    f"{'s' if stats['total'] != 1 else ''} and {playlist_stats['total']} playlist"
                    f"{'s' if playlist_stats['total'] != 1 else ''}."
                ),
            )
        except Exception as exc:
            return WmpSyncResult(ok=False, error=str(exc), message="Windows Media Player sync failed.")

    def read_audio_tracks(self, *, limit: int | None = None) -> list[WmpTrack]:
        return list(self.iter_audio_tracks(limit=limit))

    def read_playlists(self) -> list[WmpPlaylist]:
        playlists: list[WmpPlaylist] = []
        for line in self._powershell_runner(_READ_PLAYLISTS_SCRIPT, timeout_seconds=180):
            if not line.strip():
                continue
            payload = json.loads(line)
            playlist = _playlist_from_payload(payload)
            if playlist is not None:
                playlists.append(playlist)
        return playlists

    def iter_audio_tracks(self, *, limit: int | None = None):
        limit_value = max(0, int(limit or 0))
        script = _READ_TRACKS_SCRIPT.replace("__LIMIT__", str(limit_value))
        for line in self._powershell_runner(script, timeout_seconds=600):
            if not line.strip():
                continue
            payload = json.loads(line)
            track = _track_from_payload(payload)
            if track is not None:
                yield track

    def set_rating(self, *, source_external_id: str, source_path: str, rating: int | str) -> None:
        script = (
            _SET_RATING_SCRIPT
            .replace("__SOURCE_EXTERNAL_ID__", _ps_single_quoted(source_external_id))
            .replace("__SOURCE_PATH__", _ps_single_quoted(str(Path(source_path).resolve()) if source_path else ""))
            .replace("__RATING__", str(_stars_to_wmp_rating(clamp_rating(rating))))
        )
        _run_powershell_json(script, timeout_seconds=120)

    def update_metadata(
        self,
        *,
        source_external_id: str,
        source_path: str,
        title: str,
        artist: str,
        album: str,
    ) -> None:
        script = (
            _UPDATE_METADATA_SCRIPT
            .replace("__SOURCE_EXTERNAL_ID__", _ps_single_quoted(source_external_id))
            .replace("__SOURCE_PATH__", _ps_single_quoted(str(Path(source_path).resolve()) if source_path else ""))
            .replace("__TITLE__", _ps_single_quoted(title.strip()))
            .replace("__ARTIST__", _ps_single_quoted(artist.strip()))
            .replace("__ALBUM__", _ps_single_quoted(album.strip()))
        )
        _run_powershell_json(script, timeout_seconds=120)


def _find_or_create_wmp_library(store: Store, *, library_id: str | None) -> object:
    if library_id:
        return store.get_library(library_id)

    for library in store.list_libraries():
        if library.name.strip().casefold() == WMP_LIBRARY_NAME.casefold():
            return library

    return store.create_library(name=WMP_LIBRARY_NAME)


def _track_from_payload(payload: dict) -> WmpTrack | None:
    source_path = _source_url_to_path(str(payload.get("source_url", "") or payload.get("source_path", "")))
    if not source_path:
        return None

    path = Path(source_path)
    original_name = path.name or str(payload.get("title", "")).strip() or "wmp-track"
    size = _int_value(payload.get("file_size"))
    if path.exists() and path.is_file():
        try:
            size = path.stat().st_size
        except OSError:
            pass

    title = str(payload.get("title", "")).strip() or path.stem
    artist = str(payload.get("artist", "") or payload.get("display_artist", "")).strip()
    album = str(payload.get("album", "") or payload.get("album_fallback", "")).strip()
    tracking_id = str(payload.get("tracking_id", "")).strip()
    external_id = tracking_id or str(path.resolve()).casefold()

    return WmpTrack(
        title=title,
        artist=artist,
        album=album,
        source_path=str(path),
        source_external_id=external_id,
        original_name=original_name,
        content_type=mimetypes.guess_type(original_name)[0] or "application/octet-stream",
        size=size,
        rating=_wmp_rating_to_stars(str(payload.get("rating", "") or payload.get("effective_rating", ""))),
        duration_seconds=_float_value(payload.get("duration")),
        genre=str(payload.get("genre", "")).strip(),
        album_artist=str(payload.get("album_artist", "")).strip(),
        play_count=_int_value(payload.get("play_count")),
        last_played_at=str(payload.get("last_played_at", "")).strip(),
        source_available=path.exists() and path.is_file(),
    )


def _playlist_from_payload(payload: dict) -> WmpPlaylist | None:
    name = str(payload.get("name", "")).strip()
    if not name:
        return None

    track_ids = [
        str(value).strip()
        for value in payload.get("track_source_external_ids", [])
        if str(value).strip()
    ]
    source_paths = [
        _source_url_to_path(str(value))
        for value in payload.get("track_source_urls", [])
        if _source_url_to_path(str(value))
    ]
    if not track_ids and not source_paths:
        return None

    external_id = str(payload.get("source_external_id", "")).strip() or name.casefold()
    return WmpPlaylist(
        name=name,
        source_external_id=external_id,
        track_source_external_ids=track_ids,
        track_source_paths=source_paths,
    )


def _int_value(value) -> int:
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _float_value(value) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _source_url_to_path(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""

    if os.name == "nt":
        if len(text) >= 3 and text[1] == ":" and text[2] in {"\\", "/"}:
            return str(Path(text))
        if text.startswith("\\\\"):
            return str(Path(text))

    parsed = urlparse(text)
    if parsed.scheme.lower() == "file":
        path = unquote(parsed.path or "")
        if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
            path = path[1:]
        return str(Path(path))

    if parsed.scheme and parsed.scheme.lower() not in {"file"}:
        return ""

    return str(Path(text))


def _wmp_rating_to_stars(value: str) -> int:
    try:
        numeric = int(float(value or 0))
    except (TypeError, ValueError):
        return 0

    if numeric <= 5:
        return clamp_rating(numeric)
    if numeric >= 99:
        return 5
    if numeric >= 75:
        return 4
    if numeric >= 50:
        return 3
    if numeric >= 25:
        return 2
    if numeric >= 1:
        return 1
    return 0


def _stars_to_wmp_rating(stars: int) -> int:
    return {
        0: 0,
        1: 1,
        2: 25,
        3: 50,
        4: 75,
        5: 99,
    }[clamp_rating(stars)]


def _merge_stats(total: dict, chunk: dict) -> None:
    for key in ("created", "updated", "skipped", "marked_unavailable", "total"):
        total[key] = int(total.get(key, 0) or 0) + int(chunk.get(key, 0) or 0)


def _emit_sync_progress(
    progress_callback: Callable[[WmpSyncProgressUpdate], None] | None,
    *,
    phase: str,
    message: str,
    percent: int | None = None,
    current_item: str = "",
) -> None:
    if not progress_callback:
        return

    progress_callback(
        WmpSyncProgressUpdate(
            phase=phase,
            message=message,
            percent=percent,
            current_item=current_item,
        )
    )


def _run_powershell_json(script: str, *, timeout_seconds: int) -> dict:
    lines = _run_powershell_lines(script, timeout_seconds=timeout_seconds)
    if not lines:
        raise WmpUnavailableError("Windows Media Player did not return a response.")
    return json.loads(lines[-1])


def _run_powershell_lines(script: str, *, timeout_seconds: int) -> list[str]:
    return list(_iter_powershell_lines(script, timeout_seconds=timeout_seconds))


def _iter_powershell_lines(script: str, *, timeout_seconds: int):
    binary = "powershell.exe" if os.name == "nt" else "powershell"
    wrapped_script = (
        "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false; "
        "$OutputEncoding = [Console]::OutputEncoding; "
        + script
    )
    try:
        process = subprocess.Popen(
            [binary, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", wrapped_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise WmpUnavailableError("PowerShell is required for Windows Media Player sync.") from exc

    try:
        assert process.stdout is not None
        for line in process.stdout:
            if line.strip():
                yield line.rstrip("\r\n")
        _stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise WmpUnavailableError("Windows Media Player took too long to respond.") from exc

    if process.returncode != 0:
        raise WmpUnavailableError((stderr or "").strip() or "Windows Media Player command failed.")


def _ps_single_quoted(value: str) -> str:
    return "'" + (value or "").replace("'", "''") + "'"


_STATUS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
try {
  $player = New-Object -ComObject WMPlayer.OCX
  $rights = [string]$player.settings.mediaAccessRights
  $playlist = $player.mediaCollection.getAll()
  [pscustomobject]@{
    available = $true
    access_rights = $rights
    item_count = [int]$playlist.count
    message = 'Windows Media Player is available.'
  } | ConvertTo-Json -Compress
} catch {
  [pscustomobject]@{
    available = $false
    access_rights = ''
    item_count = 0
    message = $_.Exception.Message
  } | ConvertTo-Json -Compress
}
"""


_READ_TRACKS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$limit = __LIMIT__
function Clean($value) {
  if ($null -eq $value) { return '' }
  return ([string]$value) -replace '[\x00-\x08\x0B\x0C\x0E-\x1F]', ''
}
function Attr($media, [string]$name) {
  try { return Clean $media.getItemInfo($name) } catch { return '' }
}
function EnsureAccess($player) {
  $rights = [string]$player.settings.mediaAccessRights
  if ($rights -eq 'full' -or $rights -eq 'read') { return }
  [void]$player.settings.requestMediaAccessRights('full')
}
$player = New-Object -ComObject WMPlayer.OCX
EnsureAccess $player
$playlist = $player.mediaCollection.getAll()
$emitted = 0
for ($i = 0; $i -lt $playlist.count; $i++) {
  $media = $playlist.Item($i)
  if ((Attr $media 'MediaType').ToLowerInvariant() -ne 'audio') { continue }
  [pscustomobject]@{
    title = Attr $media 'Title'
    artist = Attr $media 'Author'
    display_artist = Attr $media 'DisplayArtist'
    album = Attr $media 'WM/AlbumTitle'
    album_fallback = Attr $media 'Album'
    album_artist = Attr $media 'WM/AlbumArtist'
    genre = Attr $media 'WM/Genre'
    rating = Attr $media 'UserRating'
    effective_rating = Attr $media 'UserEffectiveRating'
    play_count = Attr $media 'UserPlayCount'
    last_played_at = Attr $media 'UserLastPlayedTime'
    source_url = Clean $media.sourceURL
    tracking_id = Attr $media 'TrackingID'
    duration = Clean $media.duration
    file_size = Attr $media 'FileSize'
  } | ConvertTo-Json -Compress
  $emitted++
  if ($limit -gt 0 -and $emitted -ge $limit) { break }
}
"""


_READ_PLAYLISTS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
function Clean($value) {
  if ($null -eq $value) { return '' }
  return ([string]$value) -replace '[\x00-\x08\x0B\x0C\x0E-\x1F]', ''
}
function Attr($media, [string]$name) {
  try { return Clean $media.getItemInfo($name) } catch { return '' }
}
function EnsureAccess($player) {
  $rights = [string]$player.settings.mediaAccessRights
  if ($rights -eq 'full' -or $rights -eq 'read') { return }
  [void]$player.settings.requestMediaAccessRights('full')
}
$player = New-Object -ComObject WMPlayer.OCX
EnsureAccess $player
$playlists = $player.playlistCollection.getAll()
for ($i = 0; $i -lt $playlists.count; $i++) {
  $playlist = $playlists.Item($i)
  $name = Clean $playlist.name
  if (-not $name) { continue }
  $playlistType = Attr $playlist 'PlaylistType'
  if ($playlistType.ToLowerInvariant() -ne 'wpl') { continue }
  $trackIds = New-Object System.Collections.Generic.List[string]
  $sourceUrls = New-Object System.Collections.Generic.List[string]
  for ($j = 0; $j -lt $playlist.count; $j++) {
    $media = $playlist.Item($j)
    if ((Attr $media 'MediaType').ToLowerInvariant() -ne 'audio') { continue }
    $trackingId = Attr $media 'TrackingID'
    if ($trackingId) { [void]$trackIds.Add($trackingId) }
    $sourceUrl = Clean $media.sourceURL
    if ($sourceUrl) { [void]$sourceUrls.Add($sourceUrl) }
  }
  if ($trackIds.Count -eq 0 -and $sourceUrls.Count -eq 0) { continue }
  [pscustomobject]@{
    name = $name
    source_external_id = (($name.ToLowerInvariant()) + ':' + [string]$i)
    playlist_type = $playlistType
    track_source_external_ids = [string[]]$trackIds
    track_source_urls = [string[]]$sourceUrls
  } | ConvertTo-Json -Compress
}
"""


_FIND_MEDIA_HELPERS = r"""
function Attr($media, [string]$name) {
  try { return [string]$media.getItemInfo($name) } catch { return '' }
}
function EnsureAccess($player) {
  $rights = [string]$player.settings.mediaAccessRights
  if ($rights -eq 'full') { return }
  [void]$player.settings.requestMediaAccessRights('full')
}
function FindMedia($player, [string]$externalId, [string]$sourcePath) {
  $playlist = $player.mediaCollection.getAll()
  $expectedPath = ''
  if ($sourcePath) {
    try { $expectedPath = [System.IO.Path]::GetFullPath($sourcePath).ToLowerInvariant() } catch { $expectedPath = $sourcePath.ToLowerInvariant() }
  }
  for ($i = 0; $i -lt $playlist.count; $i++) {
    $media = $playlist.Item($i)
    if ((Attr $media 'MediaType').ToLowerInvariant() -ne 'audio') { continue }
    if ($externalId -and (Attr $media 'TrackingID') -eq $externalId) { return $media }
    if ($expectedPath) {
      $mediaPath = [string]$media.sourceURL
      try { $mediaPath = [System.IO.Path]::GetFullPath($mediaPath).ToLowerInvariant() } catch { $mediaPath = $mediaPath.ToLowerInvariant() }
      if ($mediaPath -eq $expectedPath) { return $media }
    }
  }
  throw 'Could not find that track in Windows Media Player.'
}
"""


_SET_RATING_SCRIPT = _FIND_MEDIA_HELPERS + r"""
$ErrorActionPreference = 'Stop'
$player = New-Object -ComObject WMPlayer.OCX
EnsureAccess $player
$media = FindMedia $player __SOURCE_EXTERNAL_ID__ __SOURCE_PATH__
$media.setItemInfo('UserRating', '__RATING__')
[pscustomobject]@{ ok = $true } | ConvertTo-Json -Compress
"""


_UPDATE_METADATA_SCRIPT = _FIND_MEDIA_HELPERS + r"""
$ErrorActionPreference = 'Stop'
$player = New-Object -ComObject WMPlayer.OCX
EnsureAccess $player
$media = FindMedia $player __SOURCE_EXTERNAL_ID__ __SOURCE_PATH__
$title = __TITLE__
$artist = __ARTIST__
$album = __ALBUM__
if ($title) { $media.setItemInfo('Title', $title) }
if ($artist) { $media.setItemInfo('Author', $artist) }
if ($album) { $media.setItemInfo('WM/AlbumTitle', $album) }
[pscustomobject]@{ ok = $true } | ConvertTo-Json -Compress
"""
