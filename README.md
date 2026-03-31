# Songshare

Songshare is a small self-hosted music dropbox with a shared UUID link per library.

## Features

- Create a shared library from the home screen
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

## Dev Mode

For automatic server restart and browser refresh while you edit Python, templates, CSS, or JS:

```powershell
$env:SONGSHARE_DEV="1"
python -m songshare
```

In dev mode Songshare uses Flask's reloader, disables static asset caching, and refreshes open pages when watched files change.

## Configuration

- `SONGSHARE_HOST`: Bind host, default `0.0.0.0`
- `SONGSHARE_PORT`: Bind port, default `8080`
- `SONGSHARE_DATA_DIR`: Storage root, default `./songshare-data`
- `SONGSHARE_BASE_URL`: Optional public base URL used for share links
- `SONGSHARE_DEV`: Enable development auto-reload mode, default `off`
- `SONGSHARE_MAX_UPLOAD_MB`: Request size limit in MB, default `512`

## Docker

```powershell
docker compose up --build
```

The compose file mounts `./songshare-data` into the container at `/data`.
