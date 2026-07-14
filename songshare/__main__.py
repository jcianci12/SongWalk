from __future__ import annotations

from .runtime import prepare_runtime, print_runtime_details
from .sync import socketio


def main() -> None:
    runtime = prepare_runtime()
    print_runtime_details(runtime)

    socketio.run(
        runtime.app,
        host=runtime.host,
        port=runtime.port,
        debug=runtime.dev_mode,
        allow_unsafe_werkzeug=True,
    )


if __name__ == "__main__":
    main()
