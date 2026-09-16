from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from tmdb_sync import _collect_candidates, _search_query_variants, _title_similarity, choose_candidate


class DummyConnection:
    def commit(self):
        return None


class JapaneseAliasClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int | None]] = []

    def search_movie(self, query, *, year=None, language="ja-JP"):
        return {"results": []}

    def search_tv(self, query, *, first_air_date_year=None, language="ja-JP"):
        self.calls.append((query, first_air_date_year))
        if query == "トリック" and first_air_date_year == 2000:
            return {"results": [{
                "id": 19616,
                "name": "トリック",
                "original_name": "TRICK",
                "first_air_date": "2000-07-07",
                "poster_path": "/trick.jpg",
                "backdrop_path": "/trick-bg.jpg",
                "overview": "TV drama",
            }]}
        if query == "グッドラック" and first_air_date_year == 2003:
            return {"results": [{
                "id": 2146,
                "name": "GOOD LUCK!!",
                "original_name": "GOOD LUCK!!",
                "first_air_date": "2003-01-19",
                "poster_path": "/goodluck.jpg",
                "backdrop_path": "/goodluck-bg.jpg",
                "overview": "TV drama",
            }]}
        return {"results": []}


class TmdbMatcherV6Tests(unittest.TestCase):
    def test_audited_japanese_aliases_are_searchable_and_equivalent(self):
        self.assertIn("トリック", _search_query_variants("TRICK"))
        self.assertIn("グッドラック", _search_query_variants("GOOD LUCK!!"))
        self.assertEqual(_title_similarity("TRICK", "トリック"), 1.0)
        self.assertEqual(_title_similarity("GOOD LUCK!!", "グッドラック"), 1.0)

    def _assert_alias_match(self, title: str, period: str, expected_id: int, expected_query: str, expected_year: int):
        work = {
            "category": "国内ドラマ",
            "year_or_period": period,
            "official_title": title,
            "source_title": title,
            "media_file_count": 10,
            "episode_count": 10,
            "movie_content_count": 0,
        }
        client = JapaneseAliasClient()
        with patch("tmdb_sync.get_cached_json", return_value=None), patch("tmdb_sync.put_cached_json"):
            candidates = _collect_candidates(DummyConnection(), client, work)
        status, selected, _ = choose_candidate(work, candidates)
        self.assertEqual(status, "MATCHED")
        self.assertIsNotNone(selected)
        self.assertEqual(selected.tmdb_id, expected_id)
        self.assertIn((expected_query, expected_year), client.calls)

    def test_trick_resolves_through_japanese_alias(self):
        self._assert_alias_match("TRICK", "2000-2003", 19616, "トリック", 2000)

    def test_good_luck_resolves_through_japanese_alias(self):
        self._assert_alias_match("GOOD LUCK!!", "2003", 2146, "グッドラック", 2003)


if __name__ == "__main__":
    unittest.main()
