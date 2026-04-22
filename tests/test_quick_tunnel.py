import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from songshare.quick_tunnel import QuickTunnelManager


class _BlockingStdout:
    def __init__(self, lines: list[str], release_event: threading.Event) -> None:
        self._lines = list(lines)
        self._release_event = release_event

    def __iter__(self):
        for line in self._lines:
            yield line
        self._release_event.wait(timeout=2)


class _FakeProcess:
    def __init__(self, lines: list[str], release_event: threading.Event) -> None:
        self.stdout = _BlockingStdout(lines, release_event)
        self._release_event = release_event
        self.pid = 4242

    def wait(self, timeout: float | None = None) -> int:
        self._release_event.wait(timeout=timeout or 2)
        return 0

    def poll(self) -> int | None:
        return 0 if self._release_event.is_set() else None


class QuickTunnelManagerTestCase(unittest.TestCase):
    def test_watch_process_extracts_generated_public_url_and_persists_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = QuickTunnelManager(
                data_dir=Path(temp_dir),
                service_url="http://127.0.0.1:8080",
                enabled=True,
            )
            release_event = threading.Event()
            process = _FakeProcess(
                [
                    "2026-04-07T10:00:00Z INF Starting tunnel\n",
                    "2026-04-07T10:00:01Z INF +--------------------------------------------------------------------------------------------+\n",
                    "2026-04-07T10:00:01Z INF |  https://gentle-sun.trycloudflare.com                                         |\n",
                ],
                release_event,
            )

            manager._process = process
            watcher = threading.Thread(target=manager._watch_process, args=(process,), daemon=True)
            watcher.start()

            self.assertTrue(manager._ready_event.wait(timeout=1), "Tunnel manager never observed a generated public URL.")

            status = manager.status()
            self.assertTrue(status.running)
            self.assertEqual(status.public_url, "https://gentle-sun.trycloudflare.com")
            self.assertEqual(status.message, "Cloudflare Quick Tunnel ready.")

            persisted = json.loads(manager.state_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["public_url"], "https://gentle-sun.trycloudflare.com")
            self.assertTrue(manager._log_path.read_text(encoding="utf-8").count("gentle-sun.trycloudflare.com"))

            release_event.set()
            watcher.join(timeout=1)
            self.assertFalse(watcher.is_alive())

    def test_start_recovers_healthy_persisted_tunnel_without_spawning_new_process(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "quick-tunnel.json"
            state_path.write_text(
                json.dumps(
                    {
                        "enabled": True,
                        "available": True,
                        "running": True,
                        "public_url": "https://gentle-sun.trycloudflare.com",
                        "service_url": "http://127.0.0.1:8080",
                        "message": "Cloudflare Quick Tunnel ready.",
                        "last_error": "",
                        "updated_at": 1.0,
                        "pid": 3333,
                        "started_at": 2.0,
                    }
                ),
                encoding="utf-8",
            )
            manager = QuickTunnelManager(
                data_dir=Path(temp_dir),
                service_url="http://127.0.0.1:8080",
                enabled=True,
            )

            with patch("shutil.which", return_value="cloudflared"), \
                 patch.object(manager, "_pid_is_running", return_value=True), \
                 patch.object(manager, "_probe_public_url", return_value=True), \
                 patch("subprocess.Popen") as popen:
                status = manager.start(wait_seconds=0.1)

            self.assertTrue(status.running)
            self.assertEqual(status.public_url, "https://gentle-sun.trycloudflare.com")
            self.assertEqual(status.message, "Recovered Cloudflare Quick Tunnel.")
            self.assertEqual(status.pid, 3333)
            popen.assert_not_called()

    def test_stop_terminates_recovered_pid_when_process_handle_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "quick-tunnel.json"
            state_path.write_text(
                json.dumps(
                    {
                        "enabled": True,
                        "available": True,
                        "running": True,
                        "public_url": "https://gentle-sun.trycloudflare.com",
                        "service_url": "http://127.0.0.1:8080",
                        "message": "Recovered Cloudflare Quick Tunnel.",
                        "last_error": "",
                        "updated_at": 1.0,
                        "pid": 4444,
                        "started_at": 2.0,
                    }
                ),
                encoding="utf-8",
            )
            manager = QuickTunnelManager(
                data_dir=Path(temp_dir),
                service_url="http://127.0.0.1:8080",
                enabled=True,
            )

            with patch.object(manager, "_terminate_pid") as terminate_pid:
                status = manager.stop()

            terminate_pid.assert_called_once_with(4444)
            self.assertFalse(status.running)
            self.assertEqual(status.pid, 0)
            self.assertEqual(status.public_url, "")


if __name__ == "__main__":
    unittest.main()
