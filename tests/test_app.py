from __future__ import annotations

import io
import time
import unittest
import uuid
import zipfile
from pathlib import Path

from songshare.album_lookup import LookupCandidate
from songshare import create_app
from songshare.importer import ImportOutcome
from songshare.quick_tunnel import QuickTunnelStatus


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


class FakeImportService:
    def __init__(self, store):
        self.store = store
        self.calls: list[tuple[str, str]] = []

    def import_uploaded_files(self, library_id: str, uploads):
        raise AssertionError("File uploads should use the real import service in this test.")

    def import_youtube_url(self, library_id: str, source_url: str, *, progress_callback=None):
        self.calls.append(("youtube", source_url))
        if progress_callback:
            progress_callback(type("Progress", (), {"phase": "downloading", "message": "Downloading YouTube audio...", "percent": 42, "current_item": "Demo video"})())
        track = self.store.add_track(
            library_id,
            uploaded_track=_uploaded_track("youtube-import.mp3"),
        )
        return ImportOutcome(uploaded=1, tracks=[track])

    def import_spotify_url(self, library_id: str, source_url: str, *, progress_callback=None):
        self.calls.append(("spotify", source_url))
        if progress_callback:
            progress_callback(type("Progress", (), {"phase": "downloading", "message": "Resolving Spotify track...", "percent": None, "current_item": "Demo track"})())
        track = self.store.add_track(
            library_id,
            uploaded_track=_uploaded_track("spotify-import.mp3"),
        )
        return ImportOutcome(uploaded=1, tracks=[track])

    def search_youtube(self, query: str, *, limit: int = 6):
        self.calls.append(("youtube-search", query))
        return [
            {
                "title": "Demo result",
                "channel": "Demo channel",
                "duration": "3:21",
                "thumbnail": "https://example.test/thumb.jpg",
                "url": "https://www.youtube.com/watch?v=demo123",
            }
        ]

    def search_spotify(self, query: str, *, limit: int = 6):
        self.calls.append(("spotify-search", query))
        return [
            {
                "kind": "track",
                "title": "Demo Spotify Result",
                "subtitle": "Demo Artist · Demo Album",
                "thumbnail": "https://example.test/spotify.jpg",
                "url": "https://open.spotify.com/track/demo123",
            }
        ]


class FakeQuickTunnelManager:
    def __init__(self, public_url: str = "https://demo.trycloudflare.com"):
        self._status = QuickTunnelStatus(
            enabled=True,
            available=True,
            running=True,
            public_url=public_url,
            service_url="http://127.0.0.1:8080",
            message="Cloudflare Quick Tunnel ready.",
        )
        self.start_calls = 0
        self.stop_calls = 0
        self.rotate_calls = 0

    def status(self):
        return QuickTunnelStatus(**self._status.to_dict())

    def start(self, *, wait_seconds: float = 20.0):
        self.start_calls += 1
        self._status.running = True
        self._status.public_url = f"https://started-{self.start_calls}.trycloudflare.com"
        self._status.message = "Cloudflare Quick Tunnel ready."
        return self.status()

    def stop(self, *, clear_message: bool = True):
        self.stop_calls += 1
        self._status.running = False
        self._status.public_url = ""
        self._status.message = "Quick Tunnel stopped."
        return self.status()

    def rotate(self, *, wait_seconds: float = 20.0):
        self.rotate_calls += 1
        self._status.public_url = f"https://rotated-{self.rotate_calls}.trycloudflare.com"
        self._status.message = "Cloudflare Quick Tunnel ready."
        return self.status()


def _uploaded_track(filename: str):
    from songshare.store import UploadedTrack

    return UploadedTrack(
        filename=filename,
        content_type="audio/mpeg",
        stream=io.BytesIO(b"FAKE-import-track"),
    )


def wait_for_import_job(client, status_url: str) -> dict:
    deadline = time.time() + 2
    last_payload = {}
    while time.time() < deadline:
        response = client.get(
            status_url,
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )
        last_payload = response.get_json()
        if last_payload["job"]["complete"]:
            return last_payload
        time.sleep(0.05)
    return last_payload


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

    def test_local_root_renders_owner_launch_panel(self) -> None:
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Share SongWalk from this machine", response.data)
        self.assertIn(f'href="/owner/{self.owner_token}"'.encode(), response.data)
        self.assertIn(self.app.config["OWNER_PATH"].encode(), response.data)

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

    def test_rename_library_updates_display_name_but_keeps_uuid(self) -> None:
        response = self.create_library()
        library_path = response.headers["Location"].split("?", 1)[0]
        library_id = library_path.rsplit("/", 1)[-1]

        rename_response = self.client.post(
            f"/libraries/{library_id}/rename?owner_token={self.owner_token}",
            data={"name": "Road Trip"},
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )
        self.assertEqual(rename_response.status_code, 200)
        payload = rename_response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["library"]["name"], "Road Trip")
        self.assertEqual(payload["library"]["display_name"], "Road Trip")

        renamed_library = self.app.config["STORE"].get_library(library_id)
        self.assertEqual(renamed_library.name, "Road Trip")
        self.assertEqual(renamed_library.display_name, "Road Trip")

        owner_page = self.client.get(f"/owner/{self.owner_token}")
        self.assertEqual(owner_page.status_code, 200)
        self.assertIn(b"Road Trip", owner_page.data)
        self.assertIn(library_id.encode(), owner_page.data)

        library_page = self.client.get(library_path)
        self.assertEqual(library_page.status_code, 200)
        self.assertIn(b"Road Trip", library_page.data)
        self.assertIn(library_id.encode(), library_page.data)

        import_page = self.client.get(f"{library_path}/import")
        self.assertEqual(import_page.status_code, 200)
        self.assertIn(b"Road Trip", import_page.data)
        self.assertIn(library_id.encode(), import_page.data)

    def test_create_library_accepts_optional_name(self) -> None:
        response = self.client.post(
            f"/libraries?owner_token={self.owner_token}",
            data={"name": "Gym Mix"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        library_id = response.headers["Location"].split("?", 1)[0].rsplit("/", 1)[-1]

        library = self.app.config["STORE"].get_library(library_id)
        self.assertEqual(library.name, "Gym Mix")
        self.assertEqual(library.display_name, "Gym Mix")

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

    def test_album_view_requires_manual_collection_creation(self) -> None:
        response = self.create_library()
        library_path = response.headers["Location"].split("?", 1)[0]

        self.client.post(
            f"{library_path}/upload",
            data={
                "tracks": [
                    (io.BytesIO(b"ID3-track-1"), "one.mp3"),
                    (io.BytesIO(b"ID3-track-2"), "two.mp3"),
                ]
            },
            content_type="multipart/form-data",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )

        library_id = library_path.rsplit("/", 1)[-1]
        library = self.app.config["STORE"].get_library(library_id)
        album_names = ["First EP", "Second EP"]
        for track, album_name in zip(library.tracks, album_names):
            self.app.config["STORE"].update_track(
                library_id,
                track.id,
                title=f"{album_name} Song",
                artist="Demo Artist",
                album=album_name,
            )

        page = self.client.get(f"{library_path}?view=albums")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.data.count(b"data-collection-card"), 0)
        self.assertIn(b"First EP", page.data)
        self.assertIn(b"Second EP", page.data)
        self.assertIn(b"Create collection", page.data)
        self.assertIn(b"Add selected", page.data)
        self.assertIn(b"Ungroup selected", page.data)

    def test_album_view_renders_manual_collection_after_create(self) -> None:
        response = self.create_library()
        library_path = response.headers["Location"].split("?", 1)[0]

        self.client.post(
            f"{library_path}/upload",
            data={
                "tracks": [
                    (io.BytesIO(b"ID3-track-1"), "one.mp3"),
                    (io.BytesIO(b"ID3-track-2"), "two.mp3"),
                ]
            },
            content_type="multipart/form-data",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )

        library_id = library_path.rsplit("/", 1)[-1]
        library = self.app.config["STORE"].get_library(library_id)
        album_names = ["First EP", "Second EP"]
        for track, album_name in zip(library.tracks, album_names):
            self.app.config["STORE"].update_track(
                library_id,
                track.id,
                title=f"{album_name} Song",
                artist="Demo Artist",
                album=album_name,
            )

        selected_track_ids = ",".join(track.id for track in library.tracks)
        create_response = self.client.post(
            f"/s/{library_id}/collections",
            data={"name": "Demo Singles", "track_ids": selected_track_ids},
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        page = self.client.get(f"{library_path}?view=albums")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.data.count(b"data-collection-card"), 1)
        self.assertIn(b"Demo Singles", page.data)
        self.assertIn(b"First EP", page.data)
        self.assertIn(b"Second EP", page.data)
        self.assertIn(
            f'/s/{library_id}?view=tracks&amp;album=first+ep::demo+artist'.encode(),
            page.data,
        )

    def test_library_page_renders_drawer_import_controls(self) -> None:
        response = self.create_library()
        library_path = response.headers["Location"].split("?", 1)[0]

        page = self.client.get(library_path)
        self.assertEqual(page.status_code, 200)
        self.assertIn(f'href="{library_path}/import"'.encode(), page.data)
        self.assertIn(f'href="{library_path}/download"'.encode(), page.data)
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

    def test_track_view_renders_manual_collection_controls(self) -> None:
        response = self.create_library()
        library_path = response.headers["Location"].split("?", 1)[0]

        self.client.post(
            f"{library_path}/upload",
            data={
                "tracks": [
                    (io.BytesIO(b"ID3-track-1"), "one.mp3"),
                    (io.BytesIO(b"ID3-track-2"), "two.mp3"),
                ]
            },
            content_type="multipart/form-data",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )

        library_id = library_path.rsplit("/", 1)[-1]
        library = self.app.config["STORE"].get_library(library_id)
        album_names = ["First EP", "Second EP"]
        for track, album_name in zip(library.tracks, album_names):
            self.app.config["STORE"].update_track(
                library_id,
                track.id,
                title=f"{album_name} Song",
                artist="Demo Artist",
                album=album_name,
            )

        self.client.post(
            f"/s/{library_id}/collections",
            data={"name": "Demo Singles", "track_ids": ",".join(track.id for track in library.tracks)},
            follow_redirects=False,
        )

        page = self.client.get(f"{library_path}?view=tracks")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Group from track selection", page.data)
        self.assertEqual(page.data.count(b"Group from track selection"), 1)
        self.assertIn(b'data-collection-selection-scope="tracks"', page.data)
        self.assertIn(b"Track selection is collapsed to full albums before grouping", page.data)
        self.assertIn(b"Demo Singles", page.data)
        self.assertIn(b"data-collection-summary-list", page.data)
        self.assertIn(b"collection-track-label", page.data)
        self.assertIn(b"data-track-album-key", page.data)
        self.assertIn(b"data-track-album-track-ids", page.data)
        self.assertIn(b"context-menu-collection-studio", page.data)
        self.assertIn(b'id="track-context-menu"', page.data)
        self.assertIn(b'id="context-delete-track"', page.data)

    def test_track_view_renders_drag_drop_and_library_move_controls(self) -> None:
        first_response = self.client.post(
            f"/libraries?owner_token={self.owner_token}",
            data={"name": "Source Library"},
            follow_redirects=False,
        )
        first_library_path = first_response.headers["Location"].split("?", 1)[0]
        second_response = self.client.post(
            f"/libraries?owner_token={self.owner_token}",
            data={"name": "Archive Library"},
            follow_redirects=False,
        )
        second_library_id = second_response.headers["Location"].split("?", 1)[0].rsplit("/", 1)[-1]

        self.client.post(
            f"{first_library_path}/upload",
            data={
                "tracks": [
                    (io.BytesIO(b"ID3-track-1"), "one.mp3"),
                    (io.BytesIO(b"ID3-track-2"), "two.mp3"),
                ]
            },
            content_type="multipart/form-data",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )

        first_library_id = first_library_path.rsplit("/", 1)[-1]
        library = self.app.config["STORE"].get_library(first_library_id)
        self.app.config["STORE"].update_track(
            first_library_id,
            library.tracks[0].id,
            title="First Song",
            artist="Demo Artist",
            album="First EP",
        )
        self.app.config["STORE"].update_track(
            first_library_id,
            library.tracks[1].id,
            title="Second Song",
            artist="Demo Artist",
            album="Second EP",
        )

        page = self.client.get(first_library_path)
        self.assertEqual(page.status_code, 200)
        self.assertIn(f'data-track-move-url="/s/{first_library_id}/tracks/move"'.encode(), page.data)
        self.assertIn(b'draggable="true"', page.data)
        self.assertIn(b"data-drop-album-target", page.data)
        self.assertIn(b'id="context-move-library"', page.data)
        self.assertIn(b'id="context-move-track"', page.data)
        self.assertIn(second_library_id.encode(), page.data)
        self.assertIn(b"Archive Library", page.data)

    def test_move_tracks_endpoint_moves_selection_into_target_album(self) -> None:
        response = self.create_library()
        library_path = response.headers["Location"].split("?", 1)[0]

        self.client.post(
            f"{library_path}/upload",
            data={
                "tracks": [
                    (io.BytesIO(b"ID3-track-1"), "one.mp3"),
                    (io.BytesIO(b"ID3-track-2"), "two.mp3"),
                ]
            },
            content_type="multipart/form-data",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )

        library_id = library_path.rsplit("/", 1)[-1]
        library = self.app.config["STORE"].get_library(library_id)
        source_track = library.tracks[0]
        target_track = library.tracks[1]
        self.app.config["STORE"].update_track(
            library_id,
            source_track.id,
            title="Source Song",
            artist="Demo Artist",
            album="Source EP",
        )
        self.app.config["STORE"].update_track(
            library_id,
            target_track.id,
            title="Target Song",
            artist="Demo Artist",
            album="Target EP",
        )

        response = self.client.post(
            f"/s/{library_id}/tracks/move",
            json={
                "track_ids": [source_track.id],
                "album": "Target EP",
                "artist": "Demo Artist",
            },
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["moved"], 1)
        self.assertEqual(payload["target_album_key"], "target ep::demo artist")

        updated_source = self.app.config["STORE"].get_track(library_id, source_track.id)
        self.assertEqual(updated_source.album, "Target EP")
        self.assertEqual(updated_source.artist, "Demo Artist")

    def test_move_track_to_other_library_endpoint_moves_file_and_metadata(self) -> None:
        source_response = self.client.post(
            f"/libraries?owner_token={self.owner_token}",
            data={"name": "Source Library"},
            follow_redirects=False,
        )
        source_library_path = source_response.headers["Location"].split("?", 1)[0]
        source_library_id = source_library_path.rsplit("/", 1)[-1]

        target_response = self.client.post(
            f"/libraries?owner_token={self.owner_token}",
            data={"name": "Archive Library"},
            follow_redirects=False,
        )
        target_library_id = target_response.headers["Location"].split("?", 1)[0].rsplit("/", 1)[-1]

        self.client.post(
            f"{source_library_path}/upload",
            data={"tracks": (io.BytesIO(b"FAKE-demo-track"), "demo.mp3")},
            content_type="multipart/form-data",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )

        source_library = self.app.config["STORE"].get_library(source_library_id)
        track = source_library.tracks[0]
        self.app.config["STORE"].update_track(
            source_library_id,
            track.id,
            title="Moved Song",
            artist="Demo Artist",
            album="Demo Album",
        )

        response = self.client.post(
            f"/s/{source_library_id}/tracks/{track.id}/move-library",
            json={"target_library_id": target_library_id},
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["target_library"]["id"], target_library_id)
        self.assertIn(f"/s/{target_library_id}".encode(), payload["redirect_url"].encode())

        updated_source_library = self.app.config["STORE"].get_library(source_library_id)
        self.assertEqual(updated_source_library.tracks, [])

        updated_target_library = self.app.config["STORE"].get_library(target_library_id)
        self.assertEqual(len(updated_target_library.tracks), 1)
        moved_track = updated_target_library.tracks[0]
        self.assertEqual(moved_track.title, "Moved Song")
        self.assertEqual(moved_track.artist, "Demo Artist")
        self.assertEqual(moved_track.album, "Demo Album")
        streamed_track, file_path = self.app.config["STORE"].get_track_file(target_library_id, moved_track.id)
        self.assertEqual(streamed_track.id, moved_track.id)
        self.assertTrue(file_path.exists())

    def test_library_view_renders_drawer_import_controls(self) -> None:
        response = self.create_library()
        library_path = response.headers["Location"].split("?", 1)[0]

        page = self.client.get(library_path)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"drawer-handle-button", page.data)
        self.assertIn(f'href="{library_path}/download"'.encode(), page.data)
        self.assertEqual(page.data.count(b">Import<"), 1)
        self.assertEqual(page.data.count(b">Download<"), 1)
        self.assertIn(b"Search tracks and albums", page.data)
        self.assertIn(b"data-upload-status-shell", page.data)
        self.assertIn(b"data-download-status-shell", page.data)
        self.assertIn(b"data-library-download", page.data)

    def test_owner_dashboard_renders_rename_controls(self) -> None:
        response = self.create_library()
        library_path = response.headers["Location"].split("?", 1)[0]
        library_id = library_path.rsplit("/", 1)[-1]

        page = self.client.get(f"/owner/{self.owner_token}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(f'action="/libraries/{library_id}/rename?owner_token={self.owner_token}"'.encode(), page.data)
        self.assertIn(b"Rename library", page.data)

    def test_download_library_returns_zip_archive(self) -> None:
        response = self.create_library()
        library_path = response.headers["Location"].split("?", 1)[0]

        self.client.post(
            f"{library_path}/upload",
            data={
                "tracks": [
                    (io.BytesIO(b"ID3-first-track"), "first.mp3"),
                    (io.BytesIO(b"ID3-second-track"), "second.mp3"),
                ]
            },
            content_type="multipart/form-data",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )

        library_id = library_path.rsplit("/", 1)[-1]
        library = self.app.config["STORE"].get_library(library_id)
        self.app.config["STORE"].update_track(
            library_id,
            library.tracks[0].id,
            title="Same Song",
            artist="Demo Artist",
            album="Demo Album",
        )
        self.app.config["STORE"].update_track(
            library_id,
            library.tracks[1].id,
            title="Same Song",
            artist="Demo Artist",
            album="Demo Album",
        )

        download_response = self.client.get(f"{library_path}/download")
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(download_response.mimetype, "application/zip")
        self.assertIn(f"songwalk-library-{library_id}.zip", download_response.headers["Content-Disposition"])
        self.assertGreater(int(download_response.headers["Content-Length"]), 0)

        archive = zipfile.ZipFile(io.BytesIO(download_response.data))
        self.assertEqual(
            sorted(archive.namelist()),
            [
                "Demo_Artist/Demo_Album/Same_Song (2).mp3",
                "Demo_Artist/Demo_Album/Same_Song.mp3",
            ],
        )
        expected_bytes = sorted(
            (
                self.app.config["STORE"].library_files_dir(library_id) / track.stored_name
            ).read_bytes()
            for track in self.app.config["STORE"].get_library(library_id).tracks
        )
        self.assertEqual(
            sorted(archive.read(name) for name in archive.namelist()),
            expected_bytes,
        )
        archive.close()
        download_response.close()

    def test_import_page_renders_all_sources(self) -> None:
        response = self.create_library()
        library_path = response.headers["Location"].split("?", 1)[0]

        page = self.client.get(f"{library_path}/import")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"data-dynamic-favicon", page.data)
        self.assertIn(b"Import from YouTube", page.data)
        self.assertIn(b"Import from Spotify", page.data)
        self.assertIn(b"data-upload-form", page.data)
        self.assertIn(b"data-ingest-form", page.data)
        self.assertIn(b"data-youtube-search-form", page.data)
        self.assertIn(b"data-spotify-search-form", page.data)
        self.assertIn(b"data-spotify-search-results", page.data)
        self.assertIn(b"data-remote-import-shell", page.data)

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

    def test_update_track_endpoint_updates_metadata(self) -> None:
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
            f"/s/{library_id}/tracks/{track_id}",
            data={
                "title": "Inline Title",
                "artist": "Inline Artist",
                "album": "Inline Album",
                "rating": "4",
            },
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])

        updated_library = self.app.config["STORE"].get_library(library_id)
        self.assertEqual(updated_library.tracks[0].title, "Inline Title")
        self.assertEqual(updated_library.tracks[0].artist, "Inline Artist")
        self.assertEqual(updated_library.tracks[0].album, "Inline Album")
        self.assertEqual(updated_library.tracks[0].rating, 4)

    def test_track_view_renders_inline_edit_fields(self) -> None:
        response = self.create_library()
        library_path = response.headers["Location"].split("?", 1)[0]

        self.client.post(
            f"{library_path}/upload",
            data={"tracks": (io.BytesIO(b"FAKE-demo-track"), "demo.mp3")},
            content_type="multipart/form-data",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )

        page = self.client.get(library_path)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'data-inline-edit-field="title"', page.data)
        self.assertIn(b'data-inline-edit-field="artist"', page.data)
        self.assertIn(b'data-inline-edit-field="album"', page.data)

    def test_youtube_import_endpoint_uses_import_service(self) -> None:
        temp_dir = new_test_dir()
        app = create_app(
            {
                "TESTING": True,
                "DATA_DIR": temp_dir,
                "BASE_URL": "http://localhost:8080",
                "LOOKUP_CLIENT": FakeLookupClient(),
            }
        )
        app.config["IMPORT_SERVICE"] = FakeImportService(app.config["STORE"])
        client = app.test_client()
        owner_token = app.config["OWNER_TOKEN"]

        create_response = client.post(f"/libraries?owner_token={owner_token}", follow_redirects=False)
        library_path = create_response.headers["Location"].split("?", 1)[0]
        library_id = library_path.rsplit("/", 1)[-1]

        response = client.post(
            f"/s/{library_id}/import/youtube",
            data={"source_url": "https://www.youtube.com/watch?v=demo"},
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertIn("job_id", payload)
        self.assertIn("/import/jobs/", payload["status_url"])

        status_response = client.get(
            payload["status_url"],
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )
        self.assertEqual(status_response.status_code, 200)
        status_payload = wait_for_import_job(client, payload["status_url"])
        self.assertEqual(status_payload["job"]["source"], "youtube")
        self.assertTrue(status_payload["job"]["ok"])
        self.assertEqual(len(app.config["STORE"].get_library(library_id).tracks), 1)
        self.assertEqual(
            app.config["IMPORT_SERVICE"].calls,
            [("youtube", "https://www.youtube.com/watch?v=demo")],
        )

    def test_spotify_import_endpoint_uses_import_service(self) -> None:
        temp_dir = new_test_dir()
        app = create_app(
            {
                "TESTING": True,
                "DATA_DIR": temp_dir,
                "BASE_URL": "http://localhost:8080",
                "LOOKUP_CLIENT": FakeLookupClient(),
            }
        )
        app.config["IMPORT_SERVICE"] = FakeImportService(app.config["STORE"])
        client = app.test_client()
        owner_token = app.config["OWNER_TOKEN"]

        create_response = client.post(f"/libraries?owner_token={owner_token}", follow_redirects=False)
        library_path = create_response.headers["Location"].split("?", 1)[0]
        library_id = library_path.rsplit("/", 1)[-1]

        response = client.post(
            f"/s/{library_id}/import/spotify",
            data={"source_url": "https://open.spotify.com/track/demo"},
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertIn("job_id", payload)
        self.assertIn("/import/jobs/", payload["status_url"])
        status_payload = wait_for_import_job(client, payload["status_url"])
        self.assertTrue(status_payload["job"]["ok"])
        self.assertEqual(
            app.config["IMPORT_SERVICE"].calls,
            [("spotify", "https://open.spotify.com/track/demo")],
        )
        self.assertEqual(len(app.config["STORE"].get_library(library_id).tracks), 1)

    def test_youtube_search_endpoint_returns_results(self) -> None:
        temp_dir = new_test_dir()
        app = create_app(
            {
                "TESTING": True,
                "DATA_DIR": temp_dir,
                "BASE_URL": "http://localhost:8080",
                "LOOKUP_CLIENT": FakeLookupClient(),
            }
        )
        app.config["IMPORT_SERVICE"] = FakeImportService(app.config["STORE"])
        client = app.test_client()
        owner_token = app.config["OWNER_TOKEN"]

        create_response = client.post(f"/libraries?owner_token={owner_token}", follow_redirects=False)
        library_path = create_response.headers["Location"].split("?", 1)[0]
        library_id = library_path.rsplit("/", 1)[-1]

        response = client.get(
            f"/s/{library_id}/import/youtube/search?q=demo%20song",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["results"][0]["url"], "https://www.youtube.com/watch?v=demo123")

    def test_spotify_search_endpoint_returns_results(self) -> None:
        temp_dir = new_test_dir()
        app = create_app(
            {
                "TESTING": True,
                "DATA_DIR": temp_dir,
                "BASE_URL": "http://localhost:8080",
                "LOOKUP_CLIENT": FakeLookupClient(),
            }
        )
        app.config["IMPORT_SERVICE"] = FakeImportService(app.config["STORE"])
        client = app.test_client()
        owner_token = app.config["OWNER_TOKEN"]

        create_response = client.post(f"/libraries?owner_token={owner_token}", follow_redirects=False)
        library_path = create_response.headers["Location"].split("?", 1)[0]
        library_id = library_path.rsplit("/", 1)[-1]

        response = client.get(
            f"/s/{library_id}/import/spotify/search?q=demo%20song",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["results"][0]["url"], "https://open.spotify.com/track/demo123")

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

    def test_quick_tunnel_status_requires_direct_local_access(self) -> None:
        response = self.client.get("/quick-tunnel", base_url="http://music.example.com")
        self.assertEqual(response.status_code, 404)

    def test_quick_tunnel_status_uses_manager_payload(self) -> None:
        manager = FakeQuickTunnelManager()
        self.app.extensions["quick_tunnel_manager"] = manager

        response = self.client.get("/quick-tunnel")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["tunnel"]["public_url"], "https://demo.trycloudflare.com")
        self.assertEqual(
            payload["tunnel"]["public_owner_url"],
            f"https://demo.trycloudflare.com{self.app.config['OWNER_PATH']}",
        )

    def test_quick_tunnel_rotate_uses_manager(self) -> None:
        manager = FakeQuickTunnelManager()
        self.app.extensions["quick_tunnel_manager"] = manager

        response = self.client.post("/quick-tunnel/rotate")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(manager.rotate_calls, 1)
        self.assertEqual(payload["tunnel"]["public_url"], "https://rotated-1.trycloudflare.com")

    def test_quick_tunnel_toggle_stops_running_tunnel(self) -> None:
        manager = FakeQuickTunnelManager()
        self.app.extensions["quick_tunnel_manager"] = manager

        response = self.client.post("/quick-tunnel/toggle")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["action"], "stopped")
        self.assertEqual(manager.stop_calls, 1)
        self.assertFalse(payload["tunnel"]["running"])
        self.assertEqual(payload["tunnel"]["public_url"], "")

    def test_quick_tunnel_toggle_starts_stopped_tunnel(self) -> None:
        manager = FakeQuickTunnelManager()
        manager.stop()
        self.app.extensions["quick_tunnel_manager"] = manager

        response = self.client.post("/quick-tunnel/toggle")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["action"], "started")
        self.assertEqual(manager.start_calls, 1)
        self.assertTrue(payload["tunnel"]["running"])
        self.assertEqual(payload["tunnel"]["public_url"], "https://started-1.trycloudflare.com")


if __name__ == "__main__":
    unittest.main()
