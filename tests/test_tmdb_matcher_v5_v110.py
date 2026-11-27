from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from database import connect, initialize_database, now_iso
from tmdb_cache import put_cached_json
from tmdb_sync import (
    Candidate,
    _collect_candidates,
    _search_cache_key,
    _search_query_variants,
    _title_similarity,
    choose_candidate,
    sync_tmdb_library,
)


class DummyConnection:
    def commit(self):
        return None


class GoodLuckFallbackClient:
    def __init__(self):
        self.calls = []

    def search_movie(self, query, *, year=None, language="ja-JP"):
        raise AssertionError("movie search is not expected")

    def search_tv(self, query, *, first_air_date_year=None, language="ja-JP"):
        self.calls.append((query, first_air_date_year))
        if query == "GOOD LUCK" and first_air_date_year == 2003:
            return {
                "results": [{
                    "id": 2146,
                    "name": "GOOD LUCK!!",
                    "original_name": "GOOD LUCK!!",
                    "first_air_date": "2003-01-19",
                    "poster_path": "/good-luck.jpg",
                    "backdrop_path": "/good-luck-bg.jpg",
                    "overview": "TV drama",
                }]
            }
        return {"results": []}


class ExplodingClient:
    def __init__(self):
        self.calls = 0

    def search_movie(self, query, *, year=None, language="ja-JP"):
        self.calls += 1
        raise AssertionError("v4 MATCHED must not be searched again by matcher v6")

    def search_tv(self, query, *, first_air_date_year=None, language="ja-JP"):
        self.calls += 1
        raise AssertionError("v4 MATCHED must not be searched again by matcher v6")


def seed_v4_matched(db: Path) -> int:
    with connect(db) as connection:
        initialize_database(connection)
        stamp = now_iso()
        connection.execute(
            """
            INSERT INTO works(
                external_work_no,category,year_or_period,source_title,official_title,
                media_file_count,subtitle_file_count,subfolder_count,created_at,updated_at
            ) VALUES(1,'日本映画・ドラマ','2010','Q10','Q10',9,0,1,?,?)
            """,
            (stamp, stamp),
        )
        work_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.execute(
            """
            INSERT INTO tmdb_work_links(
                work_id,media_type,tmdb_id,match_status,confidence,matched_title,matched_year,
                created_at,updated_at
            ) VALUES(?, 'tv', 71404, 'MATCHED', 1.0, 'Q10（キュート）', '2010', ?, ?)
            """,
            (work_id, stamp, stamp),
        )
        put_cached_json(
            connection,
            "tmdb:matcher-version",
            {"version": 4},
            fetched_at=stamp,
            expires_at=None,
        )
        connection.commit()
        return work_id


class TmdbMatcherV5Tests(unittest.TestCase):
    def test_audited_aliases_are_equivalent_for_matching(self):
        self.assertEqual(_title_similarity("LIAR GAME", "ライアーゲーム"), 1.0)
        self.assertEqual(_title_similarity("BLOODY MONDAY", "ブラッディ・マンデイ"), 1.0)

    def test_search_variants_include_subtitle_and_punctuation_fallbacks(self):
        self.assertIn(
            "アンタッチャブル",
            _search_query_variants("アンタッチャブル〜事件記者・鳴海遼子〜"),
        )
        self.assertIn("GOOD LUCK", _search_query_variants("GOOD LUCK!!"))
        self.assertIn("ブラッディ・マンデイ", _search_query_variants("BLOODY MONDAY"))

    def test_exact_title_and_exact_start_year_can_break_small_margin(self):
        work = {
            "category": "日本映画・ドラマ",
            "year_or_period": "2000-2003",
            "media_file_count": 30,
            "episode_count": 0,
            "movie_content_count": 0,
        }
        movie = Candidate(
            "movie", 1812, "Trick", "1999", "/m.jpg", None, "", 1.0, 0.65, 0.9475
        )
        tv = Candidate(
            "tv", 19616, "TRICK", "2000", "/t.jpg", None, "", 1.0, 1.0, 1.0
        )
        status, selected, reason = choose_candidate(work, [movie, tv])
        self.assertEqual(status, "MATCHED")
        self.assertEqual(selected.tmdb_id, 19616)
        self.assertEqual(reason, "AUTO_EXACT_TITLE_YEAR")

    def test_low_result_search_tries_punctuation_variant_and_yearless_fallback(self):
        work = {
            "category": "国内ドラマ",
            "year_or_period": "2003",
            "official_title": "GOOD LUCK!!",
            "source_title": "GOOD LUCK!!",
        }
        client = GoodLuckFallbackClient()
        with patch("tmdb_sync.get_cached_json", return_value=None), patch("tmdb_sync.put_cached_json"):
            candidates = _collect_candidates(DummyConnection(), client, work)
        self.assertTrue(any(item.tmdb_id == 2146 for item in candidates))
        self.assertIn(("GOOD LUCK!!", 2003), client.calls)
        self.assertIn(("GOOD LUCK!!", None), client.calls)
        self.assertIn(("GOOD LUCK", 2003), client.calls)

    def test_search_cache_namespace_is_v3(self):
        key = _search_cache_key("tv", "TRICK", 2000, "ja-JP")
        self.assertTrue(key.startswith("tmdb:search:v3:"))

    def test_v4_matched_result_is_preserved_without_api_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "library.db"
            image_root = root / "TMDbImages"
            reports = root / "diagnostics"
            work_id = seed_v4_matched(db)
            client = ExplodingClient()

            result = sync_tmdb_library(
                db,
                image_root,
                reports,
                "token",
                client=client,
                image_downloader=lambda *args, **kwargs: None,
            )
            self.assertEqual(client.calls, 0)
            self.assertEqual(result["summary"]["matcherVersion"], 8)
            self.assertEqual(result["summary"]["matched"], 1)

            with connect(db) as connection:
                row = connection.execute(
                    "SELECT media_type,tmdb_id,match_status FROM tmdb_work_links WHERE work_id=?",
                    (work_id,),
                ).fetchone()
                self.assertEqual(row["media_type"], "tv")
                self.assertEqual(int(row["tmdb_id"]), 71404)
                self.assertEqual(row["match_status"], "MATCHED")
                marker = connection.execute(
                    "SELECT payload_json FROM tmdb_api_cache WHERE cache_key='tmdb:matcher-version'"
                ).fetchone()
                self.assertIn('\"version\":8', marker["payload_json"])


if __name__ == "__main__":
    unittest.main()
