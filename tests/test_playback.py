from __future__ import annotations

import io
import uuid
import unittest
from pathlib import Path

from songwalk import create_app
from songwalk.store import UploadedTrack

from tests.test_app import FakeLookupClient, new_test_dir


class PlaybackTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = new_test_dir()
        self.app = create_app(
            {
                "TESTING": True,
                "DATA_DIR": self.temp_dir,
                "BASE_URL": "http://localhost:8080",
                "LOOKUP_CLIENT": FakeLookupClient(),
            }
        )
        self.client = self.app.test_client()
        self.store = self.app.config["STORE"]

        self.library = self.store.create_library()
        self.library_id = self.library.id

        self.track_bytes = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 1024
        self.track = self.store.add_track(
            self.library_id,
            UploadedTrack(
                filename="demo.mp3",
                content_type="audio/mpeg",
                stream=io.BytesIO(self.track_bytes),
            ),
        )
        self.track_id = self.track.id

    def tearDown(self) -> None:
        pass

    def test_stream_track_returns_200(self) -> None:
        response = self.client.get(
            f"/s/{self.library_id}/tracks/{self.track_id}/file",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, "audio/mpeg")
        self.assertEqual(response.data, self.track_bytes)

    def test_stream_track_404_for_missing(self) -> None:
        fake_id = str(uuid.uuid4())
        response = self.client.get(
            f"/s/{self.library_id}/tracks/{fake_id}/file",
        )
        self.assertEqual(response.status_code, 404)

    def test_library_state_includes_sync_state(self) -> None:
        response = self.client.get(
            f"/s/{self.library_id}/state",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertIsNotNone(payload["library"])
        self.assertEqual(payload["library"]["id"], self.library_id)
        self.assertIn("sync_state", payload)
        self.assertIn("import_job", payload)
        self.assertIn("import_active", payload)

    def test_track_file_supports_range_requests(self) -> None:
        response = self.client.get(
            f"/s/{self.library_id}/tracks/{self.track_id}/file",
            headers={"Range": "bytes=0-100"},
        )
        self.assertEqual(response.status_code, 206)
        self.assertIn("Content-Range", response.headers)
        self.assertIn("bytes 0-100", response.headers["Content-Range"])

    def test_stream_track_conditional_etag(self) -> None:
        response = self.client.get(
            f"/s/{self.library_id}/tracks/{self.track_id}/file",
        )
        self.assertEqual(response.status_code, 200)
        etag = response.headers.get("ETag")
        self.assertIsNotNone(etag)

        cached_response = self.client.get(
            f"/s/{self.library_id}/tracks/{self.track_id}/file",
            headers={"If-None-Match": etag},
        )
        self.assertEqual(cached_response.status_code, 304)

    def test_cover_art_404_for_missing(self) -> None:
        response = self.client.get(
            f"/s/{self.library_id}/covers/nonexistent.jpg",
        )
        self.assertEqual(response.status_code, 404)

    def test_cover_art_404_for_missing_library(self) -> None:
        fake_id = str(uuid.uuid4())
        response = self.client.get(
            f"/s/{fake_id}/covers/foo.jpg",
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
