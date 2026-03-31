from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass


class LookupError(RuntimeError):
    pass


@dataclass
class LookupCandidate:
    release_id: str
    release_group_id: str
    title: str
    artist: str
    date: str
    country: str
    track_title: str
    cover_art_url: str = ""

    def to_dict(self) -> dict:
        return {
            "release_id": self.release_id,
            "release_group_id": self.release_group_id,
            "title": self.title,
            "artist": self.artist,
            "date": self.date,
            "country": self.country,
            "track_title": self.track_title,
            "cover_art_url": self.cover_art_url,
        }


class MusicMetadataClient:
    api_root = "https://musicbrainz.org/ws/2"
    cover_art_root = "https://coverartarchive.org"

    def __init__(self, user_agent: str = "Songshare/0.1 ( https://localhost )"):
        self._user_agent = user_agent
        self._lock = threading.Lock()
        self._last_request_at = 0.0

    def search_release_candidates(
        self,
        *,
        title: str,
        artist: str,
        album: str,
        limit: int = 5,
    ) -> list[LookupCandidate]:
        query = self._build_release_query(title=title, artist=artist, album=album)
        url = f"{self.api_root}/release/?query={urllib.parse.quote(query)}&fmt=json&limit={limit}"
        payload = self._get_json(url)
        candidates: list[LookupCandidate] = []

        for release in payload.get("releases", []):
            artist_credit = release.get("artist-credit", [])
            artist_name = "".join(
                part.get("name", "") if isinstance(part, dict) else str(part)
                for part in artist_credit
            ).strip() or artist or "Unknown artist"
            release_group = release.get("release-group", {}) or {}
            media = release.get("media", []) or []
            track_title = title
            if media and isinstance(media[0], dict):
                tracks = media[0].get("tracks", []) or []
                if tracks and isinstance(tracks[0], dict):
                    track_title = tracks[0].get("title", track_title) or track_title

            release_id = release.get("id", "")
            release_group_id = release_group.get("id", "")
            cover_art_url = ""
            if release_group_id:
                cover_art_url = f"{self.cover_art_root}/release-group/{release_group_id}/front-250"
            elif release_id:
                cover_art_url = f"{self.cover_art_root}/release/{release_id}/front-250"

            candidates.append(
                LookupCandidate(
                    release_id=release_id,
                    release_group_id=release_group_id,
                    title=release.get("title", album or "Unknown album"),
                    artist=artist_name,
                    date=release.get("date", ""),
                    country=release.get("country", ""),
                    track_title=track_title,
                    cover_art_url=cover_art_url,
                )
            )

        return candidates

    def fetch_cover_art(self, *, release_id: str, release_group_id: str) -> tuple[bytes | None, str]:
        urls = []
        if release_group_id:
            urls.append(f"{self.cover_art_root}/release-group/{release_group_id}/front")
        if release_id:
            urls.append(f"{self.cover_art_root}/release/{release_id}/front")

        for url in urls:
            try:
                data, content_type, final_url = self._get_bytes(url)
                return data, _guess_extension(content_type, final_url)
            except LookupError:
                continue

        return None, ".jpg"

    def _build_release_query(self, *, title: str, artist: str, album: str) -> str:
        clauses: list[str] = []
        if album.strip():
            clauses.append(f'release:"{album.strip()}"')
        if artist.strip():
            clauses.append(f'artist:"{artist.strip()}"')
        if title.strip():
            clauses.append(f'recording:"{title.strip()}"')
        if not clauses:
            raise LookupError("Track metadata is too sparse to search for album info.")
        return " AND ".join(clauses)

    def _get_json(self, url: str) -> dict:
        data, _, _ = self._get_bytes(url)
        try:
            return json.loads(data.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise LookupError("Lookup service returned invalid JSON.") from exc

    def _get_bytes(self, url: str) -> tuple[bytes, str, str]:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json, image/*;q=0.9, */*;q=0.8",
                "User-Agent": self._user_agent,
            },
        )
        self._throttle()
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.read(), response.headers.get_content_type(), response.geturl()
        except Exception as exc:
            raise LookupError(str(exc)) from exc

    def _throttle(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait_for = 1.05 - (now - self._last_request_at)
            if wait_for > 0:
                time.sleep(wait_for)
            self._last_request_at = time.monotonic()


def _guess_extension(content_type: str, url: str) -> str:
    if content_type == "image/png":
        return ".png"
    if content_type == "image/webp":
        return ".webp"
    if ".png" in url.lower():
        return ".png"
    if ".webp" in url.lower():
        return ".webp"
    return ".jpg"
