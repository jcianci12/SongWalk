from __future__ import annotations

import os
from pathlib import Path

from waitress import serve

from . import create_app


def main() -> None:
    app = create_app()
    host = os.getenv("SONGSHARE_HOST", "0.0.0.0")
    port = int(os.getenv("SONGSHARE_PORT", "8080"))
    dev_mode = os.getenv("SONGSHARE_DEV", "").lower() in {"1", "true", "yes", "on"}
    local_owner_url = f"http://localhost:{port}{app.config['OWNER_PATH']}"
    owner_url_path = Path(app.config["DATA_DIR"]) / "owner-url.txt"
    owner_url_path.write_text(
        "\n".join(
            [
                "Songshare owner dashboard",
                local_owner_url,
                "",
                "If you are using a public tunnel or reverse proxy, append this private path to that host instead:",
                app.config["OWNER_PATH"],
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Songshare owner dashboard: {local_owner_url}", flush=True)
    print(f"Songshare owner URL file: {owner_url_path}", flush=True)

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


if __name__ == "__main__":
    main()
