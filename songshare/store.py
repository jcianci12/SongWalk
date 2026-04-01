from __future__ import annotations

import json
import mimetypes
import os
import shutil
import stat
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from werkzeug.utils import secure_filename

from .audio_tags import clamp_rating, read_mp3_metadata, write_mp3_metadata


ALLOWED_AUDIO_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
    ".wma",
}


class LibraryNotFoundError(FileNotFoundError):
    pass


class TrackNotFoundError(FileNotFoundError):
    pass


@dataclass
class UploadedTrack:
    filename: str
    content_type: str
    stream: BinaryIO
    size: int | None = None


@dataclass
class Track:
    id: str
    original_name: str
    stored_name: str
    content_type: str
    size: int
    uploaded_at: datetime
    updated_at: datetime
    title: str = ""
    artist: str = ""
    album: str = ""
    rating: int = 0
    cover_art_name: str = ""
    musicbrainz_release_id: str = ""
    musicbrainz_release_group_id: str = ""

    @classmethod
    def from_dict(cls, payload: dict) -> "Track":
        return cls(
            id=payload["id"],
            original_name=payload["original_name"],
            stored_name=payload["stored_name"],
            content_type=payload["content_type"],
            size=payload["size"],
            uploaded_at=datetime.fromisoformat(payload["uploaded_at"]),
            updated_at=datetime.fromisoformat(payload["updated_at"]),
            title=payload.get("title", ""),
            artist=payload.get("artist", ""),
            album=payload.get("album", ""),
            rating=payload.get("rating", 0),
            cover_art_name=payload.get("cover_art_name", ""),
            musicbrainz_release_id=payload.get("musicbrainz_release_id", ""),
            musicbrainz_release_group_id=payload.get("musicbrainz_release_group_id", ""),
        )

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["uploaded_at"] = self.uploaded_at.isoformat()
        payload["updated_at"] = self.updated_at.isoformat()
        return payload


@dataclass
class Library:
    id: str
    created_at: datetime
    updated_at: datetime
    tracks: list[Track] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict) -> "Library":
        return cls(
            id=payload["id"],
            created_at=datetime.fromisoformat(payload["created_at"]),
            updated_at=datetime.fromisoformat(payload["updated_at"]),
            tracks=[Track.from_dict(item) for item in payload.get("tracks", [])],
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "tracks": [track.to_dict() for track in self.tracks],
        }


class Store:
    def __init__(self, root_dir: Path):
        self.root_dir = Path(root_dir).resolve()
        self._libraries_dir = self.root_dir / "libraries"
        self._lock = threading.Lock()
        self._libraries_dir.mkdir(parents=True, exist_ok=True)

    def list_libraries(self) -> list[Library]:
        libraries: list[Library] = []
        for library_dir in self._libraries_dir.iterdir():
            if not library_dir.is_dir():
                continue
            try:
                libraries.append(self.get_library(library_dir.name))
            except LibraryNotFoundError:
                continue
        libraries.sort(key=lambda item: item.updated_at, reverse=True)
        return libraries

    def create_library(self) -> Library:
        with self._lock:
            for _ in range(5):
                library_id = str(uuid.uuid4())
                library_dir = self._library_dir(library_id)
                if library_dir.exists():
                    continue

                files_dir = library_dir / "files"
                files_dir.mkdir(parents=True, exist_ok=False)
                now = _now()
                library = Library(id=library_id, created_at=now, updated_at=now)
                self._write_library(library)
                return library
        raise RuntimeError("unable to allocate library id")

    def delete_library(self, library_id: str) -> None:
        with self._lock:
            library_dir = self._library_dir(library_id)
            if not library_dir.exists() or not library_dir.is_dir():
                raise LibraryNotFoundError(library_id)
            _rmtree_with_retries(library_dir)

    def get_library(self, library_id: str) -> Library:
        library_path = self._library_json_path(library_id)
        if not library_path.exists():
            raise LibraryNotFoundError(library_id)
        payload = json.loads(library_path.read_text(encoding="utf-8"))
        return Library.from_dict(payload)

    def add_track(self, library_id: str, uploaded_track: UploadedTrack) -> Track:
        filename = secure_filename(uploaded_track.filename or "")
        if not filename:
            raise ValueError("File is missing a usable name.")

        extension = Path(filename).suffix.lower()
        if extension not in ALLOWED_AUDIO_EXTENSIONS:
            raise ValueError(f"{filename} is not a supported audio file.")

        with self._lock:
            library = self.get_library(library_id)
            track_id = str(uuid.uuid4())
            stored_name = f"{track_id}{extension}"
            target_path = self.library_files_dir(library_id) / stored_name
            target_path.parent.mkdir(parents=True, exist_ok=True)

            stream = uploaded_track.stream
            if hasattr(stream, "seek"):
                stream.seek(0)

            with target_path.open("wb") as handle:
                shutil.copyfileobj(stream, handle)

            size = uploaded_track.size if uploaded_track.size and uploaded_track.size > 0 else target_path.stat().st_size
            content_type = (
                uploaded_track.content_type
                or mimetypes.guess_type(filename)[0]
                or "application/octet-stream"
            )
            embedded_metadata = read_mp3_metadata(target_path)

            now = _now()
            track = Track(
                id=track_id,
                original_name=filename,
                stored_name=stored_name,
                content_type=content_type,
                size=size,
                uploaded_at=now,
                updated_at=now,
                title=str(embedded_metadata.get("title", "")).strip() or Path(filename).stem,
                artist=str(embedded_metadata.get("artist", "")).strip(),
                album=str(embedded_metadata.get("album", "")).strip(),
                rating=clamp_rating(embedded_metadata.get("rating", 0)),
            )
            library.tracks.insert(0, track)
            library.updated_at = now
            self._write_library(library)
            return track

    def update_track(
        self,
        library_id: str,
        track_id: str,
        *,
        title: str,
        artist: str,
        album: str,
        rating: int | str = 0,
    ) -> Track:
        with self._lock:
            library = self.get_library(library_id)
            track = self._find_track(library, track_id)
            track.title = title.strip()
            track.artist = artist.strip()
            track.album = album.strip()
            track.rating = clamp_rating(rating)
            write_mp3_metadata(
                self.library_files_dir(library_id) / track.stored_name,
                title=track.title,
                artist=track.artist,
                album=track.album,
                rating=track.rating,
            )
            track.updated_at = _now()
            library.updated_at = track.updated_at
            self._write_library(library)
            return track

    def set_track_rating(self, library_id: str, track_id: str, *, rating: int | str) -> Track:
        with self._lock:
            library = self.get_library(library_id)
            track = self._find_track(library, track_id)
            track.rating = clamp_rating(rating)
            write_mp3_metadata(
                self.library_files_dir(library_id) / track.stored_name,
                title=track.title,
                artist=track.artist,
                album=track.album,
                rating=track.rating,
            )
            track.updated_at = _now()
            library.updated_at = track.updated_at
            self._write_library(library)
            return track

    def apply_album_info(
        self,
        library_id: str,
        track_id: str,
        *,
        title: str,
        artist: str,
        album: str,
        musicbrainz_release_id: str,
        musicbrainz_release_group_id: str,
        cover_art_bytes: bytes | None,
        cover_art_extension: str,
    ) -> Track:
        with self._lock:
            library = self.get_library(library_id)
            track = self._find_track(library, track_id)
            track.title = title.strip()
            track.artist = artist.strip()
            track.album = album.strip()
            track.musicbrainz_release_id = musicbrainz_release_id.strip()
            track.musicbrainz_release_group_id = musicbrainz_release_group_id.strip()

            if cover_art_bytes:
                cover_name = self._write_cover_art(
                    library_id,
                    track.id,
                    cover_art_bytes,
                    cover_art_extension,
                )
                track.cover_art_name = cover_name

            track.updated_at = _now()
            library.updated_at = track.updated_at
            self._write_library(library)
            return track

    def delete_track(self, library_id: str, track_id: str) -> None:
        self.delete_tracks(library_id, [track_id])

    def delete_tracks(self, library_id: str, track_ids: list[str]) -> int:
        unique_track_ids = {track_id for track_id in track_ids if str(track_id).strip()}
        if not unique_track_ids:
            return 0

        with self._lock:
            library = self.get_library(library_id)
            tracks_to_remove = [track for track in library.tracks if track.id in unique_track_ids]
            if not tracks_to_remove:
                raise TrackNotFoundError(",".join(sorted(unique_track_ids)))

            library.tracks = [item for item in library.tracks if item.id not in unique_track_ids]
            library.updated_at = _now()
            self._write_library(library)

            for track in tracks_to_remove:
                file_path = self.library_files_dir(library_id) / track.stored_name
                if file_path.exists():
                    _unlink_with_retries(file_path)
                if track.cover_art_name:
                    cover_path = self.library_covers_dir(library_id) / track.cover_art_name
                    if cover_path.exists():
                        _unlink_with_retries(cover_path)

            return len(tracks_to_remove)

    def get_track_file(self, library_id: str, track_id: str) -> tuple[Track, Path]:
        library = self.get_library(library_id)
        track = self._find_track(library, track_id)
        file_path = self.library_files_dir(library_id) / track.stored_name
        if not file_path.exists():
            raise TrackNotFoundError(track_id)
        return track, file_path

    def get_track(self, library_id: str, track_id: str) -> Track:
        library = self.get_library(library_id)
        return self._find_track(library, track_id)

    def library_files_dir(self, library_id: str) -> Path:
        return self._library_dir(library_id) / "files"

    def library_covers_dir(self, library_id: str) -> Path:
        covers_dir = self._library_dir(library_id) / "covers"
        covers_dir.mkdir(parents=True, exist_ok=True)
        return covers_dir

    def cover_art_path(self, library_id: str, cover_art_name: str) -> Path:
        return self.library_covers_dir(library_id) / cover_art_name

    def _library_dir(self, library_id: str) -> Path:
        return self._libraries_dir / library_id

    def _library_json_path(self, library_id: str) -> Path:
        return self._library_dir(library_id) / "library.json"

    def _write_library(self, library: Library) -> None:
        library_dir = self._library_dir(library.id)
        library_dir.mkdir(parents=True, exist_ok=True)
        target_path = self._library_json_path(library.id)
        payload = json.dumps(library.to_dict(), indent=2)
        target_path.write_text(payload, encoding="utf-8")

    def _write_cover_art(
        self,
        library_id: str,
        track_id: str,
        cover_art_bytes: bytes,
        cover_art_extension: str,
    ) -> str:
        extension = cover_art_extension.lower().strip() or ".jpg"
        if not extension.startswith("."):
            extension = f".{extension}"

        cover_name = f"{track_id}{extension}"
        cover_path = self.library_covers_dir(library_id) / cover_name
        cover_path.write_bytes(cover_art_bytes)
        return cover_name

    @staticmethod
    def _find_track(library: Library, track_id: str) -> Track:
        for track in library.tracks:
            if track.id == track_id:
                return track
        raise TrackNotFoundError(track_id)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _unlink_with_retries(path: Path, attempts: int = 10, delay_seconds: float = 0.05) -> None:
    last_error: PermissionError | None = None
    for _ in range(attempts):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError as exc:
            last_error = exc
            try:
                os.chmod(path, stat.S_IWRITE)
            except OSError:
                pass
            time.sleep(delay_seconds)
    if last_error is not None:
        raise last_error


def _rmtree_with_retries(path: Path, attempts: int = 10, delay_seconds: float = 0.05) -> None:
    last_error: PermissionError | None = None

    def on_error(_func, failed_path, exc_info):
        nonlocal last_error
        error = exc_info[1]
        if isinstance(error, PermissionError):
            last_error = error
            try:
                os.chmod(failed_path, stat.S_IWRITE)
            except OSError:
                pass
            raise error
        raise error

    for _ in range(attempts):
        try:
            shutil.rmtree(path, onerror=on_error)
            return
        except FileNotFoundError:
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(delay_seconds)

    if last_error is not None:
        raise last_error
