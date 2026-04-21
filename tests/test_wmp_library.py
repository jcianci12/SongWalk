from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from songshare.wmp_library import (
    WMP_LIBRARY_NAME,
    WMP_PLAYLIST_SOURCE_KIND,
    WMP_SOURCE_KIND,
    WmpLibraryService,
    WmpPlaylist,
    WmpTrack,
    _playlist_from_payload,
    _source_url_to_path,
)


class FakeWmpItemCollection:
    def __init__(self, items):
        self._items = list(items)

    @property
    def count(self) -> int:
        return len(self._items)

    def Item(self, index: int):
        return self._items[index]


class FakeWmpSettings:
    def __init__(self, *, rights: str = "none"):
        self.mediaAccessRights = rights
        self.requested_rights: list[str] = []

    def requestMediaAccessRights(self, rights: str) -> None:
        self.requested_rights.append(rights)
        self.mediaAccessRights = rights


class FakeWmpMedia:
    def __init__(self, *, source_url: str, attributes: dict[str, object]):
        self.sourceURL = source_url
        self._attributes = dict(attributes)

    def getItemInfo(self, name: str) -> str:
        return str(self._attributes.get(name, "") or "")


class FakeWmpPlaylist:
    def __init__(self, *, name: str, items, attributes: dict[str, object] | None = None):
        self.name = name
        self._items = list(items)
        self._attributes = dict(attributes or {})

    @property
    def count(self) -> int:
        return len(self._items)

    def Item(self, index: int):
        return self._items[index]

    def getItemInfo(self, name: str) -> str:
        return str(self._attributes.get(name, "") or "")


class FakeWmpMediaCollection:
    def __init__(self, items):
        self._items = list(items)

    def getAll(self) -> FakeWmpItemCollection:
        return FakeWmpItemCollection(self._items)


class FakeWmpPlaylistCollection:
    def __init__(self, items):
        self._items = list(items)

    def getAll(self) -> FakeWmpItemCollection:
        return FakeWmpItemCollection(self._items)


class FakeWmpPlayer:
    def __init__(self, *, tracks, playlists=(), rights: str = "none"):
        self.settings = FakeWmpSettings(rights=rights)
        self.mediaCollection = FakeWmpMediaCollection(tracks)
        self.playlistCollection = FakeWmpPlaylistCollection(playlists)


class RecordingWmpRunner:
    def __init__(self, player: FakeWmpPlayer, events: list[str]):
        self.player = player
        self.events = events

    def __call__(self, script: str, *, timeout_seconds: int):
        if "mediaCollection.getAll()" in script:
            yield from self._iter_tracks(script)
            return
        if "playlistCollection.getAll()" in script:
            yield from self._iter_playlists()
            return
        raise AssertionError(f"Unexpected WMP script: {script[:120]}")

    def _iter_tracks(self, script: str):
        self.events.append("read_tracks")
        self._ensure_access()
        limit = _extract_limit(script)
        emitted = 0
        playlist = self.player.mediaCollection.getAll()
        for index in range(playlist.count):
            media = playlist.Item(index)
            if media.getItemInfo("MediaType").casefold() != "audio":
                continue
            payload = {
                "title": media.getItemInfo("Title"),
                "artist": media.getItemInfo("Author"),
                "display_artist": media.getItemInfo("DisplayArtist"),
                "album": media.getItemInfo("WM/AlbumTitle"),
                "album_fallback": media.getItemInfo("Album"),
                "album_artist": media.getItemInfo("WM/AlbumArtist"),
                "genre": media.getItemInfo("WM/Genre"),
                "rating": media.getItemInfo("UserRating"),
                "effective_rating": media.getItemInfo("UserEffectiveRating"),
                "play_count": media.getItemInfo("UserPlayCount"),
                "last_played_at": media.getItemInfo("UserLastPlayedTime"),
                "source_url": media.sourceURL,
                "tracking_id": media.getItemInfo("TrackingID"),
                "duration": media.getItemInfo("Duration"),
                "file_size": media.getItemInfo("FileSize"),
            }
            external_id = payload["tracking_id"] or payload["source_url"]
            self.events.append(f"yield_track:{external_id}")
            yield json.dumps(payload)
            emitted += 1
            if limit > 0 and emitted >= limit:
                break

    def _iter_playlists(self):
        self.events.append("read_playlists")
        self._ensure_access()
        playlists = self.player.playlistCollection.getAll()
        for index in range(playlists.count):
            playlist = playlists.Item(index)
            name = playlist.name.strip()
            if not name:
                continue
            playlist_type = playlist.getItemInfo("PlaylistType")
            if playlist_type.casefold() != "wpl":
                continue
            track_ids: list[str] = []
            source_urls: list[str] = []
            for item_index in range(playlist.count):
                media = playlist.Item(item_index)
                if media.getItemInfo("MediaType").casefold() != "audio":
                    continue
                tracking_id = media.getItemInfo("TrackingID").strip()
                if tracking_id and tracking_id not in track_ids:
                    track_ids.append(tracking_id)
                source_url = media.sourceURL.strip()
                if source_url and source_url not in source_urls:
                    source_urls.append(source_url)
            if not track_ids and not source_urls:
                continue
            payload = {
                "name": name,
                "source_external_id": playlist.getItemInfo("TrackingID").strip() or name.casefold(),
                "playlist_type": playlist_type,
                "track_source_external_ids": track_ids,
                "track_source_urls": source_urls,
            }
            yield json.dumps(payload)

    def _ensure_access(self) -> None:
        rights = self.player.settings.mediaAccessRights.casefold()
        if rights in {"full", "read"}:
            return
        self.player.settings.requestMediaAccessRights("full")


class RecordingStore:
    def __init__(self, events: list[str] | None = None):
        self.libraries: list[object] = []
        self.calls: list[str] = []
        self.sync_batches: list[list[dict]] = []
        self.playlist_batches: list[list[dict]] = []
        self.mark_missing_calls: list[dict] = []
        self._next_id = 1
        self._events = events

    def list_libraries(self):
        self.calls.append("list_libraries")
        return list(self.libraries)

    def create_library(self, *, name: str = ""):
        self.calls.append(f"create_library:{name}")
        library = type("Library", (), {"id": f"library-{self._next_id}", "name": name})()
        self._next_id += 1
        self.libraries.append(library)
        return library

    def get_library(self, library_id: str):
        self.calls.append(f"get_library:{library_id}")
        for library in self.libraries:
            if library.id == library_id:
                return library
        raise AssertionError(f"Missing library {library_id}")

    def sync_linked_tracks(
        self,
        library_id: str,
        *,
        source_kind: str,
        tracks: list[dict],
        mark_missing_unavailable: bool = True,
    ) -> dict:
        self.calls.append(f"sync_linked_tracks:{len(tracks)}")
        if self._events is not None:
            self._events.append(f"sync_linked_tracks:{len(tracks)}")
        self.sync_batches.append(list(tracks))
        return {
            "created": len(tracks),
            "updated": 0,
            "skipped": 0,
            "marked_unavailable": 0,
            "total": len(tracks),
        }

    def mark_linked_tracks_unavailable_except(self, library_id: str, *, source_kind: str, source_external_ids: set[str]) -> int:
        self.calls.append(f"mark_missing:{len(source_external_ids)}")
        if self._events is not None:
            self._events.append(f"mark_missing:{len(source_external_ids)}")
        self.mark_missing_calls.append(
            {
                "library_id": library_id,
                "source_kind": source_kind,
                "source_external_ids": set(source_external_ids),
            }
        )
        return 0

    def sync_linked_collections(self, library_id: str, *, source_kind: str, collections: list[dict]) -> dict:
        self.calls.append(f"sync_linked_collections:{len(collections)}")
        if self._events is not None:
            self._events.append(f"sync_linked_collections:{len(collections)}")
        self.playlist_batches.append(list(collections))
        return {
            "created": len(collections),
            "updated": 0,
            "removed": 0,
            "skipped": 0,
            "total": len(collections),
        }


def _extract_limit(script: str) -> int:
    match = re.search(r"^\$limit = (\d+)$", script, re.MULTILINE)
    if not match:
        return 0
    return int(match.group(1))


def _build_fake_media(temp_dir: Path, index: int) -> FakeWmpMedia:
    source_file = temp_dir / f"track-{index}.mp3"
    source_file.write_bytes(f"track-{index}".encode("utf-8"))
    return FakeWmpMedia(
        source_url=source_file.as_uri(),
        attributes={
            "MediaType": "audio",
            "Title": f"Track {index}",
            "Author": f"Artist {index}",
            "DisplayArtist": f"Display Artist {index}",
            "WM/AlbumTitle": f"Album {index // 10}",
            "Album": f"Fallback Album {index // 10}",
            "WM/AlbumArtist": f"Album Artist {index // 10}",
            "WM/Genre": "Demo",
            "UserRating": "75",
            "UserEffectiveRating": "50",
            "UserPlayCount": str(index),
            "UserLastPlayedTime": f"2026-04-{(index % 28) + 1:02d}",
            "TrackingID": f"track-{index}",
            "Duration": "123.4",
            "FileSize": str(source_file.stat().st_size),
        },
    )


class WmpLibraryTestCase(unittest.TestCase):
    def test_file_url_is_converted_to_local_path(self) -> None:
        path = _source_url_to_path("file:///C:/Music/demo.mp3")
        self.assertTrue(path.endswith("C:\\Music\\demo.mp3") or path.endswith("/C:/Music/demo.mp3"))

    @unittest.skipUnless(os.name == "nt", "Windows drive paths are Windows-specific")
    def test_windows_drive_path_is_not_treated_as_url_scheme(self) -> None:
        self.assertEqual(_source_url_to_path("C:\\Music\\demo.mp3"), "C:\\Music\\demo.mp3")

    def test_playlist_payload_normalizes_track_references(self) -> None:
        playlist = _playlist_from_payload(
            {
                "name": "Favorites",
                "source_external_id": "playlist-1",
                "track_source_external_ids": ["track-1", "", "track-2"],
                "track_source_urls": ["file:///C:/Music/one.mp3"],
            }
        )

        self.assertIsNotNone(playlist)
        assert playlist is not None
        self.assertEqual(playlist.name, "Favorites")
        self.assertEqual(playlist.source_external_id, "playlist-1")
        self.assertEqual(playlist.track_source_external_ids, ["track-1", "track-2"])
        self.assertTrue(playlist.track_source_paths)

    def test_iter_audio_tracks_reads_from_fake_wmp_com_objects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)
            media_items = [_build_fake_media(temp_dir, 1), _build_fake_media(temp_dir, 2), _build_fake_media(temp_dir, 3)]
            player = FakeWmpPlayer(
                tracks=[FakeWmpMedia(source_url="file:///ignored.mp3", attributes={"MediaType": "video"})] + media_items,
                rights="none",
            )
            events: list[str] = []
            service = WmpLibraryService(powershell_runner=RecordingWmpRunner(player, events))

            tracks = list(service.iter_audio_tracks(limit=2))

            self.assertEqual(len(tracks), 2)
            self.assertEqual(tracks[0].title, "Track 1")
            self.assertEqual(tracks[0].artist, "Artist 1")
            self.assertEqual(tracks[0].album, "Album 0")
            self.assertEqual(tracks[0].source_external_id, "track-1")
            self.assertTrue(tracks[0].source_path.endswith("track-1.mp3"))
            self.assertTrue(tracks[0].source_available)
            self.assertEqual(player.settings.requested_rights, ["full"])
            self.assertEqual(events[0], "read_tracks")
            self.assertEqual(events[1], "yield_track:track-1")
            self.assertEqual(events[2], "yield_track:track-2")

    def test_sync_to_store_reports_current_track_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)
            media_items = [_build_fake_media(temp_dir, 1), _build_fake_media(temp_dir, 2)]
            player = FakeWmpPlayer(tracks=media_items, rights="full")
            runner = RecordingWmpRunner(player, [])
            service = WmpLibraryService(chunk_size=1, powershell_runner=runner)
            store = RecordingStore()
            updates: list[tuple[str, str, int | None, str]] = []

            def progress(update) -> None:
                updates.append((update.phase, update.message, update.percent, update.current_item))

            result = service.sync_to_store(store, progress_callback=progress)

            self.assertTrue(result.ok)
            self.assertEqual(updates[0], ("syncing_tracks", "Syncing Windows Media Player tracks...", 5, ""))
            self.assertEqual(updates[1][0], "syncing_tracks")
            self.assertEqual(updates[1][1], "Syncing WMP track 1...")
            self.assertIsNone(updates[1][2])
            self.assertTrue(updates[1][3].endswith("track-1.mp3"))
            self.assertEqual(updates[2][0], "syncing_tracks")
            self.assertEqual(updates[2][1], "Syncing WMP track 2...")
            self.assertIsNone(updates[2][2])
            self.assertTrue(updates[2][3].endswith("track-2.mp3"))
            self.assertEqual(updates[-1][0], "complete")
            self.assertEqual(updates[-1][1], "Windows Media Player sync finished.")
            self.assertEqual(updates[-1][2], 100)
            self.assertTrue(updates[-1][3].endswith("track-2.mp3"))

    def test_sync_to_store_imports_large_libraries_in_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)
            media_items = [_build_fake_media(temp_dir, index) for index in range(1, 54)]
            playlist = FakeWmpPlaylist(
                name="Favorites",
                items=media_items[:3],
                attributes={"PlaylistType": "wpl", "TrackingID": "playlist-1"},
            )
            player = FakeWmpPlayer(tracks=media_items, playlists=[playlist], rights="full")
            events: list[str] = []
            runner = RecordingWmpRunner(player, events)
            service = WmpLibraryService(chunk_size=25, powershell_runner=runner)
            store = RecordingStore(events)

            result = service.sync_to_store(store)

            self.assertTrue(result.ok)
            self.assertEqual(result.library_id, "library-1")
            self.assertEqual(result.created, 53)
            self.assertEqual(result.total, 53)
            self.assertEqual([len(batch) for batch in store.sync_batches], [25, 25, 3])
            self.assertEqual(
                store.mark_missing_calls,
                [
                    {
                        "library_id": "library-1",
                        "source_kind": WMP_SOURCE_KIND,
                        "source_external_ids": {f"track-{index}" for index in range(1, 54)},
                    }
                ],
            )
            self.assertEqual([len(batch) for batch in store.playlist_batches], [1])
            self.assertEqual(
                events,
                [
                    "read_tracks",
                    *[f"yield_track:track-{index}" for index in range(1, 26)],
                    "sync_linked_tracks:25",
                    *[f"yield_track:track-{index}" for index in range(26, 51)],
                    "sync_linked_tracks:25",
                    *[f"yield_track:track-{index}" for index in range(51, 54)],
                    "sync_linked_tracks:3",
                    "mark_missing:53",
                    "read_playlists",
                    "sync_linked_collections:1",
                ],
            )
            self.assertEqual(store.sync_batches[0][0]["source_external_id"], "track-1")
            self.assertEqual(store.playlist_batches[0][0]["source_external_id"], "playlist-1")
            self.assertEqual(WMP_LIBRARY_NAME, "Windows Media Player")
            self.assertEqual(WMP_PLAYLIST_SOURCE_KIND, "wmp_playlist")


if __name__ == "__main__":
    unittest.main()
