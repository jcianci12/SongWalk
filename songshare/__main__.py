from __future__ import annotations

import os
from pathlib import Path

from waitress import serve

from . import create_app
from .quick_tunnel import QuickTunnelManager


def main() -> None:
    app = create_app()
    host = os.getenv("SONGSHARE_HOST", "0.0.0.0")
    port = int(os.getenv("SONGSHARE_PORT", "8080"))
    dev_mode = os.getenv("SONGSHARE_DEV", "").lower() in {"1", "true", "yes", "on"}
    quick_tunnel_enabled = os.getenv("SONGSHARE_QUICK_TUNNEL_ENABLED", "").lower() in {"1", "true", "yes", "on"}
    local_owner_url = f"http://localhost:{port}{app.config['OWNER_PATH']}"
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
    print(f"SongWalk owner dashboard: {local_owner_url}", flush=True)
    print(f"SongWalk owner URL file: {owner_url_path}", flush=True)

    if should_start_quick_tunnel(dev_mode):
        quick_tunnel = QuickTunnelManager(
            data_dir=Path(app.config["DATA_DIR"]),
            service_url=f"http://127.0.0.1:{port}",
            enabled=quick_tunnel_enabled,
        )
        app.extensions["quick_tunnel_manager"] = quick_tunnel
        quick_tunnel.start(wait_seconds=1.0)

    if dev_mode:
        app.run(
            host=host,
            port=port,
            debug=True,
            use_reloader=True,
            extra_files=watch_files(),
        )
        return

    serve(app, host=host, port=port, threads=8)


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


if __name__ == "__main__":
    main()
