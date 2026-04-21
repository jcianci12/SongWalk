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


class CollectionNotFoundError(FileNotFoundError):
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
    source_kind: str = "uploaded"
    source_path: str = ""
    source_external_id: str = ""
    source_available: bool = True
    duration_seconds: float = 0.0
    genre: str = ""
    album_artist: str = ""
    play_count: int = 0
    last_played_at: str = ""

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
            source_kind=payload.get("source_kind", "uploaded"),
            source_path=payload.get("source_path", ""),
            source_external_id=payload.get("source_external_id", ""),
            source_available=payload.get("source_available", True),
            duration_seconds=float(payload.get("duration_seconds", 0.0) or 0.0),
            genre=payload.get("genre", ""),
            album_artist=payload.get("album_artist", ""),
            play_count=int(payload.get("play_count", 0) or 0),
            last_played_at=payload.get("last_played_at", ""),
        )

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["uploaded_at"] = self.uploaded_at.isoformat()
        payload["updated_at"] = self.updated_at.isoformat()
        return payload


@dataclass
class Collection:
    id: str
    name: str
    track_ids: list[str]
    created_at: datetime
    updated_at: datetime
    source_kind: str = "manual"
    source_external_id: str = ""

    @classmethod
    def from_dict(cls, payload: dict) -> "Collection":
        return cls(
            id=payload["id"],
            name=payload.get("name", ""),
            track_ids=[str(track_id) for track_id in payload.get("track_ids", [])],
            created_at=datetime.fromisoformat(payload["created_at"]),
            updated_at=datetime.fromisoformat(payload["updated_at"]),
            source_kind=payload.get("source_kind", "manual"),
            source_external_id=payload.get("source_external_id", ""),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "track_ids": self.track_ids,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "source_kind": self.source_kind,
            "source_external_id": self.source_external_id,
        }


@dataclass
class Library:
    id: str
    created_at: datetime
    updated_at: datetime
    name: str = ""
    collections: list[Collection] = field(default_factory=list)
    tracks: list[Track] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict) -> "Library":
        return cls(
            id=payload["id"],
            created_at=datetime.fromisoformat(payload["created_at"]),
            updated_at=datetime.fromisoformat(payload["updated_at"]),
            name=payload.get("name", ""),
            collections=[Collection.from_dict(item) for item in payload.get("collections", [])],
            tracks=[Track.from_dict(item) for item in payload.get("tracks", [])],
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "name": self.name,
            "collections": [collection.to_dict() for collection in self.collections],
            "tracks": [track.to_dict() for track in self.tracks],
        }

    @property
    def display_name(self) -> str:
        name = self.name.strip()
        return name or self.id


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

    def create_library(self, *, name: str = "") -> Library:
        with self._lock:
            for _ in range(5):
                library_id = str(uuid.uuid4())
                library_dir = self._library_dir(library_id)
                if library_dir.exists():
                    continue

                files_dir = library_dir / "files"
                files_dir.mkdir(parents=True, exist_ok=False)
                now = _now()
                library = Library(id=library_id, created_at=now, updated_at=now, name=name.strip())
                self._write_library(library)
                return library
        raise RuntimeError("unable to allocate library id")

    def rename_library(self, library_id: str, *, name: str) -> Library:
        with self._lock:
            library = self.get_library(library_id)
            library.name = name.strip()
            library.updated_at = _now()
            self._write_library(library)
            return library

    def create_collection(self, library_id: str, *, name: str, track_ids: list[str]) -> Collection:
        with self._lock:
            library = self.get_library(library_id)
            normalized_name = name.strip()
            if not normalized_name:
                raise ValueError("Collection name is required.")

            selected_track_ids = self._normalize_track_ids(library, track_ids)
            if not selected_track_ids:
                raise ValueError("Choose at least one album to group.")

            now = _now()
            self._remove_track_ids_from_collections_locked(library, selected_track_ids)
            collection = Collection(
                id=str(uuid.uuid4()),
                name=normalized_name,
                track_ids=selected_track_ids,
                created_at=now,
                updated_at=now,
            )
            library.collections.append(collection)
            library.updated_at = now
            self._write_library(library)
            return collection

    def add_tracks_to_collection(self, library_id: str, collection_id: str, *, track_ids: list[str]) -> Collection:
        with self._lock:
            library = self.get_library(library_id)
            collection = self._find_collection(library, collection_id)
            selected_track_ids = self._normalize_track_ids(library, track_ids)
            if not selected_track_ids:
                raise ValueError("Choose at least one album to group.")

            self._remove_track_ids_from_collections_locked(library, selected_track_ids, except_collection_id=collection_id)
            collection.track_ids = _unique_strings([*collection.track_ids, *selected_track_ids])
            collection.updated_at = _now()
            library.updated_at = collection.updated_at
            self._prune_empty_collections_locked(library)
            self._write_library(library)
            return collection

    def remove_tracks_from_collections(self, library_id: str, *, track_ids: list[str]) -> int:
        with self._lock:
            library = self.get_library(library_id)
            selected_track_ids = self._normalize_track_ids(library, track_ids)
            if not selected_track_ids:
                return 0

            removed = self._remove_track_ids_from_collections_locked(library, selected_track_ids)
            if removed:
                library.updated_at = _now()
                self._write_library(library)
            return removed

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

    def sync_linked_tracks(
        self,
        library_id: str,
        *,
        source_kind: str,
        tracks: list[dict],
        mark_missing_unavailable: bool = True,
    ) -> dict:
        clean_source_kind = source_kind.strip().lower()
        if not clean_source_kind or clean_source_kind == "uploaded":
            raise ValueError("A non-uploaded source kind is required.")

        with self._lock:
            library = self.get_library(library_id)
            now = _now()
            existing_by_key = {
                track.source_external_id: track
                for track in library.tracks
                if track.source_kind == clean_source_kind and track.source_external_id
            }
            existing_by_path = {
                track.source_path.casefold(): track
                for track in library.tracks
                if track.source_kind == clean_source_kind and track.source_path
            }
            seen_track_ids: set[str] = set()
            created = 0
            updated = 0
            skipped = 0

            for payload in tracks:
                source_path = str(payload.get("source_path", "")).strip()
                if not source_path:
                    skipped += 1
                    continue

                source_external_id = str(payload.get("source_external_id", "")).strip() or source_path
                track = existing_by_key.get(source_external_id) or existing_by_path.get(source_path.casefold())
                if track is None:
                    track = Track(
                        id=str(uuid.uuid4()),
                        original_name=str(payload.get("original_name", "")).strip() or Path(source_path).name,
                        stored_name="",
                        content_type=str(payload.get("content_type", "")).strip()
                        or mimetypes.guess_type(source_path)[0]
                        or "application/octet-stream",
                        size=_int_value(payload.get("size")),
                        uploaded_at=now,
                        updated_at=now,
                        source_kind=clean_source_kind,
                        source_path=source_path,
                        source_external_id=source_external_id,
                    )
                    library.tracks.append(track)
                    created += 1
                else:
                    updated += 1

                track.original_name = str(payload.get("original_name", "")).strip() or Path(source_path).name
                track.content_type = (
                    str(payload.get("content_type", "")).strip()
                    or mimetypes.guess_type(track.original_name or source_path)[0]
                    or "application/octet-stream"
                )
                track.size = _int_value(payload.get("size"))
                track.title = str(payload.get("title", "")).strip() or Path(track.original_name).stem
                track.artist = str(payload.get("artist", "")).strip()
                track.album = str(payload.get("album", "")).strip()
                track.rating = clamp_rating(payload.get("rating", 0))
                track.source_kind = clean_source_kind
                track.source_path = source_path
                track.source_external_id = source_external_id
                track.source_available = bool(payload.get("source_available", True))
                track.duration_seconds = _float_value(payload.get("duration_seconds"))
                track.genre = str(payload.get("genre", "")).strip()
                track.album_artist = str(payload.get("album_artist", "")).strip()
                track.play_count = _int_value(payload.get("play_count"))
                track.last_played_at = str(payload.get("last_played_at", "")).strip()
                track.updated_at = now
                seen_track_ids.add(track.id)

            marked_unavailable = 0
            if mark_missing_unavailable:
                for track in library.tracks:
                    if track.source_kind != clean_source_kind or track.id in seen_track_ids:
                        continue
                    if track.source_available:
                        marked_unavailable += 1
                    track.source_available = False
                    track.updated_at = now

            if created or updated or marked_unavailable:
                library.updated_at = now
                self._write_library(library)

            return {
                "created": created,
                "updated": updated,
                "skipped": skipped,
                "marked_unavailable": marked_unavailable,
                "total": created + updated,
            }

    def mark_linked_tracks_unavailable_except(
        self,
        library_id: str,
        *,
        source_kind: str,
        source_external_ids: set[str],
    ) -> int:
        clean_source_kind = source_kind.strip().lower()
        with self._lock:
            library = self.get_library(library_id)
            now = _now()
            marked_unavailable = 0
            for track in library.tracks:
                if track.source_kind != clean_source_kind:
                    continue
                if track.source_external_id in source_external_ids:
                    continue
                if track.source_available:
                    marked_unavailable += 1
                track.source_available = False
                track.updated_at = now

            if marked_unavailable:
                library.updated_at = now
                self._write_library(library)
            return marked_unavailable

    def sync_linked_collections(self, library_id: str, *, source_kind: str, collections: list[dict]) -> dict:
        clean_source_kind = source_kind.strip().lower()
        if not clean_source_kind or clean_source_kind == "manual":
            raise ValueError("A non-manual source kind is required.")

        with self._lock:
            library = self.get_library(library_id)
            now = _now()
            track_id_by_external_id = {
                track.source_external_id: track.id
                for track in library.tracks
                if track.source_external_id
            }
            track_id_by_source_path = {
                track.source_path.casefold(): track.id
                for track in library.tracks
                if track.source_path
            }
            existing_by_key = {
                collection.source_external_id: collection
                for collection in library.collections
                if collection.source_kind == clean_source_kind and collection.source_external_id
            }
            seen_keys: set[str] = set()
            created = 0
            updated = 0
            skipped = 0

            for payload in collections:
                name = str(payload.get("name", "")).strip()
                source_external_id = str(payload.get("source_external_id", "")).strip() or name
                if not name or not source_external_id:
                    skipped += 1
                    continue

                track_ids: list[str] = []
                for external_id in payload.get("track_source_external_ids", []):
                    track_id = track_id_by_external_id.get(str(external_id).strip())
                    if track_id and track_id not in track_ids:
                        track_ids.append(track_id)
                for source_path in payload.get("track_source_paths", []):
                    track_id = track_id_by_source_path.get(str(source_path).strip().casefold())
                    if track_id and track_id not in track_ids:
                        track_ids.append(track_id)

                if not track_ids:
                    skipped += 1
                    continue

                collection = existing_by_key.get(source_external_id)
                if collection is None:
                    collection = Collection(
                        id=str(uuid.uuid4()),
                        name=name,
                        track_ids=track_ids,
                        created_at=now,
                        updated_at=now,
                        source_kind=clean_source_kind,
                        source_external_id=source_external_id,
                    )
                    library.collections.append(collection)
                    created += 1
                else:
                    collection.name = name
                    collection.track_ids = track_ids
                    collection.updated_at = now
                    updated += 1

                collection.source_kind = clean_source_kind
                collection.source_external_id = source_external_id
                seen_keys.add(source_external_id)

            before_count = len(library.collections)
            library.collections = [
                collection
                for collection in library.collections
                if collection.source_kind != clean_source_kind or collection.source_external_id in seen_keys
            ]
            removed = before_count - len(library.collections)

            if created or updated or removed:
                library.updated_at = now
                self._write_library(library)

            return {
                "created": created,
                "updated": updated,
                "removed": removed,
                "skipped": skipped,
                "total": created + updated,
            }

    def update_track(
        self,
        library_id: str,
        track_id: str,
        *,
        title: str,
        artist: str,
        album: str,
        rating: int | str = 0,
        write_file_tags: bool = True,
    ) -> Track:
        with self._lock:
            library = self.get_library(library_id)
            track = self._find_track(library, track_id)
            track.title = title.strip()
            track.artist = artist.strip()
            track.album = album.strip()
            track.rating = clamp_rating(rating)
            if write_file_tags and track.source_kind == "uploaded":
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

    def set_track_rating(
        self,
        library_id: str,
        track_id: str,
        *,
        rating: int | str,
        write_file_tags: bool = True,
    ) -> Track:
        with self._lock:
            library = self.get_library(library_id)
            track = self._find_track(library, track_id)
            track.rating = clamp_rating(rating)
            if write_file_tags and track.source_kind == "uploaded":
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
                if track.source_kind == "uploaded":
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
        if track.source_kind == "uploaded":
            file_path = self.library_files_dir(library_id) / track.stored_name
        else:
            file_path = Path(track.source_path).expanduser()
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

    @staticmethod
    def _find_collection(library: Library, collection_id: str) -> Collection:
        for collection in library.collections:
            if collection.id == collection_id:
                return collection
        raise CollectionNotFoundError(collection_id)

    @staticmethod
    def _normalize_track_ids(library: Library, track_ids: list[str]) -> list[str]:
        valid_track_ids = {track.id for track in library.tracks}
        return [track_id for track_id in _unique_strings(track_ids) if track_id in valid_track_ids]

    @staticmethod
    def _prune_empty_collections_locked(library: Library) -> None:
        library.collections = [collection for collection in library.collections if collection.track_ids]

    def _remove_track_ids_from_collections_locked(
        self,
        library: Library,
        track_ids: list[str],
        *,
        except_collection_id: str = "",
    ) -> int:
        target_ids = set(track_ids)
        removed = 0

        for collection in library.collections:
            if except_collection_id and collection.id == except_collection_id:
                continue

            next_track_ids = [track_id for track_id in collection.track_ids if track_id not in target_ids]
            removed += len(collection.track_ids) - len(next_track_ids)
            if next_track_ids != collection.track_ids:
                collection.track_ids = next_track_ids
                collection.updated_at = _now()

        self._prune_empty_collections_locked(library)
        return removed

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


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


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
