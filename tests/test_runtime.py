from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from songshare.runtime import ensure_portable_data_dir, prepare_runtime, resolve_cloudflared_binary, resolve_quick_tunnel_enabled


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


class SongshareRuntimeTestCase(unittest.TestCase):
    def test_ensure_portable_data_dir_uses_executable_folder_when_frozen(self) -> None:
        temp_dir = new_test_dir()
        executable = temp_dir / "SongWalk.exe"
        executable.write_bytes(b"")

        with patch.dict(os.environ, {}, clear=True):
            with patch.object(sys, "frozen", True, create=True):
                with patch.object(sys, "executable", str(executable)):
                    data_dir = ensure_portable_data_dir()

        self.assertEqual(data_dir, temp_dir / "songshare-data")

    def test_prepare_runtime_writes_owner_url_file(self) -> None:
        temp_dir = new_test_dir()

        with patch.dict(
            os.environ,
            {
                "SONGSHARE_DATA_DIR": str(temp_dir),
                "SONGSHARE_PORT": "8097",
            },
            clear=True,
        ):
            runtime = prepare_runtime({"TESTING": True, "DATA_DIR": temp_dir})

        owner_url_text = runtime.owner_url_path.read_text(encoding="utf-8")
        self.assertIn("SongWalk owner dashboard", owner_url_text)
        self.assertIn(runtime.local_owner_url, owner_url_text)
        self.assertIn(runtime.app.config["OWNER_PATH"], owner_url_text)
        self.assertEqual(runtime.local_home_url, "http://localhost:8097/")

    def test_resolve_cloudflared_binary_uses_sibling_executable_when_frozen(self) -> None:
        temp_dir = new_test_dir()
        executable = temp_dir / "SongWalk.exe"
        bundled_binary = temp_dir / "cloudflared.exe"
        executable.write_bytes(b"")
        bundled_binary.write_bytes(b"")

        with patch.dict(os.environ, {}, clear=True):
            with patch.object(sys, "frozen", True, create=True):
                with patch.object(sys, "executable", str(executable)):
                    binary = resolve_cloudflared_binary()

        self.assertEqual(binary, str(bundled_binary))

    def test_resolve_quick_tunnel_enabled_defaults_on_for_frozen_build(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(sys, "frozen", True, create=True):
                enabled = resolve_quick_tunnel_enabled()

        self.assertTrue(enabled)

    def test_resolve_quick_tunnel_enabled_respects_explicit_off_value(self) -> None:
        with patch.dict(os.environ, {"SONGSHARE_QUICK_TUNNEL_ENABLED": "0"}, clear=True):
            with patch.object(sys, "frozen", True, create=True):
                enabled = resolve_quick_tunnel_enabled()

        self.assertFalse(enabled)
