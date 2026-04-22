from __future__ import annotations

import json
import re
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
    max_release_lookups_floor = 8

    def __init__(self, user_agent: str = "SongWalk/0.1 ( https://localhost )"):
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
        self._validate_search_inputs(title=title, artist=artist, album=album)

        searches: list[tuple[str, str, int, bool]] = []
        if album.strip() and artist.strip():
            searches.append(("release", self._build_release_query(artist=artist, album=album), max(limit * 2, 8), False))
        if artist.strip() and title.strip():
            searches.append(("recording", self._build_recording_query(artist=artist, title=title), max(limit * 2, 8), False))
            searches.append(
                ("recording", self._build_recording_fallback_query(artist=artist, title=title), max(limit * 2, 8), True)
            )
        if album.strip():
            searches.append(("release", f'release:"{album.strip()}"', max(limit * 2, 8), False))

        seen_release_ids: set[str] = set()
        candidates: list[tuple[int, LookupCandidate]] = []
        strict_recording_found = False
        remaining_release_lookups = max(self.max_release_lookups_floor, limit * 4)

        for search_type, query, query_limit, fallback_only in searches:
            if fallback_only and strict_recording_found:
                continue

            search_results = (
                self._search_recordings(query, query_limit)
                if search_type == "recording"
                else self._search_releases(query, query_limit)
            )
            search_added = False
            for release in self._candidate_releases(search_type, search_results):
                if remaining_release_lookups <= 0:
                    break
                release_id = release.get("id", "")
                if not release_id or release_id in seen_release_ids:
                    continue
                seen_release_ids.add(release_id)
                remaining_release_lookups -= 1

                release_details = self._lookup_release(release_id)
                match_score, matched_track_title = self._match_track_title(release_details, title)
                if search_type == "recording" and title.strip() and match_score == 0:
                    recording_title = release.get("_recording_title", "")
                    match_score = self._field_match_score(recording_title, title)
                    matched_track_title = recording_title if match_score else matched_track_title

                if search_type == "release" and title.strip() and match_score == 0 and album.strip():
                    continue

                artist_name = self._artist_name(release_details.get("artist-credit", []) or release.get("artist-credit", []))
                release_title = release_details.get("title", release.get("title", album or "Unknown album"))
                release_group = release.get("release-group", {}) or release_details.get("release-group", {}) or {}
                release_group_id = release_group.get("id", "")
                cover_art_url = ""
                if release_group_id:
                    cover_art_url = f"{self.cover_art_root}/release-group/{release_group_id}/front-250"
                elif release_id:
                    cover_art_url = f"{self.cover_art_root}/release/{release_id}/front-250"

                search_added = True
                candidates.append(
                    (
                        (match_score * 10)
                        + (self._field_match_score(artist_name, artist) * 3)
                        + (self._field_match_score(release_title, album) * 2),
                        LookupCandidate(
                            release_id=release_id,
                            release_group_id=release_group_id,
                            title=release_title,
                            artist=artist_name or artist or "Unknown artist",
                            date=release_details.get("date", release.get("date", "")),
                            country=release_details.get("country", release.get("country", "")),
                            track_title=matched_track_title or title,
                            cover_art_url=cover_art_url,
                        ),
                    )
                )

            if search_type == "recording" and not fallback_only and search_added:
                strict_recording_found = True

        candidates.sort(key=lambda item: item[0], reverse=True)
        return [candidate for _, candidate in candidates[:limit]]

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

    def _build_release_query(self, *, artist: str, album: str) -> str:
        clauses: list[str] = []
        if album.strip():
            clauses.append(f'release:"{album.strip()}"')
        if artist.strip():
            clauses.append(f'artist:"{artist.strip()}"')
        if not clauses:
            raise LookupError("Track metadata is too sparse to search for album info.")
        return " AND ".join(clauses)

    def _build_recording_query(self, *, artist: str, title: str) -> str:
        clauses: list[str] = []
        if artist.strip():
            clauses.append(f'artist:"{artist.strip()}"')
        if title.strip():
            clauses.append(f'recording:"{title.strip()}"')
        if not clauses:
            raise LookupError("Track metadata is too sparse to search for album info.")
        return " AND ".join(clauses)

    def _build_recording_fallback_query(self, *, artist: str, title: str) -> str:
        clauses: list[str] = []
        if artist.strip():
            clauses.append(f'artistname:"{artist.strip()}"')
        if title.strip():
            clauses.append(" ".join(title.strip().split()))
        if not clauses:
            raise LookupError("Track metadata is too sparse to search for album info.")
        return " AND ".join(clauses)

    def _search_releases(self, query: str, limit: int) -> list[dict]:
        url = f"{self.api_root}/release/?query={urllib.parse.quote(query)}&fmt=json&limit={limit}"
        payload = self._get_json(url)
        return payload.get("releases", [])

    def _search_recordings(self, query: str, limit: int) -> list[dict]:
        url = f"{self.api_root}/recording/?query={urllib.parse.quote(query)}&fmt=json&limit={limit}"
        payload = self._get_json(url)
        return payload.get("recordings", [])

    def _lookup_release(self, release_id: str) -> dict:
        url = f"{self.api_root}/release/{release_id}?inc=recordings+artist-credits&fmt=json"
        return self._get_json(url)

    def _candidate_releases(self, search_type: str, results: list[dict]) -> list[dict]:
        if search_type == "release":
            return results

        releases: list[dict] = []
        for recording in results:
            for release in recording.get("releases", []) or []:
                release_copy = dict(release)
                release_copy["_recording_title"] = recording.get("title", "")
                releases.append(release_copy)
        return releases

    def _artist_name(self, artist_credit: list) -> str:
        parts = []
        for part in artist_credit:
            if isinstance(part, dict):
                parts.append(part.get("name", ""))
                if part.get("joinphrase"):
                    parts.append(part["joinphrase"])
            else:
                parts.append(str(part))
        return "".join(parts).strip()

    def _match_track_title(self, release_details: dict, target_title: str) -> tuple[int, str]:
        if not target_title.strip():
            return 1, ""

        best_score = 0
        best_title = ""

        for medium in release_details.get("media", []) or []:
            for track in medium.get("tracks", []) or []:
                track_title = track.get("title", "")
                score = self._field_match_score(track_title, target_title)

                if score > best_score:
                    best_score = score
                    best_title = track_title

        return best_score, best_title

    def _field_match_score(self, candidate: str, target: str) -> int:
        if not candidate.strip() or not target.strip():
            return 0

        normalized_candidate = _normalize(candidate)
        normalized_target = _normalize(target)
        if normalized_candidate == normalized_target:
            return 3
        if normalized_target in normalized_candidate or normalized_candidate in normalized_target:
            return 2
        return 0

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

    def _validate_search_inputs(self, *, title: str, artist: str, album: str) -> None:
        fields = [bool(title.strip()), bool(artist.strip()), bool(album.strip())]
        if sum(fields) < 2:
            raise LookupError("Enter at least two fields. Use title + artist, artist + album, or title + album.")


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


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
