from __future__ import annotations

from waitress import serve

from .runtime import prepare_runtime, print_runtime_details, watch_files


def main() -> None:
    runtime = prepare_runtime()
    print_runtime_details(runtime)

    if runtime.dev_mode:
        runtime.app.run(
            host=runtime.host,
            port=runtime.port,
            debug=True,
            use_reloader=True,
            extra_files=watch_files(),
        )
        return

    serve(runtime.app, host=runtime.host, port=runtime.port, threads=8)


if __name__ == "__main__":
    main()
