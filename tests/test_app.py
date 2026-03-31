from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from songshare.album_lookup import LookupCandidate
from songshare import create_app


class FakeLookupClient:
    def search_release_candidates(self, *, title: str, artist: str, album: str, limit: int = 5):
        return [
            LookupCandidate(
                release_id="release-123",
                release_group_id="group-123",
                title=album or "Album Match",
                artist=artist or "Artist Match",
                date="2020-01-01",
                country="AU",
                track_title=title or "Track Match",
                cover_art_url="https://example.test/front.jpg",
            )
        ]

    def fetch_cover_art(self, *, release_id: str, release_group_id: str):
        return b"fake-cover", ".jpg"


class SongshareAppTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "DATA_DIR": Path(self.temp_dir.name),
                "BASE_URL": "http://localhost:8080",
                "LOOKUP_CLIENT": FakeLookupClient(),
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
                "LOOKUP_CLIENT": FakeLookupClient(),
            }
        )
        client = app.test_client()
        response = client.get("/__dev/reload-token")
        self.assertEqual(response.status_code, 200)
        self.assertIn("token", response.get_json())

    def test_lookup_and_apply_album_info(self) -> None:
        response = self.client.post("/libraries", follow_redirects=False)
        library_path = response.headers["Location"].split("?", 1)[0]

        upload_response = self.client.post(
            f"{library_path}/upload",
            data={"tracks": (io.BytesIO(b"ID3-demo-track"), "demo.mp3")},
            content_type="multipart/form-data",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )
        self.assertEqual(upload_response.status_code, 200)

        library_id = library_path.rsplit("/", 1)[-1]
        library = self.app.config["STORE"].get_library(library_id)
        track_id = library.tracks[0].id

        lookup_response = self.client.get(
            f"/s/{library_id}/tracks/{track_id}/lookup",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )
        self.assertEqual(lookup_response.status_code, 200)
        self.assertTrue(lookup_response.get_json()["ok"])

        apply_response = self.client.post(
            f"/s/{library_id}/tracks/{track_id}/lookup/apply",
            json={
                "release_id": "release-123",
                "release_group_id": "group-123",
                "title": "Demo Track",
                "artist": "Demo Artist",
                "album": "Demo Album",
            },
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )
        self.assertEqual(apply_response.status_code, 200)
        payload = apply_response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["track"]["album"], "Demo Album")
        self.assertTrue(payload["track"]["cover_url"])

        updated_library = self.app.config["STORE"].get_library(library_id)
        self.assertEqual(updated_library.tracks[0].musicbrainz_release_id, "release-123")
        self.assertEqual(updated_library.tracks[0].album, "Demo Album")
        self.assertTrue(updated_library.tracks[0].cover_art_name)

    def test_lookup_accepts_manual_query_overrides(self) -> None:
        response = self.client.post("/libraries", follow_redirects=False)
        library_path = response.headers["Location"].split("?", 1)[0]

        self.client.post(
            f"{library_path}/upload",
            data={"tracks": (io.BytesIO(b"ID3-demo-track"), "demo.mp3")},
            content_type="multipart/form-data",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )

        library_id = library_path.rsplit("/", 1)[-1]
        library = self.app.config["STORE"].get_library(library_id)
        track_id = library.tracks[0].id

        lookup_response = self.client.get(
            f"/s/{library_id}/tracks/{track_id}/lookup?title=Manual%20Title&artist=Manual%20Artist&album=Manual%20Album",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )
        self.assertEqual(lookup_response.status_code, 200)
        payload = lookup_response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["query"]["title"], "Manual Title")
        self.assertEqual(payload["query"]["artist"], "Manual Artist")
        self.assertEqual(payload["query"]["album"], "Manual Album")

    def test_bulk_delete_tracks(self) -> None:
        response = self.client.post("/libraries", follow_redirects=False)
        library_path = response.headers["Location"].split("?", 1)[0]

        self.client.post(
            f"{library_path}/upload",
            data={
                "tracks": [
                    (io.BytesIO(b"ID3-demo-track-1"), "demo-one.mp3"),
                    (io.BytesIO(b"ID3-demo-track-2"), "demo-two.mp3"),
                ]
            },
            content_type="multipart/form-data",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )

        library_id = library_path.rsplit("/", 1)[-1]
        library = self.app.config["STORE"].get_library(library_id)
        track_ids = [track.id for track in library.tracks]

        delete_response = self.client.post(
            f"/s/{library_id}/tracks/delete",
            json={"track_ids": track_ids},
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )
        self.assertEqual(delete_response.status_code, 200)
        payload = delete_response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["deleted"], 2)

        updated_library = self.app.config["STORE"].get_library(library_id)
        self.assertEqual(updated_library.tracks, [])

    def test_album_view_renders(self) -> None:
        response = self.client.post("/libraries", follow_redirects=False)
        library_path = response.headers["Location"].split("?", 1)[0]

        self.client.post(
            f"{library_path}/upload",
            data={"tracks": (io.BytesIO(b"ID3-demo-track"), "demo.mp3")},
            content_type="multipart/form-data",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )

        page = self.client.get(f"{library_path}?view=albums")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Albums", page.data)
        self.assertIn(b"album-browser", page.data)

    def test_inline_rating_endpoint_updates_track(self) -> None:
        response = self.client.post("/libraries", follow_redirects=False)
        library_path = response.headers["Location"].split("?", 1)[0]

        self.client.post(
            f"{library_path}/upload",
            data={"tracks": (io.BytesIO(b"FAKE-demo-track"), "demo.mp3")},
            content_type="multipart/form-data",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )

        library_id = library_path.rsplit("/", 1)[-1]
        library = self.app.config["STORE"].get_library(library_id)
        track_id = library.tracks[0].id

        response = self.client.post(
            f"/s/{library_id}/tracks/{track_id}/rating",
            json={"rating": 5},
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["track"]["rating"], 5)

        updated_library = self.app.config["STORE"].get_library(library_id)
        self.assertEqual(updated_library.tracks[0].rating, 5)


if __name__ == "__main__":
    unittest.main()
