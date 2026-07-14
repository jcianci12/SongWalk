from __future__ import annotations

from waitress import serve

from .runtime import prepare_runtime, print_runtime_details
from .sync import socketio


def main() -> None:
    runtime = prepare_runtime()
    print_runtime_details(runtime)

    if runtime.dev_mode:
        socketio.run(
            runtime.app,
            host=runtime.host,
            port=runtime.port,
            debug=True,
        )
        return

    serve(runtime.app, host=runtime.host, port=runtime.port, threads=8)


if __name__ == "__main__":
    main()
