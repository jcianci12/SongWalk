from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from songshare.desktop import public_owner_dashboard_is_ready, public_owner_dashboard_url, wait_for_owner_dashboard_url
from songshare.quick_tunnel import QuickTunnelStatus


class FakeQuickTunnelManager:
    def __init__(self, statuses: list[QuickTunnelStatus]):
        self._statuses = list(statuses)
        self._index = 0

    def status(self) -> QuickTunnelStatus:
        status = self._statuses[min(self._index, len(self._statuses) - 1)]
        if self._index < len(self._statuses) - 1:
            self._index += 1
        return status


class DesktopRuntimeTestCase(unittest.TestCase):
    def make_runtime(self, manager) -> SimpleNamespace:
        return SimpleNamespace(
            quick_tunnel=manager,
            local_owner_url="http://localhost:8080/owner/local-token",
            app=SimpleNamespace(config={"OWNER_PATH": "/owner/local-token"}),
        )

    def test_public_owner_dashboard_url_uses_quick_tunnel_host(self) -> None:
        runtime = self.make_runtime(
            FakeQuickTunnelManager(
                [
                    QuickTunnelStatus(
                        enabled=True,
                        available=True,
                        running=True,
                        public_url="https://demo.trycloudflare.com",
                    )
                ]
            )
        )

        self.assertEqual(
            public_owner_dashboard_url(runtime),
            "https://demo.trycloudflare.com/owner/local-token",
        )

    def test_wait_for_owner_dashboard_url_prefers_public_url(self) -> None:
        runtime = self.make_runtime(
            FakeQuickTunnelManager(
                [
                    QuickTunnelStatus(enabled=True, available=True, running=True, public_url=""),
                    QuickTunnelStatus(
                        enabled=True,
                        available=True,
                        running=True,
                        public_url="https://demo.trycloudflare.com",
                    ),
                ]
            )
        )

        with patch("songshare.desktop.public_owner_dashboard_is_ready", side_effect=[False, True]):
            self.assertEqual(
                wait_for_owner_dashboard_url(runtime, timeout_seconds=1.0),
                "https://demo.trycloudflare.com/owner/local-token",
            )

    def test_wait_for_owner_dashboard_url_falls_back_to_local_when_tunnel_fails(self) -> None:
        runtime = self.make_runtime(
            FakeQuickTunnelManager(
                [
                    QuickTunnelStatus(
                        enabled=True,
                        available=False,
                        running=False,
                        public_url="",
                        last_error="cloudflared missing",
                    )
                ]
            )
        )

        self.assertEqual(
            wait_for_owner_dashboard_url(runtime, timeout_seconds=1.0),
            "http://localhost:8080/owner/local-token",
        )

    def test_public_owner_dashboard_is_ready_checks_dns_and_http(self) -> None:
        runtime = self.make_runtime(
            FakeQuickTunnelManager(
                [
                    QuickTunnelStatus(
                        enabled=True,
                        available=True,
                        running=True,
                        public_url="https://demo.trycloudflare.com",
                    )
                ]
            )
        )

        with patch("songshare.desktop.socket.getaddrinfo", return_value=[object()]):
            with patch("songshare.desktop.urlopen") as mocked_urlopen:
                mocked_urlopen.return_value.__enter__.return_value.status = 200
                self.assertTrue(public_owner_dashboard_is_ready(runtime))

    def test_wait_for_owner_dashboard_url_returns_local_when_public_page_never_becomes_ready(self) -> None:
        runtime = self.make_runtime(
            FakeQuickTunnelManager(
                [
                    QuickTunnelStatus(
                        enabled=True,
                        available=True,
                        running=True,
                        public_url="https://demo.trycloudflare.com",
                    )
                ]
            )
        )

        with patch("songshare.desktop.public_owner_dashboard_is_ready", return_value=False):
            self.assertEqual(
                wait_for_owner_dashboard_url(runtime, timeout_seconds=0.3),
                "http://localhost:8080/owner/local-token",
            )


if __name__ == "__main__":
    unittest.main()
