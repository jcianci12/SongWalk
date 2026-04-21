<p align="center">
  <a href="https://github.com/jcianci12/SongWalk">
    <img src="songshare\images\Songwalk logo.png" alt="SongWalk logo" width="220">
  </a>
</p>

# SongWalk

SongWalk is a small self-hosted music dropbox with a shared UUID link per library.

The product branding is `SongWalk`. The current module names, commands, and environment variables still use the existing `songshare` and `SONGSHARE_*` identifiers.

## Quick Start

If you are on Windows and have the packaged desktop build, the shortest path is now:

1. Run `SongWalk.exe`.
2. Wait for the browser to open the owner dashboard.
3. Create a library and copy the share URL.
4. Send it.

The EXE starts the local server, brings Cloudflare Quick Tunnel online automatically, and opens the public owner page when it is reachable.

## Share First

SongWalk is built around one idea: EASILY spin it up, create a library, copy its share URL, and send it to someone immediately.

On Windows, the packaged EXE now does that directly. Run it, wait for the owner page to open, create a library, and share the resulting public link. Docker Compose still supports the same flow for non-desktop use.

- Anyone with the share URL can open that library.
- Anyone with the share URL can upload tracks and edit metadata in that library.
- The public landing page does not enumerate existing library IDs. This is only exposed to the person opening it locally - it is not exposed over cloudflare.
- Library management lives behind a separate private owner URL.

## A nod to windows media player (legacy)
Looks like windows media player (In my opinion the best version)

## Fast Public Exposure

For the fastest zero-account demo flow on Windows:

1. Run `SongWalk.exe`.
2. Wait for the owner dashboard to open.
3. Create a library.
4. Copy its share URL and send it.

For Docker instead:

1. Run `docker compose up --build`.
2. Open `http://localhost:8080/`.
3. Use the local launch page to bring SongWalk online, then copy the public `https://...trycloudflare.com` URL and send a library share link from there.

Quick Tunnels are temporary and for demos/testing only.

## Features

- Create and manage libraries from a private owner dashboard URL
- Upload audio files with drag and drop
- Import from YouTube and Spotify into any shared library
- Fill missing title, artist, and album tags from MusicBrainz after import
- Share the UUID-backed library URL with collaborators
- Edit track metadata such as title, artist, and album
- Stream tracks from the browser

## Run Locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m songshare
```

Open `http://localhost:8080`.

For YouTube and Spotify imports in a plain Python install, make sure `ffmpeg` is available on your `PATH`. The Python requirements install `yt-dlp` and `spotdl`; `ffmpeg` still needs to come from your OS package manager or a manual install.

## Desktop Build

For a local desktop executable, use the PyInstaller build path documented in [docs/desktop-packaging.md](docs/desktop-packaging.md).

To rebuild the Windows executable automatically while editing:

```powershell
.\build\pyinstaller\watch-windows.ps1
```

The packaged Windows app now runs as a tray app:

- turns Quick Tunnel on by default in the packaged desktop runtime unless you explicitly set `SONGSHARE_QUICK_TUNNEL_ENABLED=0`
- bundles `cloudflared.exe` next to `SongWalk.exe`, so the EXE can bring Cloudflare online without a separate machine-wide install
- opens the owner dashboard on startup, waiting for the public owner page to become reachable before falling back to `localhost`
- double-clicks to the owner dashboard, preferring the public tunnel URL over `localhost`
- right-click for `Open owner dashboard`, `Open SongWalk`, `Open data folder`, and `Quit SongWalk`
- when launched from the packaged build, `songshare-data/` defaults to a folder next to `SongWalk.exe` so the app stays portable

The built executable lives at:

```text
build/pyinstaller/dist/windows/SongWalk/SongWalk.exe
```

For a normal Windows first run, that EXE is now the recommended entry point.

If you open root directly on `localhost`, SongWalk now shows a local launch page with the owner dashboard link plus Quick Tunnel on/off controls and the current public host when it is online.

For public hosts, tunnels, and reverse proxies, root stays in share-access mode and does not reveal library IDs.

SongWalk also writes a private owner URL to `songshare-data/owner-url.txt` for library management access.

## Dev Mode

For automatic server restart and browser refresh while you edit Python, templates, CSS, or JS:

```powershell
$env:SONGSHARE_DEV="1"
python -m songshare
```

In dev mode SongWalk uses Flask's reloader, disables static asset caching, and refreshes open pages when watched files change.

## Configuration

- `SONGSHARE_HOST`: Bind host, default `0.0.0.0`
- `SONGSHARE_PORT`: Bind port, default `8080`
- `SONGSHARE_DATA_DIR`: Storage root, default `./songshare-data`
- `SONGSHARE_BASE_URL`: Optional public base URL used for share links
- `SONGSHARE_DEV`: Enable development auto-reload mode, default `off`
- `SONGSHARE_MAX_UPLOAD_MB`: Request size limit in MB, default `512`
- `SONGSHARE_PROXY_HOPS`: Number of trusted reverse proxies to honor for forwarded host/proto headers, default `0`
- `SONGSHARE_YOUTUBE_DL_BIN`: Optional override for the YouTube downloader command. Defaults to `yt-dlp` and falls back to `youtube-dl` if present.
- `SONGSHARE_SPOTIFY_DL_BIN`: Optional override for the Spotify downloader command. Defaults to `spotdl`.

## Docker

```powershell
docker compose up --build
```

The compose file mounts `./songshare-data` into the container at `/data`, enables one trusted proxy hop so nginx/Traefik/Caddy can forward the public host and scheme cleanly, and turns on the built-in Quick Tunnel manager by default.

For live-reload development inside Docker, use the dev override:

```powershell
docker compose -f compose.yaml -f compose.dev.yaml up --build
```

`compose.dev.yaml` enables `SONGSHARE_DEV=1`, keeps the Quick Tunnel manager enabled, and bind-mounts `./songshare` into `/app/songshare`, so Python, template, CSS, and JS edits are picked up without rebuilding the image each time.

The container image now includes `ffmpeg`, `yt-dlp`, and `spotdl`, so the `/import` page works inside Docker without extra setup.

## Owner Access

SongWalk separates public share access from owner management:

- Direct `http://localhost:8080/` shows a local-only launch page with owner access and Quick Tunnel controls.
- Public `/` is a neutral landing page that does not enumerate library IDs.
- `/s/<library-id>` is the shared library URL you send to collaborators.
- `/s/<library-id>/import` is the dedicated import page for drag-and-drop, YouTube URLs, and Spotify URLs.
- `/owner/<secret-token>` is the private owner dashboard for creating and deleting libraries.

On startup, SongWalk writes the private owner URL to `songshare-data/owner-url.txt`. Keep that URL private.

This local-only convenience is intentionally limited to direct loopback requests and does not activate through Cloudflare tunnels or public reverse proxies.

## Quick Sharing

### Cloudflare Quick Tunnel

Docker Compose starts a Quick Tunnel automatically now:

```powershell
docker compose up --build
```

Then open `http://localhost:8080/` locally. The launch page shows:

- The current public `https://...trycloudflare.com` URL
- The owner URL on that public host
- A button to bring SongWalk online or take it offline
- A button to rotate the tunnel

For the packaged Windows EXE, Quick Tunnel starts by default and the app opens the public owner page when it becomes reachable. For plain `python -m songshare`, Quick Tunnel startup is still optional. Install `cloudflared` yourself and set `SONGSHARE_QUICK_TUNNEL_ENABLED=1` if you want the same in-app behavior outside Docker.

Quick Tunnels are for testing and demos only. They are temporary, have a limit of 200 in-flight requests, and do not support Server-Sent Events.

Important: anyone with a shared library URL on that public host can access that library.

Stop the tunnel with:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\cloudflare\stop-quick-tunnel.ps1
```

Or:

```bash
docker rm -f songshare-cloudflared
```

### ngrok

`ngrok` is still a reasonable alternative, but it now requires an account and auth token for the standard localhost sharing flow. For the lowest-friction first run, Cloudflare Quick Tunnels are easier.

## Reverse Proxy (nginx)

If nginx terminates TLS and proxies traffic to SongWalk, keep `SONGSHARE_PROXY_HOPS=1` and forward the usual headers.

A ready-to-adapt example config is included at `deploy/nginx/songshare.conf`:

```nginx
server {
    listen 80;
    server_name music.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name music.example.com;

    ssl_certificate /etc/letsencrypt/live/music.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/music.example.com/privkey.pem;

    client_max_body_size 512m;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Port $server_port;
    }
}
```

In that setup, SongWalk can usually leave `SONGSHARE_BASE_URL` empty and derive the correct public share URL from forwarded headers. Set `SONGSHARE_BASE_URL` only if you want to force one canonical external URL.

If you are running the Windows executable or `python -m songshare` behind nginx instead of Docker, export the same proxy setting before launch:

```powershell
$env:SONGSHARE_PROXY_HOPS="1"
python -m songshare
```
