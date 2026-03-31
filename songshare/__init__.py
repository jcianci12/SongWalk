from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, url_for

from .album_lookup import LookupError, MusicMetadataClient
from .store import LibraryNotFoundError, Store, TrackNotFoundError, UploadedTrack


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")

    data_dir = Path(os.getenv("SONGSHARE_DATA_DIR", "./songshare-data"))
    max_upload_mb = int(os.getenv("SONGSHARE_MAX_UPLOAD_MB", "512"))
    dev_mode = os.getenv("SONGSHARE_DEV", "").lower() in {"1", "true", "yes", "on"}

    app.config.from_mapping(
        DATA_DIR=data_dir,
        BASE_URL=os.getenv("SONGSHARE_BASE_URL", "").rstrip("/"),
        DEV_MODE=dev_mode,
        MAX_UPLOAD_MB=max_upload_mb,
        MAX_CONTENT_LENGTH=max_upload_mb * 1024 * 1024,
    )

    if test_config:
        app.config.update(test_config)

    app.config["DATA_DIR"] = Path(app.config["DATA_DIR"]).resolve()
    app.config["TEMPLATES_AUTO_RELOAD"] = bool(app.config["DEV_MODE"])
    if app.config["DEV_MODE"]:
        app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    store = Store(Path(app.config["DATA_DIR"]))
    app.config["STORE"] = store
    app.config.setdefault("LOOKUP_CLIENT", MusicMetadataClient())

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

    def track_url(library_id: str, track_id: str) -> str:
        return url_for("stream_track", library_id=library_id, track_id=track_id)

    def cover_url(library_id: str, cover_art_name: str) -> str:
        return url_for("track_cover_art", library_id=library_id, cover_art_name=cover_art_name)

    def build_album_groups(library):
        groups: OrderedDict[tuple[str, str], dict] = OrderedDict()

        for track in library.tracks:
            album_name = track.album.strip() or "Unknown album"
            artist_name = track.artist.strip() or "Unknown artist"
            key = (album_name.lower(), artist_name.lower())

            if key not in groups:
                groups[key] = {
                    "name": album_name,
                    "artist": artist_name,
                    "cover_initials": cover_initials(album_name),
                    "cover_url": "",
                    "search_value": f"{album_name} {artist_name}",
                    "tracks": [],
                }

            if track.cover_art_name and not groups[key]["cover_url"]:
                groups[key]["cover_url"] = cover_url(library.id, track.cover_art_name)

            groups[key]["tracks"].append(
                {
                    "id": track.id,
                    "title": track.title or Path(track.original_name).stem,
                    "artist": artist_name,
                    "album": album_name,
                    "rating": track.rating,
                    "original_name": track.original_name,
                    "size": track.size,
                    "updated_at": track.updated_at,
                    "cover_url": cover_url(library.id, track.cover_art_name) if track.cover_art_name else "",
                    "cover_initials": cover_initials(track.album or track.title or track.original_name),
                }
            )
            groups[key]["search_value"] = (
                f"{groups[key]['search_value']} {track.title} {track.original_name}"
            ).strip()

        for group in groups.values():
            for index, track in enumerate(group["tracks"], start=1):
                track["number"] = index

        return list(groups.values())

    def cover_initials(album_name: str) -> str:
        words = [word[:1].upper() for word in album_name.split() if word]
        if not words:
            return "SS"
        return "".join(words[:2])

    @app.get("/")
    def home():
        libraries = []
        for library in store.list_libraries():
            libraries.append(
                {
                    "id": library.id,
                    "track_count": len(library.tracks),
                    "updated_at": library.updated_at,
                    "share_url": f"{base_url()}{url_for('view_library', library_id=library.id)}",
                    "browse_url": url_for("view_library", library_id=library.id),
                    "files_dir": store.library_files_dir(library.id),
                }
            )

        return render_template(
            "home.html",
            libraries=libraries,
            data_dir=app.config["DATA_DIR"],
            base_url=base_url(),
        )

    @app.post("/libraries")
    def create_library():
        library = store.create_library()
        return redirect(
            url_for("view_library", library_id=library.id, notice="Library ready. Drop tracks into the queue.")
        )

    @app.get("/s/<library_id>")
    def view_library(library_id: str):
        try:
            library = store.get_library(library_id)
        except LibraryNotFoundError:
            abort(404)

        view_mode = request.args.get("view", "tracks").strip().lower()
        if view_mode not in {"tracks", "albums"}:
            view_mode = "tracks"

        album_groups = build_album_groups(library)

        libraries = []
        for item in store.list_libraries():
            libraries.append(
                {
                    "id": item.id,
                    "browse_url": url_for("view_library", library_id=item.id),
                }
            )

        return render_template(
            "library.html",
            library=library,
            album_groups=album_groups,
            album_count=len(album_groups),
            libraries=libraries,
            other_libraries=[item for item in libraries if item["id"] != library.id],
            share_url=f"{base_url()}{url_for('view_library', library_id=library.id)}",
            library_files_dir=store.library_files_dir(library.id),
            notice=request.args.get("notice", ""),
            error=request.args.get("error", ""),
            view_mode=view_mode,
            track_url=track_url,
        )

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

        uploaded = 0
        errors = []

        for file in files:
            try:
                store.add_track(
                    library_id,
                    UploadedTrack(
                        filename=file.filename,
                        content_type=file.content_type or "",
                        stream=file.stream,
                        size=file.content_length,
                    ),
                )
                uploaded += 1
            except ValueError as exc:
                errors.append(str(exc))
            finally:
                file.close()

        if wants_json():
            status = 200 if uploaded else 400
            return jsonify({"ok": uploaded > 0, "uploaded": uploaded, "errors": errors}), status

        if uploaded:
            notice = f"Uploaded {uploaded} track{'s' if uploaded != 1 else ''}."
            return redirect(url_for("view_library", library_id=library_id, notice=notice))

        error = errors[0] if errors else "Upload failed."
        return redirect(url_for("view_library", library_id=library_id, error=error))

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
