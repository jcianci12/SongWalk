from __future__ import annotations

import atexit
import json
import os
import re
import signal
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import urlopen


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
    pid: int = 0
    started_at: float = 0.0

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
        self._load_persisted_status_locked()
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
                    pid=0,
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
                    pid=0,
                )
                return self.status()

            if self._process and self._process.poll() is None:
                should_wait = True
            elif self._recover_existing_tunnel_locked():
                should_wait = False
            else:
                self._ready_event.clear()
                self._set_status_locked(
                    available=True,
                    running=True,
                    public_url="",
                    message="Starting Cloudflare Quick Tunnel...",
                    last_error="",
                    pid=0,
                    started_at=time.time(),
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
                self._set_status_locked(
                    available=True,
                    running=True,
                    public_url="",
                    message="Starting Cloudflare Quick Tunnel...",
                    last_error="",
                    pid=process.pid,
                    started_at=time.time(),
                )

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
            persisted_pid = self._status.pid

        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        elif persisted_pid:
            self._terminate_pid(persisted_pid)

        with self._lock:
            self._ready_event.clear()
            self._set_status_locked(
                running=False,
                public_url="",
                message="Quick Tunnel stopped." if clear_message else "Restarting Cloudflare Quick Tunnel...",
                last_error="",
                pid=0,
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
                                    pid=process.pid,
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
                        pid=0,
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

    def _load_persisted_status_locked(self) -> None:
        if not self._state_path.exists():
            return
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return

        for key in self._status.to_dict().keys():
            if key in payload:
                setattr(self._status, key, payload[key])
        self._status.enabled = self._enabled
        self._status.service_url = self._service_url

    def _recover_existing_tunnel_locked(self) -> bool:
        public_url = self._status.public_url.strip()
        pid = int(self._status.pid or 0)
        if not public_url or pid <= 0:
            self._set_status_locked(
                available=True,
                running=False,
                public_url="",
                message="Quick Tunnel is offline.",
                last_error="",
                pid=0,
            )
            return False

        if not self._pid_is_running(pid):
            self._set_status_locked(
                available=True,
                running=False,
                public_url="",
                message="Saved Quick Tunnel was no longer running.",
                last_error="",
                pid=0,
            )
            return False

        if not self._probe_public_url(public_url):
            self._set_status_locked(
                available=True,
                running=False,
                public_url="",
                message="Saved Quick Tunnel was unreachable.",
                last_error="",
                pid=0,
            )
            return False

        self._ready_event.set()
        self._set_status_locked(
            available=True,
            running=True,
            public_url=public_url,
            message="Recovered Cloudflare Quick Tunnel.",
            last_error="",
            pid=pid,
        )
        return True

    @staticmethod
    def _pid_is_running(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _terminate_pid(self, pid: int) -> None:
        if pid <= 0 or not self._pid_is_running(pid):
            return

        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return

        deadline = time.time() + 5
        while time.time() < deadline:
            if not self._pid_is_running(pid):
                return
            time.sleep(0.1)

        try:
            os.kill(pid, signal.SIGKILL)
        except (AttributeError, OSError):
            return

    def _probe_public_url(self, public_url: str, *, timeout: float = 2.0) -> bool:
        try:
            parts = urlsplit(public_url)
            health_url = urlunsplit((parts.scheme, parts.netloc, "/healthz", "", ""))
            with urlopen(health_url, timeout=timeout) as response:
                return response.status == 200
        except (OSError, URLError, ValueError):
            return False

    def _persist_status_locked(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps(self._status.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )
