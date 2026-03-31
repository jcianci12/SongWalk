from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from mutagen.id3 import ID3

from songshare.store import Store, UploadedTrack


class StoreTestCase(unittest.TestCase):
    def test_track_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Store(Path(temp_dir))
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


if __name__ == "__main__":
    unittest.main()
