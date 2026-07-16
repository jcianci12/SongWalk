from __future__ import annotations

import ctypes
import os
import socket
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk
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
        self.window: tk.Tk | None = None
        self._tunnel_label_var: tk.StringVar | None = None
        self._local_label_var: tk.StringVar | None = None

    def run(self) -> None:
        print_runtime_details(self.runtime)
        self.server_thread.start()
        wait_for_server(self.server_thread, self.runtime)
        threading.Thread(
            target=self.open_startup_owner_dashboard,
            name="songwalk-desktop-startup-browser",
            daemon=True,
        ).start()

        self.icon = self._build_tray_icon()
        tray_thread = threading.Thread(
            target=self.icon.run,
            name="songwalk-desktop-tray",
            daemon=True,
        )
        tray_thread.start()

        self._build_window()
        self._update_tunnel_status()
        self.window.mainloop()

    def _build_tray_icon(self) -> pystray.Icon:
        return pystray.Icon(
            "songwalk",
            icon=create_tray_image(),
            title=f"SongWalk on localhost:{self.runtime.port}",
            menu=pystray.Menu(
                pystray.MenuItem("Show SongWalk", self._show_window, default=True),
                pystray.MenuItem("Open owner dashboard", self.open_owner_dashboard),
                pystray.MenuItem("Open SongWalk", self.open_home),
                pystray.MenuItem("Open data folder", self.open_data_folder),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit SongWalk", self.quit_app),
            ),
        )

    def _build_window(self) -> None:
        self.window = tk.Tk()
        self.window.title("SongWalk")
        self.window.geometry("380x240")
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", self._hide_window)
        self.window.configure(bg="#edf4fb")

        try:
            self.window.iconbitmap(default=self._tray_ico_path())
        except Exception:
            pass

        style = ttk.Style(self.window)
        style.theme_use("clam")
        style.configure(
            "Title.TLabel",
            font=("Tahoma", 13, "bold"),
            background="#edf4fb",
            foreground="#1f3550",
        )
        style.configure(
            "Status.TLabel",
            font=("Tahoma", 9),
            background="#edf4fb",
            foreground="#60758e",
        )
        style.configure(
            "Url.TLabel", font=("Tahoma", 9), background="#ffffff", foreground="#1f3550"
        )
        style.configure("UrlBox.TFrame", background="#ffffff")
        style.configure("Primary.TButton", font=("Tahoma", 9, "bold"))

        header = ttk.Frame(self.window, style="UrlBox.TFrame")
        header.pack(fill=tk.X, padx=12, pady=(14, 0))

        ttk.Label(
            header, text="\U0001f3b5", font=("Tahoma", 16), background="#ffffff"
        ).pack(side=tk.LEFT, padx=(10, 6))
        title_col = ttk.Frame(header, style="UrlBox.TFrame")
        title_col.pack(side=tk.LEFT, pady=8)
        ttk.Label(title_col, text="SongWalk is running", style="Title.TLabel").pack(
            anchor=tk.W
        )
        ttk.Label(
            title_col, text="Your music dropbox is online", style="Status.TLabel"
        ).pack(anchor=tk.W)

        url_frame = ttk.Frame(self.window, style="UrlBox.TFrame")
        url_frame.pack(fill=tk.X, padx=12, pady=(10, 0))

        self._local_label_var = tk.StringVar(
            value=f"Local:  http://localhost:{self.runtime.port}"
        )
        ttk.Label(
            url_frame, textvariable=self._local_label_var, style="Url.TLabel"
        ).pack(anchor=tk.W, padx=10, pady=(8, 0))
        ttk.Button(
            url_frame,
            text="Copy",
            width=6,
            command=lambda: self._copy_url(f"http://localhost:{self.runtime.port}"),
        ).place(relx=1.0, x=-60, y=6, anchor=tk.NE)

        self._tunnel_label_var = tk.StringVar(value="Tunnel:  waiting...")
        tunnel_line = ttk.Frame(url_frame, style="UrlBox.TFrame")
        tunnel_line.pack(fill=tk.X, padx=10, pady=(4, 8))
        ttk.Label(
            tunnel_line, textvariable=self._tunnel_label_var, style="Status.TLabel"
        ).pack(side=tk.LEFT)
        self._tunnel_copy_btn = ttk.Button(
            url_frame, text="Copy", width=6, command=self._copy_tunnel_url
        )
        self._tunnel_copy_btn.place(relx=1.0, x=-60, y=34, anchor=tk.NE)

        btn_frame = ttk.Frame(self.window)
        btn_frame.pack(fill=tk.X, padx=12, pady=(10, 0))

        ttk.Button(
            btn_frame,
            text="Open Dashboard",
            style="Primary.TButton",
            command=self.open_owner_dashboard,
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_frame, text="Open SongWalk", command=self.open_home).pack(
            side=tk.LEFT
        )
        ttk.Button(btn_frame, text="Quit", command=self.quit_app).pack(side=tk.RIGHT)

        self.window.after(3000, self._update_tunnel_status)

    def _tray_ico_path(self) -> str:
        ico = Path(__file__).resolve().parent / "images" / "Songwalk logo.ico"
        if ico.exists():
            return str(ico)
        return ""

    def _show_window(self, icon: pystray.Icon | None = None, item=None) -> None:
        if self.window is not None:
            self.window.after(0, self.window.deiconify)
            self.window.after(0, self.window.lift)

    def _hide_window(self) -> None:
        if self.window is not None:
            self.window.withdraw()

    def _copy_url(self, url: str) -> None:
        if self.window is None:
            return
        self.window.clipboard_clear()
        self.window.clipboard_append(url)

    def _copy_tunnel_url(self) -> None:
        manager = self.runtime.quick_tunnel
        if manager is None:
            return
        status = manager.status()
        if status.public_url:
            self._copy_url(status.public_url)

    def _update_tunnel_status(self) -> None:
        if self.window is None or self._tunnel_label_var is None:
            return
        manager = self.runtime.quick_tunnel
        if manager is None:
            self._tunnel_label_var.set("Tunnel:  disabled")
        else:
            status = manager.status()
            if status.public_url:
                self._tunnel_label_var.set(f"Public:  {status.public_url}")
            elif status.last_error:
                self._tunnel_label_var.set(f"Tunnel:  {status.last_error[:50]}")
            else:
                self._tunnel_label_var.set("Tunnel:  connecting...")
        if self.window:
            self.window.after(5000, self._update_tunnel_status)

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


def wait_for_server(
    server_thread: threading.Thread,
    runtime: PreparedRuntime,
    timeout_seconds: float = 20.0,
) -> None:
    deadline = time.time() + timeout_seconds
    last_error = ""

    while time.time() < deadline:
        if not server_thread.is_alive():
            raise RuntimeError("SongWalk server stopped before it came online.")
        try:
            with urlopen(
                f"http://127.0.0.1:{runtime.port}/healthz", timeout=2
            ) as response:
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


def wait_for_owner_dashboard_url(
    runtime: PreparedRuntime, timeout_seconds: float = 20.0
) -> str:
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
    draw.rounded_rectangle(
        (4, 4, size - 4, size - 4), radius=14, fill=(223, 228, 230, 255)
    )
    draw.text((18, 18), "SW", fill=(14, 48, 58, 255))
    return canvas
