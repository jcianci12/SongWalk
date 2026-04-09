from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from flask import Flask

from . import create_app
from .quick_tunnel import QuickTunnelManager


@dataclass
class PreparedRuntime:
    app: Flask
    host: str
    port: int
    dev_mode: bool
    local_home_url: str
    local_owner_url: str
    owner_url_path: Path
    quick_tunnel: QuickTunnelManager | None = None


def ensure_portable_data_dir() -> Path | None:
    configured = os.getenv("SONGSHARE_DATA_DIR", "").strip()
    if configured:
        return Path(configured)

    if not getattr(sys, "frozen", False):
        return None

    data_dir = Path(sys.executable).resolve().parent / "songshare-data"
    os.environ["SONGSHARE_DATA_DIR"] = str(data_dir)
    return data_dir


def prepare_runtime(test_config: dict | None = None) -> PreparedRuntime:
    ensure_portable_data_dir()

    app = create_app(test_config)
    host = os.getenv("SONGSHARE_HOST", "0.0.0.0")
    port = int(os.getenv("SONGSHARE_PORT", "8080"))
    dev_mode = os.getenv("SONGSHARE_DEV", "").lower() in {"1", "true", "yes", "on"}
    quick_tunnel_enabled = resolve_quick_tunnel_enabled()
    app.config["QUICK_TUNNEL_ENABLED"] = quick_tunnel_enabled

    local_home_url = f"http://localhost:{port}/"
    local_owner_url = f"http://localhost:{port}{app.config['OWNER_PATH']}"
    owner_url_path = write_owner_url_file(app=app, local_owner_url=local_owner_url)

    quick_tunnel = None
    if should_start_quick_tunnel(dev_mode):
        quick_tunnel = QuickTunnelManager(
            data_dir=Path(app.config["DATA_DIR"]),
            service_url=f"http://127.0.0.1:{port}",
            enabled=quick_tunnel_enabled,
            binary_name=resolve_cloudflared_binary(),
        )
        app.extensions["quick_tunnel_manager"] = quick_tunnel
        quick_tunnel.start(wait_seconds=1.0)

    return PreparedRuntime(
        app=app,
        host=host,
        port=port,
        dev_mode=dev_mode,
        local_home_url=local_home_url,
        local_owner_url=local_owner_url,
        owner_url_path=owner_url_path,
        quick_tunnel=quick_tunnel,
    )


def write_owner_url_file(*, app: Flask, local_owner_url: str) -> Path:
    owner_url_path = Path(app.config["DATA_DIR"]) / "owner-url.txt"
    owner_url_path.write_text(
        "\n".join(
            [
                "SongWalk owner dashboard",
                local_owner_url,
                "",
                "If you are using a public tunnel or reverse proxy, append this private path to that host instead:",
                app.config["OWNER_PATH"],
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return owner_url_path


def print_runtime_details(runtime: PreparedRuntime) -> None:
    print(f"SongWalk owner dashboard: {runtime.local_owner_url}", flush=True)
    print(f"SongWalk owner URL file: {runtime.owner_url_path}", flush=True)


def watch_files() -> list[str]:
    root = Path(__file__).resolve().parent
    watched: list[str] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix == ".py":
            watched.append(str(path))
    return watched


def should_start_quick_tunnel(dev_mode: bool) -> bool:
    if not dev_mode:
        return True
    return os.getenv("WERKZEUG_RUN_MAIN") == "true"


def resolve_quick_tunnel_enabled() -> bool:
    configured = os.getenv("SONGSHARE_QUICK_TUNNEL_ENABLED", "").strip().lower()
    if configured in {"1", "true", "yes", "on"}:
        return True
    if configured in {"0", "false", "no", "off"}:
        return False
    return bool(getattr(sys, "frozen", False))


def resolve_cloudflared_binary() -> str:
    configured = os.getenv("SONGSHARE_CLOUDFLARED_BIN", "").strip()
    if configured:
        return configured

    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        binary_name = "cloudflared.exe" if os.name == "nt" else "cloudflared"
        bundled_binary = executable_dir / binary_name
        if bundled_binary.exists():
            return str(bundled_binary)

    return "cloudflared"
