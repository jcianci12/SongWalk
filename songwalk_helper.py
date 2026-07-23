"""SongWalk YouTube Helper — Desktop App. Downloads YouTube audio as mp3, uploads to SongWalk."""

import argparse, os, shutil, subprocess, sys, tempfile
from pathlib import Path
import requests

try:
    import webview
except ImportError:
    webview = None

APP_TITLE = "SongWalk YouTube Helper"


class SongWalkHelper:
    def __init__(self, server_url, library_id, youtube_url=None):
        self.server = server_url.rstrip("/")
        self.library_id = library_id
        self.youtube_url = youtube_url

    def do_download(self, url):
        td = Path(tempfile.mkdtemp(prefix="songwalk_"))
        ytdlp = self._find_ytdlp()
        ffmpeg_exe, ffprobe_exe = self._find_ffmpeg()

        # Step 1: download format 18 (mp4 with AAC audio)
        cmd = [
            ytdlp,
            "--extractor-args",
            "youtube:player_client=android,ios,mweb",
            "-f",
            "18",
            "-o",
            str(td / "%(title)s.%(ext)s"),
            "--no-playlist",
            "--no-warnings",
        ]
        cmd.append(url)

        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300, cwd=str(td)
            )
        except subprocess.TimeoutExpired:
            return False, "Download timed out (5 min)"

        files = list(td.glob("*.mp4")) + list(td.glob("*.webm"))
        if not files:
            lines = (r.stderr or r.stdout).strip().split("\n")[-5:]
            return False, "Download failed:\n" + "\n".join(lines)

        input_path = files[0]
        mp3_path = input_path.with_suffix(".mp3")

        # Step 2: convert to mp3 using ffmpeg
        if ffmpeg_exe and input_path.suffix.lower() != ".mp3":
            try:
                conv = subprocess.run(
                    [
                        ffmpeg_exe,
                        "-y",
                        "-i",
                        str(input_path),
                        "-vn",
                        "-acodec",
                        "libmp3lame",
                        "-q:a",
                        "2",
                        str(mp3_path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if conv.returncode == 0 and mp3_path.exists():
                    input_path.unlink()  # remove mp4
                    input_path = mp3_path
            except Exception:
                pass  # keep mp4 if conversion fails

        mb = input_path.stat().st_size / (1024 * 1024)

        # Step 3: upload
        try:
            with open(input_path, "rb") as f:
                resp = requests.post(
                    f"{self.server}/s/{self.library_id}/upload",
                    files={"tracks": (input_path.name, f, "audio/mpeg")},
                    timeout=120,
                )
            ok = resp.ok or resp.status_code in (302, 303)
        except requests.exceptions.ConnectionError:
            ok = False
            resp = None
        except requests.exceptions.Timeout:
            ok = False
            resp = None

        try:
            shutil.rmtree(td, ignore_errors=True)
        except:
            pass

        if ok:
            return (
                True,
                f"Downloaded {input_path.name} ({mb:.1f} MB)\nUploaded to {self.server}/s/{self.library_id}",
            )
        else:
            code = getattr(resp, "status_code", "?")
            return False, f"Upload failed: HTTP {code}"

    @staticmethod
    def _find_ytdlp():
        for name in ("yt-dlp", "yt-dlp.exe"):
            p = shutil.which(name)
            if p:
                return p
        return "yt-dlp"

    @staticmethod
    def _find_ffmpeg():
        """Return (ffmpeg_path, ffprobe_path) or (None, None)."""
        # Try system ffmpeg first
        ffmpeg = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
        ffprobe = shutil.which("ffprobe") or shutil.which("ffprobe.exe")
        if ffmpeg:
            return ffmpeg, ffprobe
        # Fall back to imageio-ffmpeg (copy to temp dir with correct names)
        try:
            from imageio_ffmpeg import get_ffmpeg_exe

            exe = Path(get_ffmpeg_exe())
            if exe.exists():
                td = Path(tempfile.gettempdir()) / "songwalk_ffmpeg"
                td.mkdir(exist_ok=True)
                f1, f2 = td / "ffmpeg.exe", td / "ffprobe.exe"
                if not f1.exists():
                    shutil.copy2(exe, f1)
                if not f2.exists():
                    shutil.copy2(exe, f2)
                return str(f1), str(f2)
        except:
            pass
        return None, None

    # GUI
    def _html(self):
        uv = self.youtube_url or ""
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>SongWalk</title>
<style>*{{box-sizing:border-box;margin:0;padding:0}}body{{font-family:system-ui;padding:1rem;background:#111;color:#ddd}}
h2{{font-size:1.1rem;color:#fff;margin-bottom:.8rem}}
label{{font-size:.8rem;color:#999;margin:.5rem 0 .2rem;display:block}}
input{{width:100%;padding:.5rem;border:1px solid #444;border-radius:4px;background:#1a1a1a;color:#eee;font-size:.9rem}}
button{{padding:.5rem 1.2rem;margin:.8rem .3rem 0 0;border:none;border-radius:4px;cursor:pointer;font-weight:600;font-size:.9rem}}
.login{{background:#3ea6ff;color:#000}}.dl{{background:#2ba640;color:#fff}}
.prog{{margin-top:.8rem;height:6px;display:none}}
.prog::-webkit-progress-bar{{background:#333;border-radius:3px}}
.prog::-webkit-progress-value{{background:#3ea6ff;border-radius:3px}}
.status{{margin-top:1rem;padding:.8rem;border-radius:6px;background:#1a1a1a;font-size:.8rem;white-space:pre-wrap}}
.ok{{color:#2ba640}}.err{{color:#ff6b6b}}</style></head><body>
<h2>{APP_TITLE}</h2>
<label>YouTube URL</label>
<input id="url" value="{uv}" placeholder="https://www.youtube.com/watch?v=...">
<button class="login" onclick="login()">Login to YouTube</button>
<button class="dl" onclick="download()">Download & Send</button>
<progress class="prog" id="prog" value="0" max="100"></progress>
<div class="status" id="status"><span style="color:#999">Paste a YouTube URL and click Download & Send.</span></div>
<script>
function login(){{window.open('https://www.youtube.com','_blank')}}
async function download(){{
const u=document.getElementById('url').value.trim();if(!u)return upd('Enter a YouTube URL',1);
upd('Downloading...');document.getElementById('prog').style.display='';
const r=await window.pywebview.api.download(u);
upd(r.message,r.ok?0:1);document.getElementById('prog').value=r.ok?100:0;
}}
function upd(m,e){{const el=document.getElementById('status');el.innerHTML=m.replace(/\\n/g,'<br>');el.className='status '+(e?'err':'ok');}}
</script></body></html>"""

    class Api:
        def __init__(self, p):
            self.p = p

        def download(self, url):
            ok, msg = self.p.do_download(url)
            return {"ok": ok, "message": msg}

    def run_gui(self):
        if not webview:
            print("Install pywebview: pip install pywebview", file=sys.stderr)
            sys.exit(1)
        api = self.Api(self)
        webview.create_window(
            APP_TITLE,
            html=self._html(),
            js_api=api,
            width=600,
            height=480,
            resizable=True,
        )
        webview.start()


def main():
    p = argparse.ArgumentParser(description="SongWalk YouTube Helper")
    p.add_argument("--server", required=True)
    p.add_argument("--library", required=True)
    p.add_argument("--url")
    p.add_argument("--headless", action="store_true")
    args = p.parse_args()
    app = SongWalkHelper(args.server, args.library, args.url)
    if args.headless and args.url:
        ok, msg = app.do_download(args.url)
        print(msg)
        sys.exit(0 if ok else 1)
    else:
        app.run_gui()


if __name__ == "__main__":
    main()
