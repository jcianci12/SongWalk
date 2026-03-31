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
