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
from songshare.wmp_library import WMP_LIBRARY_NAME, WMP_PLAYLIST_SOURCE_KIND, WMP_SOURCE_KIND, WmpStatus, WmpSyncResult


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


class FakeWmpService:
    def __init__(self, source_path: Path | None = None):
        self.source_path = source_path
        self.sync_calls = 0
        self.rating_calls: list[tuple[str, str, int]] = []
        self.metadata_calls: list[tuple[str, str, str, str, str]] = []
        self.progress_events: list[dict] = []

    def status(self):
        return WmpStatus(
            available=True,
            platform="win32",
            access_rights="full",
            item_count=1 if self.source_path else 0,
            message="Windows Media Player is available.",
        )

    def sync_to_store(
        self,
        store,
        *,
        library_id: str | None = None,
        limit: int | None = None,
        progress_callback=None,
    ):
        self.sync_calls += 1
        if progress_callback:
            progress_callback(
                type(
                    "Progress",
                    (),
                    {
                        "phase": "scanning",
                        "message": "Scanning Windows Media Player library...",
                        "percent": 0,
                        "current_item": "",
                    },
                )()
            )
        library = None
        if library_id:
            library = store.get_library(library_id)
        else:
            for candidate in store.list_libraries():
                if candidate.name == WMP_LIBRARY_NAME:
                    library = candidate
                    break
            if library is None:
                library = store.create_library(name=WMP_LIBRARY_NAME)

        tracks = []
        if self.source_path:
            if progress_callback:
                progress_callback(
                    type(
                        "Progress",
                        (),
                        {
                            "phase": "syncing_tracks",
                            "message": "Syncing track 1 of 1...",
                            "percent": 50,
                            "current_item": "WMP Demo",
                        },
                    )()
                )
            time.sleep(0.15)
            tracks.append(
                {
                    "source_path": str(self.source_path),
                    "source_external_id": "wmp-track-1",
                    "original_name": self.source_path.name,
                    "content_type": "audio/mpeg",
                    "size": self.source_path.stat().st_size,
                    "title": "WMP Demo",
                    "artist": "WMP Artist",
                    "album": "WMP Album",
                    "rating": 3,
                    "duration_seconds": 123.0,
                    "genre": "Demo",
                    "album_artist": "WMP Album Artist",
                    "play_count": 7,
                    "last_played_at": "2026-04-16",
                    "source_available": True,
                }
            )
        stats = store.sync_linked_tracks(library.id, source_kind=WMP_SOURCE_KIND, tracks=tracks)
        playlist_stats = {"total": 0}
        if tracks:
            playlist_stats = store.sync_linked_collections(
                library.id,
                source_kind=WMP_PLAYLIST_SOURCE_KIND,
                collections=[
                    {
                        "name": "WMP Favorites",
                        "source_external_id": "playlist-1",
                        "track_source_external_ids": ["wmp-track-1"],
                    }
                ],
            )
        if progress_callback:
            progress_callback(
                type(
                    "Progress",
                    (),
                    {
                        "phase": "complete",
                        "message": "Windows Media Player sync finished.",
                        "percent": 100,
                        "current_item": "",
                    },
                )()
            )
        return WmpSyncResult(
            ok=True,
            library_id=library.id,
            created=stats["created"],
            updated=stats["updated"],
            skipped=stats["skipped"],
            marked_unavailable=stats["marked_unavailable"],
            total=stats["total"],
            message=f"Synced {stats['total']} WMP track and {playlist_stats['total']} playlist.",
        )

    def set_rating(self, *, source_external_id: str, source_path: str, rating: int | str) -> None:
        self.rating_calls.append((source_external_id, source_path, int(rating)))

    def update_metadata(
        self,
        *,
        source_external_id: str,
        source_path: str,
        title: str,
        artist: str,
        album: str,
    ) -> None:
        self.metadata_calls.append((source_external_id, source_path, title, artist, album))


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


def wait_for_wmp_sync_job(client, status_url: str) -> dict:
    deadline = time.time() + 3
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

    def create_wmp_playlist_fixture(self):
        source_dir = self.temp_dir / "wmp-source"
        source_dir.mkdir()
        first_source = source_dir / "road-runner.mp3"
        second_source = source_dir / "rain-pulse.mp3"
        first_source.write_bytes(b"WMP-road-runner-bytes")
        second_source.write_bytes(b"WMP-rain-pulse-bytes")

        store = self.app.config["STORE"]
        library = store.create_library(name=WMP_LIBRARY_NAME)
        store.sync_linked_tracks(
            library.id,
            source_kind=WMP_SOURCE_KIND,
            tracks=[
                {
                    "source_path": str(first_source),
                    "source_external_id": "wmp-road",
                    "original_name": first_source.name,
                    "content_type": "audio/mpeg",
                    "size": first_source.stat().st_size,
                    "title": "Road Runner",
                    "artist": "Coyote Choir",
                    "album": "Desert Tapes",
                    "source_available": True,
                },
                {
                    "source_path": str(second_source),
                    "source_external_id": "wmp-rain",
                    "original_name": second_source.name,
                    "content_type": "audio/mpeg",
                    "size": second_source.stat().st_size,
                    "title": "Rain Pulse",
                    "artist": "Harbor Line",
                    "album": "Storm Record",
                    "source_available": True,
                },
            ],
        )
        store.sync_linked_collections(
            library.id,
            source_kind=WMP_PLAYLIST_SOURCE_KIND,
            collections=[
                {
                    "name": "Evening Drive",
                    "source_external_id": "playlist-evening-drive",
                    "track_source_external_ids": ["wmp-road"],
                }
            ],
        )
        return store.get_library(library.id)

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

    def test_track_view_renders_manual_collection_controls_in_context_menu(self) -> None:
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
        self.assertEqual(page.data.count(b"Group from track selection"), 1)
        self.assertEqual(page.data.count(b"collection-studio context-menu-collection-studio"), 1)
        self.assertIn(b'data-collection-selection-scope="tracks"', page.data)
        self.assertIn(b"Track selection is collapsed to full albums before grouping", page.data)
        self.assertIn(b"Demo Singles", page.data)
        self.assertIn(b"data-collection-summary-list", page.data)
        self.assertIn(b"collection-track-label", page.data)
        self.assertIn(b"data-track-album-key", page.data)
        self.assertIn(b"data-track-album-track-ids", page.data)
        self.assertIn(b"context-menu-collection-studio", page.data)
        self.assertIn(b'id="track-context-menu"', page.data)

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

    def test_owner_dashboard_renders_wmp_sync_panel_for_local_access(self) -> None:
        self.app.config["WMP_SERVICE"] = FakeWmpService()

        page = self.client.get(f"/owner/{self.owner_token}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Mirror WMP library", page.data)
        self.assertIn(b"Sync Windows Media Player", page.data)
        self.assertIn(b"Windows Media Player is available.", page.data)
        self.assertIn(b"data-wmp-sync-shell", page.data)
        self.assertIn(b"data-wmp-sync-bar", page.data)
        self.assertIn(b"data-wmp-sync-current", page.data)
        self.assertIn(b"data-wmp-sync-library-link", page.data)

    def test_wmp_sync_json_starts_background_job_and_exposes_progress(self) -> None:
        source_dir = self.temp_dir / "wmp-source"
        source_dir.mkdir()
        source_file = source_dir / "demo.mp3"
        source_file.write_bytes(b"WMP-source-bytes")
        self.app.config["WMP_SERVICE"] = FakeWmpService(source_file)

        response = self.client.post(
            f"/owner/{self.owner_token}/wmp/sync",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )
        self.assertEqual(response.status_code, 202)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertIn("status_url", payload)
        self.assertIn("/s/", payload["wmp"]["library_url"])

        status_payload = wait_for_wmp_sync_job(self.client, payload["status_url"])
        self.assertTrue(status_payload["job"]["ok"])
        self.assertEqual(status_payload["job"]["percent"], 100)
        self.assertEqual(status_payload["job"]["current_item"], "")
        self.assertIn("Synced 1 WMP track", status_payload["job"]["message"])

        libraries = self.app.config["STORE"].list_libraries()
        wmp_library = next(library for library in libraries if library.name == WMP_LIBRARY_NAME)
        self.assertEqual(len(wmp_library.tracks), 1)
        self.assertEqual(wmp_library.tracks[0].title, "WMP Demo")
        self.assertEqual(payload["wmp"]["library_id"], wmp_library.id)

        state_response = self.client.get(f"/s/{wmp_library.id}/state")
        self.assertEqual(state_response.status_code, 200)
        state_payload = state_response.get_json()
        self.assertTrue(state_payload["ok"])
        self.assertEqual(state_payload["library"]["track_count"], 1)
        self.assertTrue(state_payload["library"]["is_wmp_library"])
        self.assertNotIn("owner_token", state_payload.get("wmp_sync") or {})

    def test_wmp_sync_creates_mirrored_library_and_streams_source_file(self) -> None:
        source_dir = self.temp_dir / "wmp-source"
        source_dir.mkdir()
        source_file = source_dir / "demo.mp3"
        source_file.write_bytes(b"WMP-source-bytes")
        self.app.config["WMP_SERVICE"] = FakeWmpService(source_file)

        response = self.client.post(f"/owner/{self.owner_token}/wmp/sync", follow_redirects=False)
        self.assertEqual(response.status_code, 302)

        libraries = self.app.config["STORE"].list_libraries()
        wmp_library = next(library for library in libraries if library.name == WMP_LIBRARY_NAME)
        self.assertEqual(len(wmp_library.tracks), 1)
        track = wmp_library.tracks[0]
        self.assertEqual(track.source_kind, WMP_SOURCE_KIND)
        self.assertEqual(track.source_path, str(source_file))
        self.assertEqual(track.title, "WMP Demo")
        self.assertEqual(len(wmp_library.collections), 1)
        self.assertEqual(wmp_library.collections[0].name, "WMP Favorites")
        self.assertEqual(wmp_library.collections[0].source_kind, WMP_PLAYLIST_SOURCE_KIND)

        library_page = self.client.get(f"/s/{wmp_library.id}?view=albums")
        self.assertEqual(library_page.status_code, 200)
        self.assertIn(b"WMP Favorites", library_page.data)
        self.assertIn(b"Playlist", library_page.data)

        stream_response = self.client.get(f"/s/{wmp_library.id}/tracks/{track.id}/file")
        self.assertEqual(stream_response.status_code, 200)
        self.assertEqual(stream_response.data, b"WMP-source-bytes")
        stream_response.close()

    def test_wmp_sync_json_endpoint_exposes_job_progress(self) -> None:
        source_dir = self.temp_dir / "wmp-source"
        source_dir.mkdir()
        source_file = source_dir / "demo.mp3"
        source_file.write_bytes(b"WMP-source-bytes")
        self.app.config["WMP_SERVICE"] = FakeWmpService(source_file)

        response = self.client.post(
            f"/owner/{self.owner_token}/wmp/sync",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )
        self.assertEqual(response.status_code, 202)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertIn("id", payload["job"])
        self.assertIn("/wmp/sync/", payload["status_url"])

        deadline = time.time() + 2
        observed_current_item = ""
        while time.time() < deadline:
            status_response = self.client.get(
                payload["status_url"],
                headers={"Accept": "application/json", "X-Requested-With": "fetch"},
            )
            status_payload = status_response.get_json()
            observed_current_item = status_payload["job"]["current_item"]
            if observed_current_item:
                break
            time.sleep(0.05)

        self.assertTrue(observed_current_item)
        self.assertIn("WMP", observed_current_item)

        status_payload = wait_for_import_job(self.client, payload["status_url"])
        self.assertTrue(status_payload["job"]["ok"])

    def test_wmp_library_page_exposes_state_polling_metadata(self) -> None:
        wmp_library = self.create_wmp_playlist_fixture()

        page = self.client.get(f"/s/{wmp_library.id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(f'data-library-state-url="/s/{wmp_library.id}/state"'.encode(), page.data)
        self.assertIn(b'data-wmp-library="1"', page.data)
        self.assertIn(b"data-library-live-region", page.data)
        self.assertIn(b"data-library-live-sync", page.data)

    def test_library_state_reports_active_wmp_sync_job_for_incremental_refresh(self) -> None:
        source_dir = self.temp_dir / "wmp-source"
        source_dir.mkdir()
        source_file = source_dir / "demo.mp3"
        source_file.write_bytes(b"WMP-source-bytes")
        self.app.config["WMP_SERVICE"] = FakeWmpService(source_file)

        response = self.client.post(
            f"/owner/{self.owner_token}/wmp/sync",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )
        self.assertEqual(response.status_code, 202)
        payload = response.get_json()
        library_id = payload["wmp"]["library_id"]

        state_response = self.client.get(f"/s/{library_id}/state")
        self.assertEqual(state_response.status_code, 200)
        state_payload = state_response.get_json()
        self.assertTrue(state_payload["ok"])
        self.assertEqual(state_payload["library"]["id"], library_id)
        self.assertTrue(state_payload["library"]["is_wmp_library"])
        self.assertIsNotNone(state_payload["wmp_sync"])
        self.assertEqual(state_payload["wmp_sync"]["library_id"], library_id)
        self.assertNotIn("owner_token", state_payload["wmp_sync"])

        final_payload = wait_for_wmp_sync_job(self.client, payload["status_url"])
        self.assertTrue(final_payload["job"]["ok"])

    def test_wmp_playlist_views_render_searchable_playable_rows(self) -> None:
        wmp_library = self.create_wmp_playlist_fixture()
        first_track = next(track for track in wmp_library.tracks if track.source_external_id == "wmp-road")

        tracks_page = self.client.get(f"/s/{wmp_library.id}?view=tracks")
        self.assertEqual(tracks_page.status_code, 200)
        self.assertIn(b"Evening Drive", tracks_page.data)
        self.assertIn(b"Playlist", tracks_page.data)
        self.assertIn(b"data-collection-track-section", tracks_page.data)
        self.assertIn(b'data-collection-name-search="evening drive"', tracks_page.data)
        self.assertIn(b"Road Runner", tracks_page.data)
        self.assertIn(b"Rain Pulse", tracks_page.data)
        self.assertIn(b'data-track-source-kind="wmp"', tracks_page.data)
        self.assertIn(b'data-track-source-available="1"', tracks_page.data)
        self.assertIn(
            f'data-track-src="/s/{wmp_library.id}/tracks/{first_track.id}/file"'.encode(),
            tracks_page.data,
        )

        albums_page = self.client.get(f"/s/{wmp_library.id}?view=albums")
        self.assertEqual(albums_page.status_code, 200)
        self.assertEqual(albums_page.data.count(b"data-collection-card"), 1)
        self.assertIn(b"Evening Drive", albums_page.data)
        self.assertIn(b"Playlist", albums_page.data)
        self.assertIn(b"data-collection-album-link", albums_page.data)
        self.assertIn(b"Desert Tapes", albums_page.data)
        self.assertIn(b"Storm Record", albums_page.data)
        self.assertIn(b'data-search="evening drive', albums_page.data)

    def test_wmp_track_stream_supports_range_requests_for_audio_playback(self) -> None:
        wmp_library = self.create_wmp_playlist_fixture()
        track = next(track for track in wmp_library.tracks if track.source_external_id == "wmp-road")

        stream_response = self.client.get(
            f"/s/{wmp_library.id}/tracks/{track.id}/file",
            headers={"Range": "bytes=0-2"},
        )
        self.assertEqual(stream_response.status_code, 206)
        self.assertEqual(stream_response.data, b"WMP")
        self.assertIn("bytes 0-2/", stream_response.headers["Content-Range"])
        stream_response.close()

    def test_wmp_rating_endpoint_writes_to_wmp_before_updating_mirror(self) -> None:
        source_dir = self.temp_dir / "wmp-source"
        source_dir.mkdir()
        source_file = source_dir / "demo.mp3"
        source_file.write_bytes(b"WMP-source-bytes")
        service = FakeWmpService(source_file)
        self.app.config["WMP_SERVICE"] = service

        self.client.post(f"/owner/{self.owner_token}/wmp/sync", follow_redirects=False)
        wmp_library = next(library for library in self.app.config["STORE"].list_libraries() if library.name == WMP_LIBRARY_NAME)
        track = wmp_library.tracks[0]

        response = self.client.post(
            f"/s/{wmp_library.id}/tracks/{track.id}/rating",
            json={"rating": 5},
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(service.rating_calls, [("wmp-track-1", str(source_file), 5)])
        updated = self.app.config["STORE"].get_track(wmp_library.id, track.id)
        self.assertEqual(updated.rating, 5)

    def test_wmp_sync_requires_direct_local_access(self) -> None:
        self.app.config["WMP_SERVICE"] = FakeWmpService()

        response = self.client.post(
            f"/owner/{self.owner_token}/wmp/sync",
            base_url="http://music.example.com",
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
