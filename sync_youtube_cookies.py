"""
SongWalk YouTube Cookie Sync
Extracts YouTube cookies from your browser, sends them to SongWalk.

Usage (test mode — prints cookies to terminal):
    python sync_youtube_cookies.py

Usage (upload to SongWalk):
    python sync_youtube_cookies.py http://localhost:8080

Usage (with token, for future admin integration):
    python sync_youtube_cookies.py http://localhost:8080 abc123-token

Requirements:
    - yt-dlp installed (pip install yt-dlp) — OR —
    - browser_cookie3 installed (pip install browser-cookie3)
    - At least one browser signed into YouTube (Chrome, Firefox, Edge, Brave)
"""

import os
import sys
import tempfile
from typing import Optional

BROWSERS = ("chrome", "firefox", "edge", "brave", "chromium", "opera")

YOUTUBE_DOMAINS = {".youtube.com", "youtube.com", ".www.youtube.com"}


# ---------------------------------------------------------------------------
# Method 1: yt-dlp --cookies-from-browser (preferred — handles encryption)
# ---------------------------------------------------------------------------


def _try_ytdlp(browser: str) -> Optional[str]:
    """Use yt-dlp to extract cookies from a browser profile."""
    import subprocess

    cookie_path = os.path.join(tempfile.gettempdir(), "SONGWALK_cookies_tmp.txt")
    try:
        result = subprocess.run(
            [
                "yt-dlp",
                "--cookies-from-browser",
                browser,
                "--cookies",
                cookie_path,
                "-s",  # simulate — don't download
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and os.path.getsize(cookie_path) > 100:
            with open(cookie_path, encoding="utf-8") as fh:
                return fh.read()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    finally:
        _try_remove(cookie_path)
    return None


# ---------------------------------------------------------------------------
# Method 2: browser_cookie3 (pure Python — no yt-dlp needed)
# ---------------------------------------------------------------------------


def _try_browser_cookie3(browser: str) -> Optional[str]:
    """Use browser_cookie3 to read cookies directly from browser SQLite DB."""
    try:
        import browser_cookie3
    except ImportError:
        return None

    loader = {
        "chrome": browser_cookie3.chrome,
        "firefox": browser_cookie3.firefox,
        "edge": browser_cookie3.edge,
        "brave": browser_cookie3.brave,
        "chromium": browser_cookie3.chromium,
        "opera": browser_cookie3.opera,
    }.get(browser)

    if loader is None:
        return None

    try:
        cj = loader()
    except Exception:
        return None

    # Filter to YouTube domains only
    youtube_cookies = [
        c
        for c in cj
        if c.domain in YOUTUBE_DOMAINS or c.domain.endswith(".youtube.com")
    ]
    if not youtube_cookies:
        return None

    lines = ["# Netscape HTTP Cookie File", "# Extracted by SongWalk cookie sync"]
    for c in youtube_cookies:
        domain = c.domain if c.domain.startswith(".") else f".{c.domain}"
        flag = "TRUE" if c.domain.startswith(".") else "FALSE"
        secure = "TRUE" if c.secure else "FALSE"
        expires = str(int(c.expires)) if c.expires else "0"
        lines.append(
            "\t".join(
                [
                    domain,
                    flag,
                    c.path or "/",
                    secure,
                    expires,
                    c.name or "",
                    c.value or "",
                ]
            )
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _try_remove(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _valid_cookies(text: str) -> bool:
    """Quick check: Netscape format starts with # comment, has tab-separated fields."""
    return bool(text) and text.startswith("#") and "\t" in text


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def upload_cookies(
    SONGWALK_url: str, cookies_text: str, token: Optional[str] = None
) -> bool:
    """POST cookies to SongWalk. Uses token endpoint if token provided, else file upload."""
    try:
        import requests
    except ImportError:
        print(
            "ERROR: 'requests' library not installed. Install with: pip install requests"
        )
        return False

    url = SONGWALK_url.rstrip("/")
    if token:
        endpoint = f"{url}/api/import/cookies/token/{token}"
        resp = requests.post(
            endpoint,
            data=cookies_text.encode("utf-8"),
            headers={"Content-Type": "text/plain; charset=utf-8"},
            timeout=15,
        )
    else:
        endpoint = f"{url}/api/import/cookies"
        resp = requests.post(
            endpoint,
            files={
                "cookies": ("cookies.txt", cookies_text.encode("utf-8"), "text/plain")
            },
            timeout=15,
        )

    if resp.status_code == 200:
        print(f"  -> Uploaded successfully ({len(cookies_text)} bytes)")
        return True
    else:
        try:
            msg = resp.json().get("error", resp.text)
        except Exception:
            msg = resp.text[:200]
        print(f"  -> Upload failed [{resp.status_code}]: {msg}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    SONGWALK_url = sys.argv[1] if len(sys.argv) > 1 else None
    token = sys.argv[2] if len(sys.argv) > 2 else None

    if SONGWALK_url and SONGWALK_url.startswith("http"):
        print(f"SongWalk: {SONGWALK_url}")
        if token:
            print(f"Token: {token}")
        print("Extracting YouTube cookies from browser...")
    else:
        print("=== SongWalk YouTube Cookie Sync (test mode) ===")
        print("Extracting cookies from browser...")

    # Try each browser
    for browser in BROWSERS:
        print(f"\n[{browser}] ", end="", flush=True)

        cookies = _try_ytdlp(browser)
        method = "yt-dlp"
        if cookies is None:
            cookies = _try_browser_cookie3(browser)
            method = "browser_cookie3"

        if cookies and _valid_cookies(cookies):
            print(f"Found YouTube cookies via {method}!")
            if SONGWALK_url and SONGWALK_url.startswith("http"):
                upload_cookies(SONGWALK_url, cookies, token)
            else:
                # Test mode: print first 600 chars
                preview = cookies[:600]
                print(f"\n--- cookies.txt preview ({len(cookies)} bytes) ---")
                print(preview)
                if len(cookies) > 600:
                    print("... (truncated)")
                print("--- end preview ---")
            return
        elif cookies:
            print(f"Found via {method} but no YouTube cookies in this browser.")
        else:
            print("No cookies found.")

    print("\nCould not extract YouTube cookies from any browser.")
    print("\nTroubleshooting:")
    print("  1. Make sure you're signed into YouTube in Chrome or Firefox.")
    print("  2. Install yt-dlp:  pip install yt-dlp")
    print("  3. Or install browser_cookie3:  pip install browser-cookie3")
    print("  4. Close the browser before running this script (avoids DB lock).")
    sys.exit(1)


if __name__ == "__main__":
    main()
