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


class ReleaseLookupBudgetClient(MusicMetadataClient):
    def __init__(self) -> None:
        super().__init__(user_agent="Songshare-Test/0.1")
        self.release_ids: list[str] = []

    def _search_releases(self, query: str, limit: int) -> list[dict]:
        return []

    def _search_recordings(self, query: str, limit: int) -> list[dict]:
        return [
            {
                "title": "Big Song",
                "releases": [
                    {
                        "id": f"release-{index}",
                        "title": f"Release {index}",
                        "artist-credit": [{"name": "Big Artist"}],
                        "release-group": {"id": f"group-{index}"},
                    }
                    for index in range(20)
                ],
            }
        ]

    def _lookup_release(self, release_id: str) -> dict:
        self.release_ids.append(release_id)
        return {
            "id": release_id,
            "title": "Big Album",
            "artist-credit": [{"name": "Big Artist"}],
            "release-group": {"id": "group-1"},
            "date": "2018-12-31",
            "country": "XW",
            "media": [{"tracks": [{"title": "Big Song"}]}],
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

    def test_limits_release_detail_lookups_for_popular_recordings(self) -> None:
        client = ReleaseLookupBudgetClient()

        candidates = client.search_release_candidates(title="Big Song", artist="Big Artist", album="", limit=1)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(client.release_ids), client.max_release_lookups_floor)
        self.assertEqual(client.release_ids[0], "release-0")


if __name__ == "__main__":
    unittest.main()
