from __future__ import annotations

import unittest

from songshare.album_lookup import LookupError, MusicMetadataClient


class StubMusicMetadataClient(MusicMetadataClient):
    def __init__(self) -> None:
        super().__init__(user_agent="Songshare-Test/0.1")
        self.recording_queries: list[str] = []

    def _search_releases(self, query: str, limit: int) -> list[dict]:
        return []

    def _search_recordings(self, query: str, limit: int) -> list[dict]:
        self.recording_queries.append(query)
        if query == 'artist:"Admo" AND recording:"Against all odds"':
            return []
        if query == 'artistname:"Admo" AND Against all odds':
            return [
                {
                    "title": "Against All Odds",
                    "releases": [
                        {
                            "id": "release-1",
                            "title": "Zero Wave",
                            "artist-credit": [{"name": "ADMO"}],
                            "release-group": {"id": "group-1"},
                        }
                    ],
                }
            ]
        return []

    def _lookup_release(self, release_id: str) -> dict:
        return {
            "id": release_id,
            "title": "Zero Wave",
            "artist-credit": [{"name": "ADMO"}],
            "release-group": {"id": "group-1"},
            "date": "2018-12-31",
            "country": "XW",
            "media": [{"tracks": []}],
        }


class MusicMetadataClientTestCase(unittest.TestCase):
    def test_requires_two_fields_for_lookup(self) -> None:
        client = MusicMetadataClient(user_agent="Songshare-Test/0.1")

        with self.assertRaises(LookupError):
            client.search_release_candidates(title="Against All Odds", artist="", album="")

    def test_recording_fallback_uses_artistname_query(self) -> None:
        client = StubMusicMetadataClient()

        candidates = client.search_release_candidates(title="Against all odds", artist="Admo", album="")

        self.assertEqual(
            client.recording_queries,
            ['artist:"Admo" AND recording:"Against all odds"', 'artistname:"Admo" AND Against all odds'],
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].title, "Zero Wave")
        self.assertEqual(candidates[0].artist, "ADMO")
        self.assertEqual(candidates[0].track_title, "Against All Odds")


if __name__ == "__main__":
    unittest.main()
