<p align="center">
  <a href="https://github.com/jcianci12/SongWalk">
    <img src="songshare\images\Songwalk logo.png" alt="SongWalk logo" width="220">
  </a>
</p>

# SongWalk

SongWalk is a small self-hosted music dropbox with a shared UUID link per library.

The product branding is `SongWalk`. The current module names, commands, and environment variables still use the existing `songshare` and `SONGSHARE_*` identifiers.

## Share First

SongWalk is built around one idea: EASILY spin it up, create a library, copy its share URL, and send it to someone immediately.

Really easy to use. Run the included scripts (quick-share.ps1) and you will have a public facing url in no time that you can share with friends! Python or docker is needed. (future feature one simple exe to run perhaps?)

- Anyone with the share URL can open that library.
- Anyone with the share URL can upload tracks and edit metadata in that library.
- The public landing page does not enumerate existing library IDs. This is only exposed to the person opening it locally - it is not exposed over cloudflare.
- Library management lives behind a separate private owner URL.

## A nod to windows media player (legacy)
Looks like windows media player (In my opinion the best version)

## Fast Public Exposure

For the fastest zero-account demo flow:

1. Run the quick-share launcher.
2. Choose whether SongWalk should run in Docker or Python.
3. Copy the printed public URL and send a library share link from there.

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\quick-share.ps1
```

On Linux/macOS shells:

```bash
bash ./deploy/quick-share.sh
```

The launcher starts SongWalk, waits for it to respond, starts a Cloudflare Quick Tunnel, and prints:

- The local URL
- The public `https://...trycloudflare.com` URL
- The private owner URL on that public host

Quick Tunnels are temporary and for demos/testing only.

## Features

- Create and manage libraries from a private owner dashboard URL
- Upload audio files with drag and drop
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

If you open root directly on `localhost`, SongWalk will send you to the private owner dashboard automatically for convenience.

For public hosts, tunnels, and reverse proxies, root stays in share-access mode and does not reveal library IDs.

SongWalk also writes a private owner URL to `songshare-data/owner-url.txt` and prints it on startup for library management access.

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

## Docker

```powershell
docker compose up --build
```

The compose file mounts `./songshare-data` into the container at `/data` and enables one trusted proxy hop so nginx/Traefik/Caddy can forward the public host and scheme cleanly.

For live-reload development inside Docker, use the dev override:

```powershell
docker compose -f compose.yaml -f compose.dev.yaml up --build
```

`compose.dev.yaml` enables `SONGSHARE_DEV=1` and bind-mounts `./songshare` into `/app/songshare`, so Python, template, CSS, and JS edits are picked up without rebuilding the image each time.

## Owner Access

SongWalk separates public share access from owner management:

- Direct `http://localhost:8080/` redirects to the owner dashboard for convenience.
- Public `/` is a neutral landing page that does not enumerate library IDs.
- `/s/<library-id>` is the shared library URL you send to collaborators.
- `/owner/<secret-token>` is the private owner dashboard for creating and deleting libraries.

On startup, SongWalk writes the private owner URL to `songshare-data/owner-url.txt`. Keep that URL private.

This local-only convenience is intentionally limited to direct loopback requests and does not activate through Cloudflare tunnels or public reverse proxies.

## Quick Sharing

### Cloudflare Quick Tunnel

For a temporary public URL without creating a Cloudflare account, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\quick-share.ps1
```

This script prompts for `docker` or `python`, checks the required tools, starts SongWalk if needed, waits for it to become reachable, then launches a Dockerized `cloudflared` Quick Tunnel and prints a random `https://...trycloudflare.com` URL you can share immediately.

If you prefer Bash:

```bash
bash ./deploy/quick-share.sh
```

In `python` mode, SongWalk runs locally and the tunnel still uses Docker for `cloudflared`, so Docker is still required.

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
