from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from songshare import create_app


class SongshareAppTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "DATA_DIR": Path(self.temp_dir.name),
                "BASE_URL": "http://localhost:8080",
            }
        )
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_create_library_and_upload_track(self) -> None:
        response = self.client.post("/libraries", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        library_path = response.headers["Location"].split("?", 1)[0]

        upload_response = self.client.post(
            f"{library_path}/upload",
            data={"tracks": (io.BytesIO(b"ID3-demo-track"), "demo.mp3")},
            content_type="multipart/form-data",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )
        self.assertEqual(upload_response.status_code, 200)
        payload = upload_response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["uploaded"], 1)

        page = self.client.get(library_path)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"demo.mp3", page.data)

    def test_dev_reload_endpoint_enabled_in_dev_mode(self) -> None:
        app = create_app(
            {
                "TESTING": True,
                "DEV_MODE": True,
                "DATA_DIR": Path(self.temp_dir.name),
            }
        )
        client = app.test_client()
        response = client.get("/__dev/reload-token")
        self.assertEqual(response.status_code, 200)
        self.assertIn("token", response.get_json())


if __name__ == "__main__":
    unittest.main()
