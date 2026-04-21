from __future__ import annotations

import io
import unittest
import uuid
from pathlib import Path

from mutagen.id3 import ID3

from songshare.store import Store, UploadedTrack


def _resolve_test_tmp_root() -> Path:
    for candidate in (
        Path.home() / ".codex" / "memories" / "songshare-tests",
        Path(__file__).resolve().parents[1] / ".tmp-tests",
    ):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except PermissionError:
            continue
    raise PermissionError("No writable test temp directory available.")


TEST_TMP_ROOT = _resolve_test_tmp_root()
TEST_DATA_ROOT = TEST_TMP_ROOT / "data"


def new_test_dir() -> Path:
    path = TEST_DATA_ROOT / str(uuid.uuid4())
    path.mkdir(parents=True, exist_ok=False)
    return path


class StoreTestCase(unittest.TestCase):
    def test_library_name_lifecycle(self) -> None:
        temp_dir = new_test_dir()
        store = Store(temp_dir)
        library = store.create_library(name="Road Trip")

        self.assertEqual(library.name, "Road Trip")
        self.assertEqual(library.display_name, "Road Trip")

        renamed = store.rename_library(library.id, name="Late Night")
        self.assertEqual(renamed.name, "Late Night")
        self.assertEqual(renamed.display_name, "Late Night")

        loaded = store.get_library(library.id)
        self.assertEqual(loaded.name, "Late Night")
        self.assertEqual(loaded.display_name, "Late Night")

        cleared = store.rename_library(library.id, name="  ")
        self.assertEqual(cleared.name, "")
        self.assertEqual(cleared.display_name, library.id)

    def test_track_lifecycle(self) -> None:
        temp_dir = new_test_dir()
        store = Store(temp_dir)
        library = store.create_library()

        track = store.add_track(
            library.id,
            UploadedTrack(
                filename="anthem.mp3",
                content_type="audio/mpeg",
                stream=io.BytesIO(b"FAKE-sample-data"),
            ),
        )

        loaded = store.get_library(library.id)
        self.assertEqual(len(loaded.tracks), 1)
        self.assertEqual(loaded.tracks[0].title, "anthem")

        store.update_track(library.id, track.id, title="Anthem", artist="Jon", album="V1", rating=4)
        updated = store.get_library(library.id)
        self.assertEqual(updated.tracks[0].title, "Anthem")
        self.assertEqual(updated.tracks[0].artist, "Jon")
        self.assertEqual(updated.tracks[0].album, "V1")
        self.assertEqual(updated.tracks[0].rating, 4)

        track_meta, file_path = store.get_track_file(library.id, track.id)
        self.assertEqual(track_meta.id, track.id)
        self.assertTrue(file_path.exists())

        tags = ID3(file_path)
        self.assertEqual(str(tags["TIT2"]), "Anthem")
        self.assertEqual(str(tags["TPE1"]), "Jon")
        self.assertEqual(str(tags["TALB"]), "V1")
        self.assertEqual(tags.getall("POPM")[0].rating, 196)

        store.delete_track(library.id, track.id)
        after_delete = store.get_library(library.id)
        self.assertEqual(len(after_delete.tracks), 0)
        self.assertFalse(file_path.exists())

    def test_collection_lifecycle(self) -> None:
        temp_dir = new_test_dir()
        store = Store(temp_dir)
        library = store.create_library()

        first = store.add_track(
            library.id,
            UploadedTrack(filename="one.mp3", content_type="audio/mpeg", stream=io.BytesIO(b"ID3-one")),
        )
        second = store.add_track(
            library.id,
            UploadedTrack(filename="two.mp3", content_type="audio/mpeg", stream=io.BytesIO(b"ID3-two")),
        )

        collection = store.create_collection(library.id, name="Singles", track_ids=[first.id])
        self.assertEqual(collection.name, "Singles")
        self.assertEqual(collection.track_ids, [first.id])

        updated = store.add_tracks_to_collection(library.id, collection.id, track_ids=[second.id])
        self.assertEqual(updated.track_ids, [first.id, second.id])

        removed = store.remove_tracks_from_collections(library.id, track_ids=[first.id])
        self.assertEqual(removed, 1)
        loaded = store.get_library(library.id)
        self.assertEqual(loaded.collections[0].track_ids, [second.id])

        removed = store.remove_tracks_from_collections(library.id, track_ids=[second.id])
        self.assertEqual(removed, 1)
        loaded = store.get_library(library.id)
        self.assertEqual(loaded.collections, [])

    def test_sync_linked_tracks_upserts_without_copying_or_deleting_source(self) -> None:
        temp_dir = new_test_dir()
        source_dir = temp_dir / "external"
        source_dir.mkdir()
        source_file = source_dir / "demo.mp3"
        source_file.write_bytes(b"external-audio")
        store = Store(temp_dir / "store")
        library = store.create_library(name="Windows Media Player")

        first = store.sync_linked_tracks(
            library.id,
            source_kind="wmp",
            tracks=[
                {
                    "source_path": str(source_file),
                    "source_external_id": "wmp-1",
                    "original_name": "demo.mp3",
                    "content_type": "audio/mpeg",
                    "size": source_file.stat().st_size,
                    "title": "Demo",
                    "artist": "Artist",
                    "album": "Album",
                    "rating": 4,
                }
            ],
        )
        self.assertEqual(first["created"], 1)
        self.assertEqual(first["updated"], 0)

        loaded = store.get_library(library.id)
        self.assertEqual(len(loaded.tracks), 1)
        self.assertEqual(loaded.tracks[0].source_kind, "wmp")
        self.assertEqual(loaded.tracks[0].source_path, str(source_file))

        second = store.sync_linked_tracks(
            library.id,
            source_kind="wmp",
            tracks=[
                {
                    "source_path": str(source_file),
                    "source_external_id": "wmp-1",
                    "original_name": "demo.mp3",
                    "content_type": "audio/mpeg",
                    "size": source_file.stat().st_size,
                    "title": "Demo Updated",
                    "artist": "Artist",
                    "album": "Album",
                    "rating": 5,
                }
            ],
        )
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["updated"], 1)
        loaded = store.get_library(library.id)
        self.assertEqual(len(loaded.tracks), 1)
        self.assertEqual(loaded.tracks[0].title, "Demo Updated")

        track, file_path = store.get_track_file(library.id, loaded.tracks[0].id)
        self.assertEqual(track.source_kind, "wmp")
        self.assertEqual(file_path, source_file)

        store.delete_track(library.id, loaded.tracks[0].id)
        self.assertTrue(source_file.exists())

    def test_chunked_linked_sync_marks_missing_only_after_final_pass(self) -> None:
        temp_dir = new_test_dir()
        store = Store(temp_dir)
        library = store.create_library(name="Windows Media Player")

        store.sync_linked_tracks(
            library.id,
            source_kind="wmp",
            tracks=[
                {"source_path": str(temp_dir / "one.mp3"), "source_external_id": "one", "title": "One"},
                {"source_path": str(temp_dir / "two.mp3"), "source_external_id": "two", "title": "Two"},
            ],
        )

        store.sync_linked_tracks(
            library.id,
            source_kind="wmp",
            tracks=[
                {"source_path": str(temp_dir / "one.mp3"), "source_external_id": "one", "title": "One updated"},
            ],
            mark_missing_unavailable=False,
        )
        after_chunk = store.get_library(library.id)
        self.assertTrue(next(track for track in after_chunk.tracks if track.source_external_id == "two").source_available)

        marked = store.mark_linked_tracks_unavailable_except(
            library.id,
            source_kind="wmp",
            source_external_ids={"one"},
        )
        self.assertEqual(marked, 1)
        after_final = store.get_library(library.id)
        self.assertTrue(next(track for track in after_final.tracks if track.source_external_id == "one").source_available)
        self.assertFalse(next(track for track in after_final.tracks if track.source_external_id == "two").source_available)

    def test_sync_linked_collections_maps_external_track_ids_and_removes_missing(self) -> None:
        temp_dir = new_test_dir()
        store = Store(temp_dir)
        library = store.create_library(name="Windows Media Player")
        store.sync_linked_tracks(
            library.id,
            source_kind="wmp",
            tracks=[
                {"source_path": str(temp_dir / "one.mp3"), "source_external_id": "one", "title": "One"},
                {"source_path": str(temp_dir / "two.mp3"), "source_external_id": "two", "title": "Two"},
            ],
        )

        first = store.sync_linked_collections(
            library.id,
            source_kind="wmp_playlist",
            collections=[
                {
                    "name": "Favorites",
                    "source_external_id": "playlist-one",
                    "track_source_external_ids": ["one", "two"],
                }
            ],
        )
        self.assertEqual(first["created"], 1)
        loaded = store.get_library(library.id)
        self.assertEqual(len(loaded.collections), 1)
        self.assertEqual(loaded.collections[0].name, "Favorites")
        self.assertEqual(loaded.collections[0].source_kind, "wmp_playlist")
        self.assertEqual(len(loaded.collections[0].track_ids), 2)

        second = store.sync_linked_collections(
            library.id,
            source_kind="wmp_playlist",
            collections=[
                {
                    "name": "Favorites renamed",
                    "source_external_id": "playlist-one",
                    "track_source_external_ids": ["one"],
                }
            ],
        )
        self.assertEqual(second["updated"], 1)
        loaded = store.get_library(library.id)
        self.assertEqual(len(loaded.collections), 1)
        self.assertEqual(loaded.collections[0].name, "Favorites renamed")
        self.assertEqual(len(loaded.collections[0].track_ids), 1)

        empty = store.sync_linked_collections(library.id, source_kind="wmp_playlist", collections=[])
        self.assertEqual(empty["removed"], 1)
        self.assertEqual(store.get_library(library.id).collections, [])


if __name__ == "__main__":
    unittest.main()
