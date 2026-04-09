from __future__ import annotations

import ctypes
import os
import socket
import threading
import time
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pystray
from PIL import Image, ImageDraw
from waitress import create_server

from .runtime import PreparedRuntime, prepare_runtime, print_runtime_details


def main() -> None:
    try:
        app = SongWalkDesktopApp()
        app.run()
    except Exception as exc:
        show_startup_error(str(exc))
        raise


class SongWalkDesktopApp:
    def __init__(self) -> None:
        self.runtime = prepare_runtime()
        self.server = create_server(
            self.runtime.app,
            host=self.runtime.host,
            port=self.runtime.port,
            threads=8,
        )
        self.server_thread = threading.Thread(
            target=self.server.run,
            name="songwalk-desktop-server",
            daemon=True,
        )
        self.icon: pystray.Icon | None = None

    def run(self) -> None:
        print_runtime_details(self.runtime)
        self.server_thread.start()
        wait_for_server(self.server_thread, self.runtime)
        threading.Thread(
            target=self.open_startup_owner_dashboard,
            name="songwalk-desktop-startup-browser",
            daemon=True,
        ).start()

        self.icon = pystray.Icon(
            "songwalk",
            icon=create_tray_image(),
            title=f"SongWalk on localhost:{self.runtime.port}",
            menu=pystray.Menu(
                pystray.MenuItem("Open owner dashboard", self.open_owner_dashboard, default=True),
                pystray.MenuItem("Open SongWalk", self.open_home),
                pystray.MenuItem("Open data folder", self.open_data_folder),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit SongWalk", self.quit_app),
            ),
        )
        self.icon.run()

    def open_startup_owner_dashboard(self) -> None:
        webbrowser.open(wait_for_owner_dashboard_url(self.runtime))

    def open_home(self, icon: pystray.Icon | None = None, item=None) -> None:
        webbrowser.open(self.runtime.local_home_url)

    def open_owner_dashboard(self, icon: pystray.Icon | None = None, item=None) -> None:
        webbrowser.open(wait_for_owner_dashboard_url(self.runtime, timeout_seconds=0.0))

    def open_data_folder(self, icon: pystray.Icon | None = None, item=None) -> None:
        data_dir = Path(self.runtime.app.config["DATA_DIR"]).resolve()
        if hasattr(os, "startfile"):
            os.startfile(str(data_dir))
            return
        webbrowser.open(data_dir.as_uri())

    def quit_app(self, icon: pystray.Icon, item) -> None:
        threading.Thread(
            target=self._shutdown,
            args=(icon,),
            name="songwalk-desktop-shutdown",
            daemon=True,
        ).start()

    def _shutdown(self, icon: pystray.Icon) -> None:
        try:
            if self.runtime.quick_tunnel is not None:
                self.runtime.quick_tunnel.stop()
            self.server.close()
            self.server_thread.join(timeout=5)
        finally:
            icon.stop()


def wait_for_server(server_thread: threading.Thread, runtime: PreparedRuntime, timeout_seconds: float = 20.0) -> None:
    deadline = time.time() + timeout_seconds
    last_error = ""

    while time.time() < deadline:
        if not server_thread.is_alive():
            raise RuntimeError("SongWalk server stopped before it came online.")
        try:
            with urlopen(f"http://127.0.0.1:{runtime.port}/healthz", timeout=2) as response:
                if response.status == 200:
                    return
        except URLError as exc:
            last_error = str(exc)
        except OSError as exc:
            last_error = str(exc)
        time.sleep(0.25)

    raise RuntimeError(
        f"SongWalk server did not come online at {runtime.local_home_url}. Last error: {last_error or 'unknown'}"
    )


def public_owner_dashboard_url(runtime: PreparedRuntime) -> str:
    manager = runtime.quick_tunnel
    if manager is None:
        return ""
    status = manager.status()
    if not status.public_url:
        return ""
    return f"{status.public_url}{runtime.app.config['OWNER_PATH']}"


def public_owner_dashboard_is_ready(runtime: PreparedRuntime) -> bool:
    public_url = public_owner_dashboard_url(runtime)
    if not public_url:
        return False

    host = public_url.split("://", 1)[-1].split("/", 1)[0]
    try:
        socket.getaddrinfo(host, 443)
        with urlopen(public_url, timeout=3) as response:
            return response.status == 200
    except OSError:
        return False
    except URLError:
        return False


def wait_for_owner_dashboard_url(runtime: PreparedRuntime, timeout_seconds: float = 20.0) -> str:
    if timeout_seconds <= 0:
        return public_owner_dashboard_url(runtime) or runtime.local_owner_url

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if public_owner_dashboard_is_ready(runtime):
            return public_owner_dashboard_url(runtime)

        manager = runtime.quick_tunnel
        if manager is None:
            return runtime.local_owner_url

        status = manager.status()
        if not status.enabled or status.last_error:
            return runtime.local_owner_url
        time.sleep(0.25)

    return runtime.local_owner_url


def show_startup_error(message: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(
            None,
            f"SongWalk could not start.\n\n{message}",
            "SongWalk startup error",
            0x10,
        )
    except Exception:
        pass


def create_tray_image(size: int = 64) -> Image.Image:
    logo_path = Path(__file__).resolve().parent / "images" / "Songwalk logo.png"
    if logo_path.exists():
        logo = Image.open(logo_path).convert("RGBA")
        logo.thumbnail((size - 8, size - 8), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (size, size), (14, 48, 58, 255))
        offset = ((size - logo.width) // 2, (size - logo.height) // 2)
        canvas.paste(logo, offset, logo)
        return canvas

    canvas = Image.new("RGBA", (size, size), (14, 48, 58, 255))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((4, 4, size - 4, size - 4), radius=14, fill=(223, 228, 230, 255))
    draw.text((18, 18), "SW", fill=(14, 48, 58, 255))
    return canvas
