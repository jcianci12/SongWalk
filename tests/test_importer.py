from __future__ import annotations

import io
import unittest
import uuid
from pathlib import Path
from unittest import mock

from songshare.importer import ImportError
from mutagen.id3 import ID3

from songshare.album_lookup import LookupCandidate
from songshare.importer import LibraryImportService
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


def new_test_dir() -> Path:
    path = TEST_TMP_ROOT / str(uuid.uuid4())
    path.mkdir(parents=True, exist_ok=False)
    return path


class FakeLookupClient:
    def __init__(self):
        self.queries: list[tuple[str, str, str]] = []

    def search_release_candidates(self, *, title: str, artist: str, album: str, limit: int = 5):
        self.queries.append((title, artist, album))
        return [
            LookupCandidate(
                release_id="release-123",
                release_group_id="group-123",
                title="Lookup Album",
                artist=artist or "Lookup Artist",
                date="2024-01-01",
                country="AU",
                track_title=title or "Lookup Track",
                cover_art_url="https://example.test/front.jpg",
            )
        ]

    def fetch_cover_art(self, *, release_id: str, release_group_id: str):
        return b"fake-cover", ".jpg"


class FakeCommandRunner:
    def __init__(self, filename: str):
        self.filename = filename
        self.commands: list[list[str]] = []

    def run(self, command: list[str], *, cwd: Path, progress_callback=None):
        self.commands.append(command)
        if progress_callback:
            progress_callback("[download] 42.1% of 3.21MiB at 1.23MiB/s ETA 00:01")
        (cwd / self.filename).write_bytes(b"FAKE-downloaded-track")

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()


class ImportServiceTestCase(unittest.TestCase):
    def test_uploaded_files_are_normalized_and_enriched(self) -> None:
        temp_dir = new_test_dir()
        store = Store(temp_dir)
        library = store.create_library()
        lookup = FakeLookupClient()
        service = LibraryImportService(store=store, lookup_client=lookup)

        outcome = service.import_uploaded_files(
            library.id,
            [
                UploadedTrack(
                    filename="Artist Name - Demo Song [abc123def45].mp3",
                    content_type="audio/mpeg",
                    stream=io.BytesIO(b"FAKE-upload-track"),
                )
            ],
        )

        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.uploaded, 1)
        track = store.get_library(library.id).tracks[0]
        self.assertEqual(track.title, "Demo Song")
        self.assertEqual(track.artist, "Artist Name")
        self.assertEqual(track.album, "Lookup Album")
        self.assertEqual(lookup.queries, [("Demo Song", "Artist Name", "")])

        _, file_path = store.get_track_file(library.id, track.id)
        tags = ID3(file_path)
        self.assertEqual(str(tags["TIT2"]), "Demo Song")
        self.assertEqual(str(tags["TPE1"]), "Artist Name")
        self.assertEqual(str(tags["TALB"]), "Lookup Album")

    def test_youtube_import_uses_downloader_and_tags_result(self) -> None:
        temp_dir = new_test_dir()
        store = Store(temp_dir)
        library = store.create_library()
        lookup = FakeLookupClient()
        runner = FakeCommandRunner("Uploader - Stream Song [video123ab9x].mp3")
        service = LibraryImportService(
            store=store,
            lookup_client=lookup,
            command_runner=runner,
            youtube_command="yt-dlp",
        )

        with mock.patch("songshare.importer._resolve_ffmpeg_args", return_value=["--ffmpeg-location", "ffmpeg"]):
            outcome = service.import_youtube_url(library.id, "https://www.youtube.com/watch?v=demo")

        self.assertTrue(outcome.ok)
        command_text = " ".join(runner.commands[0])
        self.assertTrue("yt_dlp" in command_text or "yt-dlp" in command_text or "youtube-dl" in command_text)
        track = store.get_library(library.id).tracks[0]
        self.assertEqual(track.title, "Stream Song")
        self.assertEqual(track.artist, "Uploader")
        self.assertEqual(track.album, "Lookup Album")

    def test_spotify_import_uses_spotdl(self) -> None:
        temp_dir = new_test_dir()
        store = Store(temp_dir)
        library = store.create_library()
        lookup = FakeLookupClient()
        runner = FakeCommandRunner("Playlist Artist - Playlist Song [video999xy1z].mp3")
        service = LibraryImportService(
            store=store,
            lookup_client=lookup,
            command_runner=runner,
            spotify_command="spotdl",
        )

        with mock.patch("songshare.importer._resolve_ffmpeg_args", return_value=["--ffmpeg", "ffmpeg"]):
            outcome = service.import_spotify_url(library.id, "https://open.spotify.com/track/demo")

        self.assertTrue(outcome.ok)
        command_text = " ".join(runner.commands[0])
        self.assertIn("spotdl", command_text)
        self.assertIn("download", runner.commands[0])
        track = store.get_library(library.id).tracks[0]
        self.assertEqual(track.title, "Playlist Song")
        self.assertEqual(track.artist, "Playlist Artist")

    def test_youtube_search_returns_flat_results(self) -> None:
        temp_dir = new_test_dir()
        store = Store(temp_dir)
        store.create_library()
        lookup = FakeLookupClient()

        class SearchRunner:
            def __init__(self):
                self.commands: list[list[str]] = []

            def run(self, command: list[str], *, cwd: Path, progress_callback=None):
                self.commands.append(command)

                class Result:
                    returncode = 0
                    stdout = (
                        '{"id":"demo123","title":"Demo Song","channel":"Demo Channel","duration":201,'
                        '"thumbnails":[{"url":"https://example.test/thumb.jpg"}]}\n'
                    )
                    stderr = ""

                return Result()

        runner = SearchRunner()
        service = LibraryImportService(
            store=store,
            lookup_client=lookup,
            command_runner=runner,
            youtube_command="yt-dlp",
        )

        results = service.search_youtube("demo song")

        self.assertEqual(results[0]["title"], "Demo Song")
        self.assertEqual(results[0]["channel"], "Demo Channel")
        self.assertEqual(results[0]["duration"], "3:21")
        self.assertEqual(results[0]["url"], "https://www.youtube.com/watch?v=demo123")

    def test_spotify_search_returns_flat_results(self) -> None:
        temp_dir = new_test_dir()
        store = Store(temp_dir)
        lookup = FakeLookupClient()

        class SpotifySearchService(LibraryImportService):
            def _spotify_request_json(self, url: str, *, query_params: dict[str, str]) -> dict:
                return {
                    "tracks": {
                        "items": [
                            {
                                "name": "Demo Track",
                                "artists": [{"name": "Demo Artist"}],
                                "album": {
                                    "name": "Demo Album",
                                    "images": [{"url": "https://example.test/track.jpg"}],
                                },
                                "external_urls": {"spotify": "https://open.spotify.com/track/demo-track"},
                            }
                        ]
                    },
                    "albums": {
                        "items": [
                            {
                                "name": "Demo Album",
                                "artists": [{"name": "Demo Artist"}],
                                "images": [{"url": "https://example.test/album.jpg"}],
                                "external_urls": {"spotify": "https://open.spotify.com/album/demo-album"},
                            }
                        ]
                    },
                    "playlists": {
                        "items": [
                            {
                                "name": "Demo Playlist",
                                "owner": {"display_name": "Demo Curator"},
                                "images": [{"url": "https://example.test/playlist.jpg"}],
                                "external_urls": {"spotify": "https://open.spotify.com/playlist/demo-playlist"},
                            }
                        ]
                    },
                }

        service = SpotifySearchService(
            store=store,
            lookup_client=lookup,
            spotify_client_id="demo-id",
            spotify_client_secret="demo-secret",
        )

        results = service.search_spotify("demo song")

        self.assertEqual(results[0]["kind"], "track")
        self.assertEqual(results[0]["title"], "Demo Track")
        self.assertEqual(results[0]["subtitle"], "Demo Artist · Demo Album")
        self.assertEqual(results[0]["url"], "https://open.spotify.com/track/demo-track")
        self.assertEqual(results[1]["kind"], "album")
        self.assertEqual(results[1]["subtitle"], "Demo Artist · Album")
        self.assertEqual(results[2]["kind"], "playlist")
        self.assertEqual(results[2]["subtitle"], "Demo Curator · Playlist")

    def test_spotify_search_requires_client_credentials(self) -> None:
        temp_dir = new_test_dir()
        store = Store(temp_dir)
        lookup = FakeLookupClient()
        service = LibraryImportService(store=store, lookup_client=lookup)

        with self.assertRaisesRegex(
            ImportError,
            "Spotify search requires SONGSHARE_SPOTIFY_CLIENT_ID and SONGSHARE_SPOTIFY_CLIENT_SECRET.",
        ):
            service.search_spotify("demo song")


if __name__ == "__main__":
    unittest.main()
