from __future__ import annotations

import atexit
import json
import re
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path


TRYCLOUDFLARE_URL_RE = re.compile(r"https://[-a-z0-9]+\.trycloudflare\.com")


@dataclass
class QuickTunnelStatus:
    enabled: bool = False
    available: bool = False
    running: bool = False
    public_url: str = ""
    service_url: str = ""
    message: str = ""
    last_error: str = ""
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class QuickTunnelManager:
    def __init__(
        self,
        *,
        data_dir: Path,
        service_url: str,
        enabled: bool = False,
        binary_name: str = "cloudflared",
    ) -> None:
        self._data_dir = Path(data_dir)
        self._service_url = service_url
        self._enabled = enabled
        self._binary_name = binary_name
        self._state_path = self._data_dir / "quick-tunnel.json"
        self._log_path = self._data_dir / "quick-tunnel.log"
        self._lock = threading.RLock()
        self._ready_event = threading.Event()
        self._process: subprocess.Popen[str] | None = None
        self._status = QuickTunnelStatus(
            enabled=enabled,
            available=False,
            running=False,
            service_url=service_url,
            message="Quick Tunnel is disabled.",
            updated_at=time.time(),
        )
        atexit.register(self.stop)

    @property
    def state_path(self) -> Path:
        return self._state_path

    def status(self) -> QuickTunnelStatus:
        with self._lock:
            status = self._status
            return QuickTunnelStatus(**status.to_dict())

    def start(self, *, wait_seconds: float = 0.0) -> QuickTunnelStatus:
        with self._lock:
            if not self._enabled:
                self._set_status_locked(
                    available=False,
                    running=False,
                    public_url="",
                    message="Quick Tunnel is disabled.",
                    last_error="",
                )
                return self.status()

            binary_path = shutil.which(self._binary_name)
            if not binary_path:
                self._set_status_locked(
                    available=False,
                    running=False,
                    public_url="",
                    message="cloudflared is not installed in this runtime.",
                    last_error="Quick Tunnel could not start because the cloudflared binary was not found.",
                )
                return self.status()

            if self._process and self._process.poll() is None:
                should_wait = True
            else:
                self._ready_event.clear()
                self._set_status_locked(
                    available=True,
                    running=True,
                    public_url="",
                    message="Starting Cloudflare Quick Tunnel...",
                    last_error="",
                )

                process = subprocess.Popen(
                    [binary_path, "tunnel", "--no-autoupdate", "--url", self._service_url],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                )
                self._process = process

                reader = threading.Thread(
                    target=self._watch_process,
                    args=(process,),
                    name="songshare-quick-tunnel",
                    daemon=True,
                )
                reader.start()
                should_wait = True

        if should_wait and wait_seconds > 0:
            self._ready_event.wait(timeout=wait_seconds)
        return self.status()

    def rotate(self, *, wait_seconds: float = 20.0) -> QuickTunnelStatus:
        self.stop(clear_message=False)
        return self.start(wait_seconds=wait_seconds)

    def stop(self, *, clear_message: bool = True) -> QuickTunnelStatus:
        with self._lock:
            process = self._process
            self._process = None

        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

        with self._lock:
            self._ready_event.clear()
            self._set_status_locked(
                running=False,
                public_url="",
                message="Quick Tunnel stopped." if clear_message else "Restarting Cloudflare Quick Tunnel...",
                last_error="",
            )
            return self.status()

    def _watch_process(self, process: subprocess.Popen[str]) -> None:
        public_url = ""
        try:
            stream = process.stdout
            if stream is not None:
                for raw_line in stream:
                    line = raw_line.rstrip()
                    if line:
                        self._append_log(line)
                    match = TRYCLOUDFLARE_URL_RE.search(line)
                    if match:
                        public_url = match.group(0)
                        with self._lock:
                            if self._process is process:
                                self._set_status_locked(
                                    available=True,
                                    running=True,
                                    public_url=public_url,
                                    message="Cloudflare Quick Tunnel ready.",
                                    last_error="",
                                )
                                self._ready_event.set()
                        print(f"SongWalk public URL: {public_url}", flush=True)
        finally:
            exit_code = process.wait()
            with self._lock:
                if self._process is process:
                    self._process = None
                    self._set_status_locked(
                        available=self._enabled and shutil.which(self._binary_name) is not None,
                        running=False,
                        public_url="",
                        message="Cloudflare Quick Tunnel exited.",
                        last_error="" if exit_code == 0 else f"cloudflared exited with code {exit_code}.",
                    )
                    self._ready_event.set()

    def _append_log(self, line: str) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        with self._log_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.write("\n")

    def _set_status_locked(self, **changes) -> None:
        for key, value in changes.items():
            setattr(self._status, key, value)
        self._status.updated_at = time.time()
        self._persist_status_locked()

    def _persist_status_locked(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps(self._status.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )
