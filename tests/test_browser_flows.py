from __future__ import annotations

import logging
import socket
import threading
import unittest
import uuid
from pathlib import Path

from werkzeug.serving import make_server

from songshare import create_app
from songshare.store import Store
from songshare.wmp_library import WMP_LIBRARY_NAME, WMP_PLAYLIST_SOURCE_KIND, WMP_SOURCE_KIND, WmpStatus, WmpSyncResult

try:
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
except ImportError:  # pragma: no cover - exercised when Selenium is not installed.
    webdriver = None
    WebDriverException = Exception
    By = None
    WebDriverWait = None


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
TEST_DATA_ROOT = TEST_TMP_ROOT / "browser-data"


def new_test_dir() -> Path:
    path = TEST_DATA_ROOT / str(uuid.uuid4())
    path.mkdir(parents=True, exist_ok=False)
    return path


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class BrowserFakeWmpService:
    def __init__(self, source_path: Path):
        self.source_path = source_path

    def status(self):
        return WmpStatus(
            available=True,
            platform="win32",
            access_rights="full",
            item_count=1,
            message="Windows Media Player is available.",
        )

    def sync_to_store(self, store, *, library_id: str | None = None, limit: int | None = None, progress_callback=None):
        library = store.get_library(library_id) if library_id else store.create_library(name=WMP_LIBRARY_NAME)

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
            progress_callback(
                type(
                    "Progress",
                    (),
                    {
                        "phase": "syncing_tracks",
                        "message": "Syncing track 1 of 1...",
                        "percent": 42,
                        "current_item": "Browser Demo Track",
                    },
                )()
            )

        time.sleep(1.1)
        store.sync_linked_tracks(
            library.id,
            source_kind=WMP_SOURCE_KIND,
            tracks=[
                {
                    "source_path": str(self.source_path),
                    "source_external_id": "browser-wmp-track",
                    "original_name": self.source_path.name,
                    "content_type": "audio/mpeg",
                    "size": self.source_path.stat().st_size,
                    "title": "Browser Demo Track",
                    "artist": "Browser Artist",
                    "album": "Browser Album",
                    "source_available": True,
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

        return WmpSyncResult(ok=True, library_id=library.id, total=1, message="Windows Media Player sync finished.")


def make_browser_driver():
    if webdriver is None:
        raise unittest.SkipTest("Selenium is not installed.")

    attempts = []

    for browser_name, options_factory, driver_factory in (
        ("Chrome", webdriver.ChromeOptions, webdriver.Chrome),
        ("Edge", webdriver.EdgeOptions, webdriver.Edge),
    ):
        options = options_factory()
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1280,900")
        options.add_argument("--autoplay-policy=no-user-gesture-required")
        options.add_argument("--disable-gpu")
        try:
            return driver_factory(options=options)
        except WebDriverException as exc:
            attempts.append(f"{browser_name}: {exc.msg}")

    raise unittest.SkipTest("No Selenium browser driver was available. " + " | ".join(attempts))


class PausedBrowserWmpService:
    def __init__(self, source_path: Path):
        self.source_path = source_path
        self.progress_started = threading.Event()
        self.release_sync = threading.Event()

    def status(self):
        return WmpStatus(
            available=True,
            platform="win32",
            access_rights="full",
            item_count=1,
            message="Windows Media Player is available.",
        )

    def sync_to_store(self, store: Store, *, library_id: str | None = None, limit: int | None = None, progress_callback=None):
        library = store.get_library(library_id) if library_id else store.create_library(name=WMP_LIBRARY_NAME)
        if progress_callback:
            progress_callback(
                type(
                    "Progress",
                    (),
                    {
                        "phase": "syncing_tracks",
                        "message": "Syncing track 1 of 1...",
                        "percent": 37,
                        "current_item": self.source_path.name,
                    },
                )()
            )
        self.progress_started.set()
        self.release_sync.wait(timeout=5)

        stats = store.sync_linked_tracks(
            library.id,
            source_kind=WMP_SOURCE_KIND,
            tracks=[
                {
                    "source_path": str(self.source_path),
                    "source_external_id": "browser-wmp-track",
                    "original_name": self.source_path.name,
                    "content_type": "audio/mpeg",
                    "size": self.source_path.stat().st_size,
                    "title": "Browser WMP Demo",
                    "artist": "Browser Artist",
                    "album": "Browser Album",
                    "source_available": True,
                }
            ],
        )
        return WmpSyncResult(
            ok=True,
            library_id=library.id,
            created=stats["created"],
            updated=stats["updated"],
            skipped=stats["skipped"],
            marked_unavailable=stats["marked_unavailable"],
            total=stats["total"],
            message="Synced 1 WMP track and 0 playlists.",
        )


@unittest.skipIf(webdriver is None, "Selenium is not installed.")
class BrowserLibraryFlowTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        cls.driver = make_browser_driver()

    @classmethod
    def tearDownClass(cls) -> None:
        driver = getattr(cls, "driver", None)
        if driver is not None:
            driver.quit()

    def setUp(self) -> None:
        self.temp_dir = new_test_dir()
        self.port = free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.wmp_source_dir = self.temp_dir / "wmp-sync-source"
        self.wmp_source_dir.mkdir()
        self.wmp_source_file = self.wmp_source_dir / "browser-sync.mp3"
        self.wmp_source_file.write_bytes(b"BROWSER-WMP-bytes")
        self.app = create_app(
            {
                "TESTING": True,
                "DATA_DIR": self.temp_dir,
                "BASE_URL": self.base_url,
            }
        )
        self.app.config["WMP_SERVICE"] = BrowserFakeWmpService(self.wmp_source_file)
        self.library = self._create_wmp_playlist_fixture(self.app.config["STORE"])
        self.server = make_server("127.0.0.1", self.port, self.app, threaded=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)

    def _create_wmp_playlist_fixture(self, store: Store):
        source_dir = self.temp_dir / "wmp-source"
        source_dir.mkdir()
        first_source = source_dir / "road-runner.mp3"
        second_source = source_dir / "rain-pulse.mp3"
        first_source.write_bytes(b"WMP-road-runner-bytes")
        second_source.write_bytes(b"WMP-rain-pulse-bytes")

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

    def open_library(self, *, view: str) -> None:
        self.driver.get(f"{self.base_url}/s/{self.library.id}?view={view}")
        WebDriverWait(self.driver, 5).until(
            lambda driver: driver.execute_script("return Boolean(window.__SONGWALK_SCRIPT_VERSION);")
        )

    def set_search(self, query: str) -> None:
        search = self.driver.find_element(By.CSS_SELECTOR, "[data-track-filter]")
        self.driver.execute_script(
            """
            arguments[0].value = arguments[1];
            arguments[0].dispatchEvent(new Event("input", { bubbles: true }));
            """,
            search,
            query,
        )

    def row_hidden(self, title: str):
        return self.driver.execute_script(
            """
            const rows = [...document.querySelectorAll("[data-track-row]:not(.album-browser-hidden-track)")];
            const row = rows.find((candidate) => candidate.dataset.trackTitle === arguments[0]);
            return row ? row.hidden : null;
            """,
            title,
        )

    def collection_track_section_hidden(self, name: str):
        return self.driver.execute_script(
            """
            const sections = [...document.querySelectorAll("[data-collection-track-section]")];
            const section = sections.find((candidate) => candidate.dataset.collectionNameSearch === arguments[0]);
            return section ? section.hidden : null;
            """,
            name,
        )

    def album_card_hidden(self, title: str):
        return self.driver.execute_script(
            """
            const cards = [...document.querySelectorAll("[data-album-card]:not([data-collection-card])")];
            const card = cards.find((candidate) => (candidate.querySelector(".album-title")?.textContent || "") === arguments[0]);
            return card ? card.hidden : null;
            """,
            title,
        )

    def collection_card_hidden(self, title: str):
        return self.driver.execute_script(
            """
            const cards = [...document.querySelectorAll("[data-collection-card]")];
            const card = cards.find((candidate) => (candidate.querySelector(".album-title")?.textContent || "") === arguments[0]);
            return card ? card.hidden : null;
            """,
            title,
        )

    def test_track_view_search_filters_tracks_and_playlist_sections(self) -> None:
        self.open_library(view="tracks")

        self.set_search("coyote road")
        WebDriverWait(self.driver, 5).until(lambda _driver: self.row_hidden("Road Runner") is False)
        self.assertFalse(self.row_hidden("Road Runner"))
        self.assertTrue(self.row_hidden("Rain Pulse"))

        self.set_search("evening")
        WebDriverWait(self.driver, 5).until(lambda _driver: self.collection_track_section_hidden("evening drive") is False)
        self.assertFalse(self.collection_track_section_hidden("evening drive"))
        self.assertFalse(self.row_hidden("Road Runner"))
        self.assertTrue(self.row_hidden("Rain Pulse"))

    def test_album_view_search_filters_album_cards_and_playlist_cards(self) -> None:
        self.open_library(view="albums")

        self.set_search("evening")
        WebDriverWait(self.driver, 5).until(lambda _driver: self.collection_card_hidden("Evening Drive") is False)
        self.assertFalse(self.collection_card_hidden("Evening Drive"))
        self.assertTrue(self.album_card_hidden("Storm Record"))

        self.set_search("storm harbor")
        WebDriverWait(self.driver, 5).until(lambda _driver: self.album_card_hidden("Storm Record") is False)
        self.assertTrue(self.collection_card_hidden("Evening Drive"))
        self.assertFalse(self.album_card_hidden("Storm Record"))

    def test_track_selection_sets_audio_source_for_playback(self) -> None:
        self.open_library(view="tracks")
        first_track = next(track for track in self.library.tracks if track.source_external_id == "wmp-road")

        self.driver.find_element(By.CSS_SELECTOR, '[data-track-title="Road Runner"]').click()
        expected_suffix = f"/s/{self.library.id}/tracks/{first_track.id}/file"
        WebDriverWait(self.driver, 5).until(
            lambda driver: expected_suffix in driver.execute_script(
                'return document.getElementById("deck-player").getAttribute("src") || "";'
            )
        )
        self.assertEqual(
            self.driver.execute_script('return document.getElementById("now-playing-title").textContent;'),
            "Road Runner",
        )

    def test_owner_wmp_sync_shows_progress_and_current_file(self) -> None:
        source_dir = self.temp_dir / "browser-wmp-source"
        source_dir.mkdir()
        source_file = source_dir / "browser-demo.mp3"
        source_file.write_bytes(b"browser-wmp-bytes")
        service = PausedBrowserWmpService(source_file)
        self.app.config["WMP_SERVICE"] = service

        self.driver.get(f"{self.base_url}/owner/{self.app.config['OWNER_TOKEN']}")
        WebDriverWait(self.driver, 5).until(
            lambda driver: driver.execute_script("return Boolean(window.__SONGWALK_SCRIPT_VERSION);")
        )

        self.driver.find_element(By.CSS_SELECTOR, "[data-wmp-sync-form] button[type='submit']").click()
        WebDriverWait(self.driver, 5).until(lambda _driver: service.progress_started.is_set())
        WebDriverWait(self.driver, 5).until(
            lambda driver: driver.execute_script(
                """
                const shell = document.querySelector("[data-wmp-sync-shell]");
                const current = document.querySelector("[data-wmp-sync-current]");
                const copy = document.querySelector("[data-wmp-sync-copy]");
                const link = document.querySelector("[data-wmp-sync-library-link]");
                return shell && !shell.hidden &&
                  current && current.textContent.includes("browser-demo.mp3") &&
                  copy && copy.textContent === "37%" &&
                  link && !link.hidden && link.getAttribute("href").includes("/s/");
                """
            )
        )

        service.release_sync.set()
        WebDriverWait(self.driver, 5).until(lambda driver: "/s/" in driver.current_url)


if __name__ == "__main__":
    unittest.main()
