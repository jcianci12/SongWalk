from __future__ import annotations

import io
import unittest
import uuid
from pathlib import Path

from songshare.album_lookup import LookupCandidate
from songshare import create_app


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


def new_test_dir() -> Path:
    path = TEST_TMP_ROOT / str(uuid.uuid4())
    path.mkdir(parents=True, exist_ok=False)
    return path


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
        self.owner_token = self.app.config["OWNER_TOKEN"]

    def create_library(self):
        return self.client.post(f"/libraries?owner_token={self.owner_token}", follow_redirects=False)

    def tearDown(self) -> None:
        pass

    def test_create_library_and_upload_track(self) -> None:
        response = self.create_library()
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

    def test_home_does_not_enumerate_library_ids(self) -> None:
        response = self.create_library()
        library_path = response.headers["Location"].split("?", 1)[0]
        library_id = library_path.rsplit("/", 1)[-1]

        page = self.client.get("/", base_url="http://music.example.com")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(library_id.encode(), page.data)
        self.assertIn(b"Open a shared library", page.data)
        self.assertIn(b"/s/12345678-1234-1234-1234-123456789abc", page.data)

    def test_local_root_redirects_to_owner_dashboard(self) -> None:
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], f"/owner/{self.owner_token}")

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
        response = self.create_library()
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
        response = self.create_library()
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
        response = self.create_library()
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

    def test_delete_library(self) -> None:
        response = self.create_library()
        library_path = response.headers["Location"].split("?", 1)[0]
        library_id = library_path.rsplit("/", 1)[-1]

        delete_response = self.client.post(
            f"/libraries/{library_id}/delete?owner_token={self.owner_token}",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )
        self.assertEqual(delete_response.status_code, 200)
        payload = delete_response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["redirect_url"], f"/owner/{self.owner_token}")

        with self.assertRaises(FileNotFoundError):
            self.app.config["STORE"].get_library(library_id)

    def test_album_view_renders(self) -> None:
        response = self.create_library()
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
        self.assertIn(b"data-album-browse-url", page.data)
        self.assertIn(b"data-search=", page.data)

    def test_library_page_renders_drawer_import_controls(self) -> None:
        response = self.create_library()
        library_path = response.headers["Location"].split("?", 1)[0]

        page = self.client.get(library_path)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"drawer-import-button", page.data)
        self.assertIn(b"data-hidden-file-input", page.data)
        self.assertIn(b"data-hidden-directory-input", page.data)
        self.assertIn(b"toggle-library-drawer", page.data)

    def test_track_view_marks_target_album_section(self) -> None:
        response = self.create_library()
        library_path = response.headers["Location"].split("?", 1)[0]

        self.client.post(
            f"{library_path}/upload",
            data={"tracks": (io.BytesIO(b"ID3-demo-track"), "demo.mp3")},
            content_type="multipart/form-data",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )

        target_key = "unknown album::unknown artist"
        page = self.client.get(f"{library_path}?view=tracks&album={target_key}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"data-target-album-section", page.data)
        self.assertIn(b"is-target-album", page.data)

    def test_library_view_renders_drawer_import_controls(self) -> None:
        response = self.create_library()
        library_path = response.headers["Location"].split("?", 1)[0]

        page = self.client.get(library_path)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"drawer-handle-button", page.data)
        self.assertIn(b"drawer-import-actions", page.data)
        self.assertIn(b"Search tracks and albums", page.data)
        self.assertIn(b"data-upload-status-shell", page.data)

    def test_library_view_does_not_expose_other_library_ids(self) -> None:
        first_response = self.create_library()
        first_library_path = first_response.headers["Location"].split("?", 1)[0]
        first_library_id = first_library_path.rsplit("/", 1)[-1]

        second_response = self.create_library()
        second_library_path = second_response.headers["Location"].split("?", 1)[0]
        second_library_id = second_library_path.rsplit("/", 1)[-1]

        page = self.client.get(first_library_path)
        self.assertEqual(page.status_code, 200)
        self.assertIn(first_library_id[:8].encode(), page.data)
        self.assertNotIn(second_library_id.encode(), page.data)
        self.assertNotIn(second_library_id[:8].encode(), page.data)
        self.assertNotIn(b"Other libraries", page.data)

    def test_inline_rating_endpoint_updates_track(self) -> None:
        response = self.create_library()
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

    def test_owner_dashboard_uses_forwarded_https_headers_for_share_links(self) -> None:
        app = create_app(
            {
                "TESTING": True,
                "DATA_DIR": self.temp_dir,
                "PROXY_HOPS": 1,
                "LOOKUP_CLIENT": FakeLookupClient(),
            }
        )
        client = app.test_client()
        owner_token = app.config["OWNER_TOKEN"]

        client.post(
            f"/libraries?owner_token={owner_token}",
            follow_redirects=False,
            base_url="http://127.0.0.1:8080",
            headers={
                "Host": "127.0.0.1:8080",
                "X-Forwarded-Host": "music.example.com",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Port": "443",
            },
        )

        page = client.get(
            f"/owner/{owner_token}",
            base_url="http://127.0.0.1:8080",
            headers={
                "Host": "127.0.0.1:8080",
                "X-Forwarded-Host": "music.example.com",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Port": "443",
            },
        )
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"https://music.example.com/s/", page.data)

    def test_owner_dashboard_requires_secret_token(self) -> None:
        response = self.client.get("/owner/not-the-right-token")
        self.assertEqual(response.status_code, 404)

    def test_create_library_requires_owner_token(self) -> None:
        response = self.client.post("/libraries", follow_redirects=False)
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
