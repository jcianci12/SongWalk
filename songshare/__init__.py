from __future__ import annotations

import os
import secrets
import threading
import tempfile
import time
import zipfile
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, url_for
from itsdangerous import BadSignature, URLSafeSerializer
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

from .album_lookup import LookupError, MusicMetadataClient
from .importer import ImportError, ImportOutcome, ImportProgressUpdate, LibraryImportService
from .quick_tunnel import QuickTunnelManager, QuickTunnelStatus
from .store import CollectionNotFoundError, LibraryNotFoundError, Store, TrackNotFoundError, UploadedTrack


@dataclass
class ImportJob:
    id: str
    library_id: str
    source: str
    status: str = "queued"
    message: str = "Queued..."
    percent: int | None = None
    current_item: str = ""
    complete: bool = False
    ok: bool = False
    error: str = ""
    redirect_url: str = ""
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "library_id": self.library_id,
            "source": self.source,
            "status": self.status,
            "message": self.message,
            "percent": self.percent,
            "current_item": self.current_item,
            "complete": self.complete,
            "ok": self.ok,
            "error": self.error,
            "redirect_url": self.redirect_url,
            "updated_at": self.updated_at,
        }


class ImportJobStore:
    def __init__(self, *, ttl_seconds: float = 3600):
        self._ttl_seconds = ttl_seconds
        self._jobs: dict[str, ImportJob] = {}
        self._lock = threading.Lock()

    def create(self, *, library_id: str, source: str, message: str) -> ImportJob:
        with self._lock:
            self._prune_locked()
            job = ImportJob(
                id=str(uuid4()),
                library_id=library_id,
                source=source,
                message=message,
                updated_at=time.time(),
            )
            self._jobs[job.id] = job
            return job

    def update(self, job_id: str, **changes) -> ImportJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            for key, value in changes.items():
                setattr(job, key, value)
            job.updated_at = time.time()
            return job

    def finish(self, job_id: str, *, ok: bool, message: str, redirect_url: str = "", error: str = "") -> ImportJob | None:
        return self.update(
            job_id,
            status="complete" if ok else "error",
            message=message,
            percent=100 if ok else None,
            complete=True,
            ok=ok,
            error=error,
            redirect_url=redirect_url,
        )

    def get(self, job_id: str) -> ImportJob | None:
        with self._lock:
            self._prune_locked()
            return self._jobs.get(job_id)

    def latest_for_library(self, library_id: str) -> ImportJob | None:
        with self._lock:
            self._prune_locked()
            matches = [job for job in self._jobs.values() if job.library_id == library_id]
            if not matches:
                return None
            return max(matches, key=lambda job: job.updated_at)

    def _prune_locked(self) -> None:
        now = time.time()
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if job.complete and now - job.updated_at > self._ttl_seconds
        ]
        for job_id in expired:
            self._jobs.pop(job_id, None)


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")

    data_dir = Path(os.getenv("SONGSHARE_DATA_DIR", "./songshare-data"))
    max_upload_mb = int(os.getenv("SONGSHARE_MAX_UPLOAD_MB", "512"))
    proxy_hops = max(0, int(os.getenv("SONGSHARE_PROXY_HOPS", "0")))
    dev_mode = os.getenv("SONGSHARE_DEV", "").lower() in {"1", "true", "yes", "on"}

    app.config.from_mapping(
        DATA_DIR=data_dir,
        BASE_URL=os.getenv("SONGSHARE_BASE_URL", "").rstrip("/"),
        DEV_MODE=dev_mode,
        MAX_UPLOAD_MB=max_upload_mb,
        MAX_CONTENT_LENGTH=max_upload_mb * 1024 * 1024,
        PROXY_HOPS=proxy_hops,
        QUICK_TUNNEL_ENABLED=os.getenv("SONGSHARE_QUICK_TUNNEL_ENABLED", "").lower() in {"1", "true", "yes", "on"},
    )

    if test_config:
        app.config.update(test_config)

    app.config["DATA_DIR"] = Path(app.config["DATA_DIR"]).resolve()
    app.config["DATA_DIR"].mkdir(parents=True, exist_ok=True)
    app.config["TEMPLATES_AUTO_RELOAD"] = bool(app.config["DEV_MODE"])
    if app.config["DEV_MODE"]:
        app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    if app.config["PROXY_HOPS"]:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=app.config["PROXY_HOPS"],
            x_proto=app.config["PROXY_HOPS"],
            x_host=app.config["PROXY_HOPS"],
            x_port=app.config["PROXY_HOPS"],
            x_prefix=app.config["PROXY_HOPS"],
        )

    store = Store(Path(app.config["DATA_DIR"]))
    app.config["STORE"] = store
    app.config.setdefault("LOOKUP_CLIENT", MusicMetadataClient())
    app.config.setdefault("IMPORT_JOB_STORE", ImportJobStore())
    app.config.setdefault(
        "IMPORT_SERVICE",
        LibraryImportService(
            store=store,
            lookup_client=app.config["LOOKUP_CLIENT"],
            youtube_command=os.getenv("SONGSHARE_YOUTUBE_DL_BIN", "").strip() or None,
            spotify_command=os.getenv("SONGSHARE_SPOTIFY_DL_BIN", "").strip() or None,
            spotify_client_id=os.getenv("SONGSHARE_SPOTIFY_CLIENT_ID", "").strip() or None,
            spotify_client_secret=os.getenv("SONGSHARE_SPOTIFY_CLIENT_SECRET", "").strip() or None,
        ),
    )
    owner_token_path = app.config["DATA_DIR"] / "owner-token.txt"
    owner_token = os.getenv("SONGSHARE_OWNER_TOKEN", "").strip()
    if not owner_token:
        if owner_token_path.exists():
            owner_token = owner_token_path.read_text(encoding="utf-8").strip()
        else:
            owner_token = str(uuid4())
            owner_token_path.write_text(owner_token, encoding="utf-8")
    app.config["OWNER_TOKEN"] = owner_token
    app.config["OWNER_PATH"] = f"/owner/{owner_token}"
    app.config["OWNER_TOKEN_PATH"] = owner_token_path

    monitor = None
    if app.config["DEV_MODE"]:
        monitor = DevChangeMonitor(
            watched_roots=[
                Path(__file__).resolve().parent,
            ]
        )
        monitor.start()
        app.extensions["dev_change_monitor"] = monitor

    @app.context_processor
    def inject_dev_mode() -> dict:
        return {
            "dev_mode": bool(app.config["DEV_MODE"]),
            "local_access_mode": is_direct_local_request(),
        }

    @app.template_filter("filesize")
    def filesize_filter(size: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        amount = float(size)
        for unit in units:
            if amount < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(amount)} {unit}"
                return f"{amount:.1f} {unit}"
            amount /= 1024
        return f"{size} B"

    @app.template_filter("friendly_time")
    def friendly_time_filter(value) -> str:
        return value.strftime("%d %b %Y %H:%M")

    def base_url() -> str:
        configured = app.config["BASE_URL"]
        if configured:
            return configured
        return request.host_url.rstrip("/")

    def wants_json() -> bool:
        accept = request.headers.get("Accept", "")
        return "application/json" in accept or request.headers.get("X-Requested-With") == "fetch"

    def owner_path() -> str:
        return app.config["OWNER_PATH"]

    def owner_dashboard_url() -> str:
        return url_for("owner_home", owner_token=app.config["OWNER_TOKEN"])

    def owner_token_from_request() -> str:
        return (
            (request.view_args or {}).get("owner_token")
            or request.form.get("owner_token", "")
            or request.args.get("owner_token", "")
            or request.headers.get("X-Songshare-Owner-Token", "")
        )

    def is_direct_local_request() -> bool:
        host = (request.host or "").split(":", 1)[0].strip().lower().strip("[]")
        has_forwarded_headers = any(
            request.headers.get(header)
            for header in (
                "X-Forwarded-For",
                "X-Forwarded-Host",
                "X-Forwarded-Proto",
                "X-Forwarded-Port",
                "X-Forwarded-Prefix",
            )
        )
        return host in {"localhost", "127.0.0.1", "::1"} and not has_forwarded_headers

    def require_local_access() -> None:
        if not is_direct_local_request():
            abort(404)

    def quick_tunnel_manager() -> QuickTunnelManager | None:
        manager = app.extensions.get("quick_tunnel_manager")
        return manager if manager is not None and hasattr(manager, "status") else None

    def quick_tunnel_status() -> dict:
        manager = quick_tunnel_manager()
        if manager is not None:
            status = manager.status()
        else:
            status = QuickTunnelStatus(
                enabled=bool(app.config["QUICK_TUNNEL_ENABLED"]),
                available=False,
                running=False,
                public_url="",
                service_url="",
                message="Quick Tunnel is disabled.",
                last_error="",
            )
            if status.enabled:
                status.message = "Quick Tunnel has not started in this runtime yet."

        public_owner_url = ""
        if status.public_url:
            public_owner_url = f"{status.public_url}{owner_path()}"

        payload = status.to_dict()
        payload["public_owner_url"] = public_owner_url
        payload["owner_path"] = owner_path()
        payload["state_path"] = str(Path(app.config["DATA_DIR"]) / "quick-tunnel.json")
        return payload

    def require_owner_access() -> None:
        token = owner_token_from_request().strip()
        expected = app.config["OWNER_TOKEN"]
        if not token or not secrets.compare_digest(token, expected):
            abort(404)

    def move_target_serializer() -> URLSafeSerializer:
        return URLSafeSerializer(app.config["OWNER_TOKEN"], salt="songwalk-move-target")

    def encode_library_move_target(library_id: str) -> str:
        return move_target_serializer().dumps({"library_id": library_id})

    def decode_library_move_target(token: str) -> str:
        try:
            payload = move_target_serializer().loads(token)
        except BadSignature as exc:
            raise ValueError("Choose a valid destination library.") from exc
        return str(payload.get("library_id", "")).strip()

    def build_library_summaries() -> list[dict]:
        libraries = []
        for library in store.list_libraries():
            libraries.append(
                {
                    "id": library.id,
                    "name": library.name,
                    "display_name": library.display_name,
                    "move_label": library.name.strip() or "Untitled library",
                    "track_count": len(library.tracks),
                    "updated_at": library.updated_at,
                    "share_url": f"{base_url()}{url_for('view_library', library_id=library.id)}",
                    "browse_url": url_for("view_library", library_id=library.id),
                    "delete_url": url_for("delete_library", library_id=library.id, owner_token=app.config["OWNER_TOKEN"]),
                    "rename_url": url_for("rename_library", library_id=library.id, owner_token=app.config["OWNER_TOKEN"]),
                    "files_dir": store.library_files_dir(library.id),
                    "move_target": encode_library_move_target(library.id),
                }
            )
        return libraries

    def track_url(library_id: str, track_id: str) -> str:
        return url_for("stream_track", library_id=library_id, track_id=track_id)

    def cover_url(library_id: str, cover_art_name: str) -> str:
        return url_for("track_cover_art", library_id=library_id, cover_art_name=cover_art_name)

    def album_group_key(album_name: str, artist_name: str) -> str:
        return f"{album_name.strip().lower()}::{artist_name.strip().lower()}"

    def build_track_view(library_id: str, track, *, album_name: str, artist_name: str) -> dict:
        title = track.title or Path(track.original_name).stem
        return {
            "id": track.id,
            "title": title,
            "artist": artist_name,
            "album": album_name,
            "album_key": album_group_key(album_name, artist_name),
            "album_track_ids": [],
            "rating": track.rating,
            "original_name": track.original_name,
            "size": track.size,
            "updated_at": track.updated_at,
            "cover_url": cover_url(library_id, track.cover_art_name) if track.cover_art_name else "",
            "cover_initials": cover_initials(track.album or track.title or track.original_name),
            "search_value": f"{title} {artist_name} {album_name} {track.original_name}".strip(),
        }

    def archive_component(value: str, fallback: str) -> str:
        normalized = " ".join((value or "").split()).strip(" .")
        if not normalized:
            normalized = fallback

        safe_value = secure_filename(normalized).strip("._ ")
        return safe_value or fallback

    def archive_track_path(track, used_paths: set[str]) -> str:
        extension = Path(track.original_name or track.stored_name).suffix or Path(track.stored_name).suffix or ".bin"
        artist = archive_component(track.artist, "Unknown artist")
        album = archive_component(track.album, "Unknown album")
        title = archive_component(track.title or Path(track.original_name).stem, track.id)
        candidate = f"{artist}/{album}/{title}{extension}"
        counter = 2

        # Keep duplicate song names from overwriting each other inside the zip.
        while candidate.casefold() in used_paths:
            candidate = f"{artist}/{album}/{title} ({counter}){extension}"
            counter += 1

        used_paths.add(candidate.casefold())
        return candidate

    def build_album_groups(library):
        groups: OrderedDict[tuple[str, str], dict] = OrderedDict()

        for track in library.tracks:
            album_name = track.album.strip() or "Unknown album"
            artist_name = track.artist.strip() or "Unknown artist"
            key = (album_name.lower(), artist_name.lower())

            if key not in groups:
                groups[key] = {
                    "key": album_group_key(album_name, artist_name),
                    "name": album_name,
                    "artist": artist_name,
                    "cover_initials": cover_initials(album_name),
                    "cover_url": "",
                    "search_value": f"{album_name} {artist_name}",
                    "track_ids": [],
                    "tracks": [],
                }

            if track.cover_art_name and not groups[key]["cover_url"]:
                groups[key]["cover_url"] = cover_url(library.id, track.cover_art_name)

            track_view = build_track_view(library.id, track, album_name=album_name, artist_name=artist_name)
            groups[key]["tracks"].append(track_view)
            groups[key]["track_ids"].append(track_view["id"])
            groups[key]["search_value"] = (
                f"{groups[key]['search_value']} {track_view['search_value']}"
            ).strip()

        for group in groups.values():
            for index, track in enumerate(group["tracks"], start=1):
                track["number"] = index
                track["album_key"] = group["key"]
                track["album_track_ids"] = list(group["track_ids"])

        return list(groups.values())

    def parse_track_ids(raw_value) -> list[str]:
        if isinstance(raw_value, list):
            return [str(item).strip() for item in raw_value if str(item).strip()]
        return [item.strip() for item in str(raw_value or "").split(",") if item.strip()]

    def build_collection_groups(library, album_groups: list[dict]) -> tuple[list[dict], set[str]]:
        grouped_album_keys: set[str] = set()
        collections: list[dict] = []
        for stored_collection in library.collections:
            selected_track_ids = set(stored_collection.track_ids)
            albums = [group for group in album_groups if any(track_id in selected_track_ids for track_id in group["track_ids"])]
            if not albums:
                continue

            grouped_album_keys.update(album["key"] for album in albums)
            collections.append(
                {
                    "id": stored_collection.id,
                    "key": f"collection::{stored_collection.id}",
                    "name": stored_collection.name,
                    "artist": "",
                    "album_count": len(albums),
                    "track_count": sum(len(album["tracks"]) for album in albums),
                    "cover_url": next((album["cover_url"] for album in albums if album["cover_url"]), ""),
                    "cover_initials": cover_initials(stored_collection.name),
                    "search_value": " ".join(
                        [stored_collection.name, *[album["search_value"] for album in albums]]
                    ).strip(),
                    "albums": albums,
                }
            )

        return collections, grouped_album_keys

    def build_album_browser_entries(library, album_groups: list[dict]) -> tuple[list[dict], list[dict]]:
        collections, grouped_album_keys = build_collection_groups(library, album_groups)
        collection_by_first_key = {
            collection["albums"][0]["key"]: collection
            for collection in collections
            if collection["albums"]
        }
        entries: list[dict] = []

        for group in album_groups:
            if group["key"] in collection_by_first_key:
                entries.append({"kind": "collection", "collection": collection_by_first_key[group["key"]]})
                continue
            if group["key"] in grouped_album_keys:
                continue
            entries.append({"kind": "album", "album": group})

        return entries, collections

    def build_collection_album_lookup(collections: list[dict]) -> dict[str, dict]:
        return {
            album["key"]: collection
            for collection in collections
            for album in collection["albums"]
        }

    def cover_initials(album_name: str) -> str:
        words = [word[:1].upper() for word in album_name.split() if word]
        if not words:
            return "SS"
        return "".join(words[:2])

    def import_redirect_response(
        library_id: str,
        outcome,
        *,
        success_notice: str,
        empty_error: str,
        error_endpoint: str = "view_import",
    ):
        if wants_json():
            redirect_url = url_for("view_library", library_id=library_id)
            if outcome.ok:
                redirect_url = url_for("view_library", library_id=library_id, notice=success_notice)
            return (
                jsonify(
                    {
                        "ok": outcome.ok,
                        "uploaded": outcome.uploaded,
                        "errors": outcome.errors,
                        "redirect_url": redirect_url,
                    }
                ),
                200 if outcome.ok else 400,
            )

        if outcome.ok:
            return redirect(url_for("view_library", library_id=library_id, notice=success_notice))

        error = outcome.errors[0] if outcome.errors else empty_error
        return redirect(url_for(error_endpoint, library_id=library_id, error=error))

    def start_import_job(library_id: str, *, source: str, source_url: str) -> ImportJob:
        job_store: ImportJobStore = app.config["IMPORT_JOB_STORE"]
        job = job_store.create(
            library_id=library_id,
            source=source,
            message=f"Queued {source.title()} import...",
        )

        def progress(update: ImportProgressUpdate) -> None:
            job_store.update(
                job.id,
                status=update.phase,
                message=update.message,
                percent=update.percent,
                current_item=update.current_item,
            )

        def worker() -> None:
            try:
                progress(ImportProgressUpdate(phase="starting", message=f"Starting {source.title()} import..."))
                if source == "youtube":
                    outcome = app.config["IMPORT_SERVICE"].import_youtube_url(
                        library_id,
                        source_url,
                        progress_callback=progress,
                    )
                    notice = f"Imported {outcome.uploaded} track{'s' if outcome.uploaded != 1 else ''} from YouTube."
                elif source == "spotify":
                    outcome = app.config["IMPORT_SERVICE"].import_spotify_url(
                        library_id,
                        source_url,
                        progress_callback=progress,
                    )
                    notice = f"Imported {outcome.uploaded} track{'s' if outcome.uploaded != 1 else ''} from Spotify."
                else:
                    raise ImportError("Unsupported import source.")

                if not outcome.ok:
                    message = outcome.errors[0] if outcome.errors else "Import failed."
                    job_store.finish(job.id, ok=False, message=message, error=message)
                    return

                with app.test_request_context():
                    redirect_url = url_for("view_library", library_id=library_id, notice=notice)
                job_store.finish(job.id, ok=True, message=notice, redirect_url=redirect_url)
            except ImportError as exc:
                message = str(exc)
                job_store.finish(job.id, ok=False, message=message, error=message)
            except Exception:
                app.logger.exception("Import job %s failed unexpectedly.", job.id)
                message = "Import failed unexpectedly."
                job_store.finish(job.id, ok=False, message=message, error=message)

        threading.Thread(
            target=worker,
            name=f"songshare-import-{job.id}",
            daemon=True,
        ).start()
        return job

    def public_import_job_status_for_library(library_id: str) -> dict | None:
        job_store: ImportJobStore = app.config["IMPORT_JOB_STORE"]
        job = job_store.latest_for_library(library_id)
        if job is None:
            return None
        return {
            "id": job.id,
            "library_id": job.library_id,
            "source": job.source,
            "status": job.status,
            "message": job.message,
            "percent": job.percent,
            "current_item": job.current_item,
            "complete": job.complete,
            "ok": job.ok,
            "error": job.error,
            "updated_at": job.updated_at,
        }

    @app.get("/")
    def home():
        return render_template(
            "home.html",
            data_dir=app.config["DATA_DIR"],
            base_url=base_url(),
            owner_dashboard_url=owner_dashboard_url(),
            owner_path=owner_path(),
            quick_tunnel=quick_tunnel_status(),
        )

    @app.get("/owner/<owner_token>")
    def owner_home(owner_token: str):
        require_owner_access()
        return render_template(
            "owner_home.html",
            libraries=build_library_summaries(),
            data_dir=app.config["DATA_DIR"],
            owner_token=app.config["OWNER_TOKEN"],
            owner_path=owner_path(),
            quick_tunnel=quick_tunnel_status(),
        )

    @app.get("/quick-tunnel")
    def view_quick_tunnel_status():
        require_local_access()
        return jsonify({"ok": True, "tunnel": quick_tunnel_status()})

    @app.post("/quick-tunnel/rotate")
    def quick_tunnel_rotate():
        require_local_access()
        manager = quick_tunnel_manager()
        if manager is None:
            return jsonify({"ok": False, "error": "Quick Tunnel is not available in this runtime."}), 400
        status = manager.rotate(wait_seconds=20.0)
        payload = quick_tunnel_status()
        ok = bool(status.public_url) or bool(status.running)
        return jsonify({"ok": ok, "tunnel": payload, "error": "" if ok else payload["last_error"]}), 200 if ok else 500

    @app.post("/quick-tunnel/toggle")
    def quick_tunnel_toggle():
        require_local_access()
        manager = quick_tunnel_manager()
        if manager is None:
            return jsonify({"ok": False, "error": "Quick Tunnel is not available in this runtime."}), 400

        current = manager.status()
        if current.running:
            status = manager.stop()
            payload = quick_tunnel_status()
            return jsonify({"ok": True, "action": "stopped", "tunnel": payload, "error": ""})

        status = manager.start(wait_seconds=20.0)
        payload = quick_tunnel_status()
        ok = bool(status.public_url) or bool(status.running)
        return jsonify({"ok": ok, "action": "started" if ok else "failed", "tunnel": payload, "error": "" if ok else payload["last_error"]}), 200 if ok else 500

    @app.post("/libraries")
    def create_library():
        require_owner_access()
        library = store.create_library(name=request.form.get("name", ""))
        return redirect(
            url_for("view_library", library_id=library.id, notice="Library ready. Drop tracks into the queue.")
        )

    @app.post("/libraries/<library_id>/delete")
    def delete_library(library_id: str):
        require_owner_access()
        try:
            store.delete_library(library_id)
        except LibraryNotFoundError:
            abort(404)

        redirect_url = owner_dashboard_url()
        if wants_json():
            return jsonify({"ok": True, "redirect_url": redirect_url})
        return redirect(redirect_url)

    @app.post("/libraries/<library_id>/rename")
    def rename_library(library_id: str):
        require_owner_access()
        try:
            library = store.rename_library(library_id, name=request.form.get("name", ""))
        except LibraryNotFoundError:
            abort(404)

        if wants_json():
            return jsonify({"ok": True, "library": {"id": library.id, "name": library.name, "display_name": library.display_name}})
        return redirect(url_for("owner_home", owner_token=app.config["OWNER_TOKEN"]))

    @app.post("/s/<library_id>/collections")
    def create_collection(library_id: str):
        try:
            collection = store.create_collection(
                library_id,
                name=request.form.get("name", ""),
                track_ids=parse_track_ids(request.form.get("track_ids", "")),
            )
        except LibraryNotFoundError:
            abort(404)
        except ValueError as exc:
            return redirect(url_for("view_library", library_id=library_id, view="albums", error=str(exc)))

        if wants_json():
            return jsonify({"ok": True, "collection": {"id": collection.id, "name": collection.name}})
        return redirect(url_for("view_library", library_id=library_id, view="albums", notice=f"Collection {collection.name} created."))

    @app.post("/s/<library_id>/collections/add")
    def add_to_collection(library_id: str):
        try:
            collection = store.add_tracks_to_collection(
                library_id,
                request.form.get("collection_id", "").strip(),
                track_ids=parse_track_ids(request.form.get("track_ids", "")),
            )
        except (LibraryNotFoundError, CollectionNotFoundError):
            abort(404)
        except ValueError as exc:
            return redirect(url_for("view_library", library_id=library_id, view="albums", error=str(exc)))

        if wants_json():
            return jsonify({"ok": True, "collection": {"id": collection.id, "name": collection.name}})
        return redirect(url_for("view_library", library_id=library_id, view="albums", notice=f"Added albums to {collection.name}."))

    @app.post("/s/<library_id>/collections/remove")
    def remove_from_collections(library_id: str):
        try:
            removed = store.remove_tracks_from_collections(
                library_id,
                track_ids=parse_track_ids(request.form.get("track_ids", "")),
            )
        except LibraryNotFoundError:
            abort(404)

        if wants_json():
            return jsonify({"ok": True, "removed": removed})
        if removed:
            return redirect(url_for("view_library", library_id=library_id, view="albums", notice="Removed selected albums from collections."))
        return redirect(url_for("view_library", library_id=library_id, view="albums", error="Choose at least one album to ungroup."))

    @app.get("/s/<library_id>")
    def view_library(library_id: str):
        try:
            library = store.get_library(library_id)
        except LibraryNotFoundError:
            abort(404)

        view_mode = request.args.get("view", "tracks").strip().lower()
        if view_mode not in {"tracks", "albums"}:
            view_mode = "tracks"
        selected_album_key = request.args.get("album", "").strip().lower()

        album_groups = build_album_groups(library)
        album_browser_entries, collection_groups = build_album_browser_entries(library, album_groups)
        collection_album_lookup = build_collection_album_lookup(collection_groups)

        return render_template(
            "library.html",
            library=library,
            album_groups=album_groups,
            album_browser_entries=album_browser_entries,
            collection_groups=collection_groups,
            collection_album_lookup=collection_album_lookup,
            other_libraries=[entry for entry in build_library_summaries() if entry["id"] != library.id] if is_direct_local_request() else [],
            album_count=len(album_groups),
            share_url=f"{base_url()}{url_for('view_library', library_id=library.id)}",
            library_files_dir=store.library_files_dir(library.id),
            notice=request.args.get("notice", ""),
            error=request.args.get("error", ""),
            view_mode=view_mode,
            selected_album_key=selected_album_key,
            track_url=track_url,
        )

    @app.get("/s/<library_id>/state")
    def library_state(library_id: str):
        try:
            library = store.get_library(library_id)
        except LibraryNotFoundError:
            abort(404)

        latest_import = public_import_job_status_for_library(library_id)
        return jsonify(
            {
                "ok": True,
                "library": {
                    "id": library.id,
                    "track_count": len(library.tracks),
                    "updated_at": library.updated_at.isoformat(),
                },
                "import_job": latest_import,
                "import_active": bool(latest_import and not latest_import["complete"]),
            }
        )

    @app.get("/s/<library_id>/import")
    def view_import(library_id: str):
        try:
            library = store.get_library(library_id)
        except LibraryNotFoundError:
            abort(404)

        return render_template(
            "import.html",
            library=library,
            share_url=f"{base_url()}{url_for('view_library', library_id=library.id)}",
            library_files_dir=store.library_files_dir(library.id),
            notice=request.args.get("notice", ""),
            error=request.args.get("error", ""),
        )

    @app.get("/s/<library_id>/download")
    def download_library(library_id: str):
        try:
            library = store.get_library(library_id)
        except LibraryNotFoundError:
            abort(404)

        archive_file = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
        used_paths: set[str] = set()

        with zipfile.ZipFile(archive_file, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            if not library.tracks:
                archive.writestr("README.txt", "SongWalk library is empty.\n")

            for track in library.tracks:
                file_path = store.library_files_dir(library_id) / track.stored_name
                if not file_path.exists():
                    continue
                archive.write(file_path, arcname=archive_track_path(track, used_paths))

        archive_size = archive_file.tell()
        archive_file.seek(0)
        response = send_file(
            archive_file,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"songwalk-library-{library.id}.zip",
            max_age=0 if app.config["DEV_MODE"] else None,
        )
        response.content_length = archive_size
        response.call_on_close(archive_file.close)
        return response

    @app.get("/s/<library_id>/import/youtube/search")
    def search_youtube_import(library_id: str):
        try:
            store.get_library(library_id)
        except LibraryNotFoundError:
            abort(404)

        query = request.args.get("q", "").strip()
        try:
            results = app.config["IMPORT_SERVICE"].search_youtube(query)
        except ImportError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        return jsonify({"ok": True, "results": results})

    @app.get("/s/<library_id>/import/spotify/search")
    def search_spotify_import(library_id: str):
        try:
            store.get_library(library_id)
        except LibraryNotFoundError:
            abort(404)

        query = request.args.get("q", "").strip()
        try:
            results = app.config["IMPORT_SERVICE"].search_spotify(query)
        except ImportError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        return jsonify({"ok": True, "results": results})

    @app.get("/s/<library_id>/import/jobs/<job_id>")
    def import_job_status(library_id: str, job_id: str):
        try:
            store.get_library(library_id)
        except LibraryNotFoundError:
            abort(404)

        job_store: ImportJobStore = app.config["IMPORT_JOB_STORE"]
        job = job_store.get(job_id)
        if not job or job.library_id != library_id:
            abort(404)

        return jsonify({"ok": True, "job": job.to_dict()})

    @app.post("/s/<library_id>/upload")
    def upload_tracks(library_id: str):
        try:
            store.get_library(library_id)
        except LibraryNotFoundError:
            abort(404)

        files = [file for file in request.files.getlist("tracks") if file and file.filename]
        if not files:
            message = "Choose at least one audio file."
            if wants_json():
                return jsonify({"ok": False, "error": message}), 400
            return redirect(url_for("view_library", library_id=library_id, error=message))

        uploads = [
            UploadedTrack(
                filename=file.filename,
                content_type=file.content_type or "",
                stream=file.stream,
                size=file.content_length,
            )
            for file in files
        ]

        try:
            outcome = app.config["IMPORT_SERVICE"].import_uploaded_files(library_id, uploads)
        finally:
            for file in files:
                file.close()

        notice = f"Imported {outcome.uploaded} track{'s' if outcome.uploaded != 1 else ''}."
        return import_redirect_response(
            library_id,
            outcome,
            success_notice=notice,
            empty_error="Upload failed.",
            error_endpoint="view_import" if request.args.get("next", "").strip().lower() == "import" else "view_library",
        )

    @app.post("/s/<library_id>/import/<source>")
    def import_source(library_id: str, source: str):
        try:
            store.get_library(library_id)
        except LibraryNotFoundError:
            abort(404)

        source_url = request.form.get("source_url", "").strip()
        if wants_json():
            if source not in {"youtube", "spotify"}:
                abort(404)
            if not source_url:
                return jsonify({"ok": False, "error": "Paste a valid source URL."}), 400

            job = start_import_job(library_id, source=source, source_url=source_url)
            return jsonify(
                {
                    "ok": True,
                    "job_id": job.id,
                    "status_url": url_for("import_job_status", library_id=library_id, job_id=job.id),
                }
            )

        try:
            if source == "youtube":
                outcome = app.config["IMPORT_SERVICE"].import_youtube_url(library_id, source_url)
                notice = f"Imported {outcome.uploaded} track{'s' if outcome.uploaded != 1 else ''} from YouTube."
            elif source == "spotify":
                outcome = app.config["IMPORT_SERVICE"].import_spotify_url(library_id, source_url)
                notice = f"Imported {outcome.uploaded} track{'s' if outcome.uploaded != 1 else ''} from Spotify."
            else:
                abort(404)
        except ImportError as exc:
            outcome = ImportOutcome(errors=[str(exc)])
            notice = ""

        return import_redirect_response(
            library_id,
            outcome,
            success_notice=notice,
            empty_error="Import failed.",
        )

    @app.post("/s/<library_id>/tracks/<track_id>")
    def update_track(library_id: str, track_id: str):
        try:
            store.update_track(
                library_id,
                track_id,
                title=request.form.get("title", ""),
                artist=request.form.get("artist", ""),
                album=request.form.get("album", ""),
                rating=request.form.get("rating", "0"),
            )
        except (LibraryNotFoundError, TrackNotFoundError):
            abort(404)

        if wants_json():
            return jsonify({"ok": True})

        return redirect(url_for("view_library", library_id=library_id, notice="Track details saved."))

    @app.post("/s/<library_id>/tracks/<track_id>/delete")
    def delete_track(library_id: str, track_id: str):
        try:
            store.delete_track(library_id, track_id)
        except (LibraryNotFoundError, TrackNotFoundError):
            abort(404)

        if wants_json():
            return jsonify({"ok": True})

        return redirect(url_for("view_library", library_id=library_id, notice="Track removed."))

    @app.post("/s/<library_id>/tracks/<track_id>/rating")
    def set_track_rating(library_id: str, track_id: str):
        payload = request.get_json(silent=True) or {}
        rating = payload.get("rating", request.form.get("rating", "0"))

        try:
            track = store.set_track_rating(library_id, track_id, rating=rating)
        except (LibraryNotFoundError, TrackNotFoundError):
            abort(404)

        return jsonify({"ok": True, "track": {"id": track.id, "rating": track.rating}})

    @app.post("/s/<library_id>/tracks/move")
    def move_tracks(library_id: str):
        payload = request.get_json(silent=True) or {}
        track_ids = payload.get("track_ids", [])
        album = str(payload.get("album", "")).strip()
        artist = str(payload.get("artist", "")).strip()

        if not isinstance(track_ids, list):
            return jsonify({"ok": False, "error": "track_ids must be a list."}), 400
        if not album or not artist:
            return jsonify({"ok": False, "error": "Target album and artist are required."}), 400

        try:
            moved_tracks = store.move_tracks_to_album(
                library_id,
                [str(track_id) for track_id in track_ids],
                album=album,
                artist=artist,
            )
        except (LibraryNotFoundError, TrackNotFoundError):
            abort(404)

        target_album_key = album_group_key(album, artist)
        notice = f"Moved {len(moved_tracks)} track{'s' if len(moved_tracks) != 1 else ''} to {album}."

        if wants_json():
            return jsonify(
                {
                    "ok": True,
                    "moved": len(moved_tracks),
                    "album": album,
                    "artist": artist,
                    "target_album_key": target_album_key,
                }
            )

        return redirect(url_for("view_library", library_id=library_id, view="tracks", album=target_album_key, notice=notice))

    @app.post("/s/<library_id>/tracks/<track_id>/move-library")
    def move_track_to_library(library_id: str, track_id: str):
        require_local_access()
        payload = request.get_json(silent=True) or {}
        target_library_id = str(payload.get("target_library_id", request.form.get("target_library_id", ""))).strip()
        if not target_library_id:
            target_token = str(payload.get("target_library_token", request.form.get("target_library_token", ""))).strip()
            if target_token:
                try:
                    target_library_id = decode_library_move_target(target_token)
                except ValueError as exc:
                    return jsonify({"ok": False, "error": str(exc)}), 400
        if not target_library_id:
            return jsonify({"ok": False, "error": "Choose a destination library."}), 400

        try:
            moved_track = store.move_track_to_library(
                library_id,
                track_id,
                target_library_id=target_library_id,
            )
            target_library = store.get_library(target_library_id)
        except (LibraryNotFoundError, TrackNotFoundError):
            abort(404)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        redirect_url = url_for(
            "view_library",
            library_id=target_library_id,
            notice=f"Moved {moved_track.title or moved_track.original_name} to {target_library.display_name}.",
        )

        if wants_json():
            return jsonify(
                {
                    "ok": True,
                    "track": {"id": moved_track.id, "title": moved_track.title, "album": moved_track.album},
                    "target_library": {"id": target_library.id, "display_name": target_library.display_name},
                    "redirect_url": redirect_url,
                }
            )

        return redirect(redirect_url)

    @app.post("/s/<library_id>/tracks/delete")
    def delete_tracks(library_id: str):
        payload = request.get_json(silent=True) or {}
        track_ids = payload.get("track_ids", [])
        if not isinstance(track_ids, list):
            return jsonify({"ok": False, "error": "track_ids must be a list."}), 400

        try:
            deleted = store.delete_tracks(library_id, [str(track_id) for track_id in track_ids])
        except (LibraryNotFoundError, TrackNotFoundError):
            abort(404)

        if wants_json():
            return jsonify({"ok": True, "deleted": deleted})

        notice = f"Removed {deleted} track{'s' if deleted != 1 else ''}."
        return redirect(url_for("view_library", library_id=library_id, notice=notice))

    @app.get("/s/<library_id>/tracks/<track_id>/file")
    def stream_track(library_id: str, track_id: str):
        try:
            track, file_path = store.get_track_file(library_id, track_id)
        except (LibraryNotFoundError, TrackNotFoundError):
            abort(404)

        return send_file(
            file_path,
            mimetype=track.content_type,
            download_name=track.original_name,
            as_attachment=False,
            conditional=True,
        )

    @app.get("/s/<library_id>/covers/<cover_art_name>")
    def track_cover_art(library_id: str, cover_art_name: str):
        try:
            store.get_library(library_id)
        except LibraryNotFoundError:
            abort(404)

        cover_path = store.cover_art_path(library_id, cover_art_name)
        if not cover_path.exists():
            abort(404)

        return send_file(cover_path, conditional=True, max_age=0 if app.config["DEV_MODE"] else None)

    @app.get("/s/<library_id>/tracks/<track_id>/lookup")
    def lookup_track_album_info(library_id: str, track_id: str):
        try:
            track = store.get_track(library_id, track_id)
        except (LibraryNotFoundError, TrackNotFoundError):
            abort(404)

        title = request.args.get("title", track.title or Path(track.original_name).stem)
        artist = request.args.get("artist", track.artist)
        album = request.args.get("album", track.album)

        try:
            candidates = app.config["LOOKUP_CLIENT"].search_release_candidates(
                title=title,
                artist=artist,
                album=album,
            )
        except LookupError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        return jsonify(
            {
                "ok": True,
                "query": {
                    "title": title,
                    "artist": artist,
                    "album": album,
                },
                "candidates": [candidate.to_dict() for candidate in candidates],
            }
        )

    @app.post("/s/<library_id>/tracks/<track_id>/lookup/apply")
    def apply_track_album_info(library_id: str, track_id: str):
        payload = request.get_json(silent=True) or {}
        release_id = str(payload.get("release_id", "")).strip()
        release_group_id = str(payload.get("release_group_id", "")).strip()
        title = str(payload.get("title", "")).strip()
        artist = str(payload.get("artist", "")).strip()
        album = str(payload.get("album", "")).strip()

        if not release_id and not release_group_id:
            return jsonify({"ok": False, "error": "Missing MusicBrainz identifiers."}), 400

        if not any([title, artist, album]):
            return jsonify({"ok": False, "error": "Missing track metadata to apply."}), 400

        try:
            cover_bytes, cover_extension = app.config["LOOKUP_CLIENT"].fetch_cover_art(
                release_id=release_id,
                release_group_id=release_group_id,
            )
            updated_track = store.apply_album_info(
                library_id,
                track_id,
                title=title,
                artist=artist,
                album=album,
                musicbrainz_release_id=release_id,
                musicbrainz_release_group_id=release_group_id,
                cover_art_bytes=cover_bytes,
                cover_art_extension=cover_extension,
            )
        except LookupError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except (LibraryNotFoundError, TrackNotFoundError):
            abort(404)

        return jsonify(
            {
                "ok": True,
                "track": {
                    "id": updated_track.id,
                    "title": updated_track.title,
                    "artist": updated_track.artist,
                    "album": updated_track.album,
                    "cover_url": cover_url(library_id, updated_track.cover_art_name) if updated_track.cover_art_name else "",
                },
            }
        )

    @app.get("/healthz")
    def healthcheck():
        return {"ok": True}

    @app.get("/__dev/reload-token")
    def dev_reload_token():
        if not app.config["DEV_MODE"]:
            abort(404)
        return {"token": monitor.token if monitor else 0}

    return app


class DevChangeMonitor:
    def __init__(self, watched_roots: list[Path], interval_seconds: float = 1.0):
        self._watched_roots = watched_roots
        self._interval_seconds = interval_seconds
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._snapshot = self._scan()
        self.token = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._thread = threading.Thread(target=self._watch_loop, name="songshare-dev-watch", daemon=True)
        self._thread.start()

    def _watch_loop(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            current = self._scan()
            if current != self._snapshot:
                self._snapshot = current
                self.token += 1

    def _scan(self) -> dict[str, int]:
        snapshot: dict[str, int] = {}
        for root in self._watched_roots:
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix not in {".py", ".html", ".css", ".js"}:
                    continue
                try:
                    snapshot[str(path)] = path.stat().st_mtime_ns
                except FileNotFoundError:
                    continue
        return snapshot
