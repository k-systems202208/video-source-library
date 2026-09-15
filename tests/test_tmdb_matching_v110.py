from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from database import connect, initialize_database, now_iso
from tmdb_matcher import (
    AUTO_MATCH_MARGIN,
    AUTO_MATCH_THRESHOLD,
    audit_tmdb_library,
    extract_year,
    match_work,
    normalize_title,
    preferred_media_types,
)


class FakeTmdbClient:
    def __init__(self, *, movie_results=None, tv_results=None, details=None):
        self.movie_results = list(movie_results or [])
        self.tv_results = list(tv_results or [])
        self.details = dict(details or {})
        self.calls = []

    def search_movie(self, query, *, year=None, language="ja-JP"):
        self.calls.append(("search_movie", query, year))
        return {"results": list(self.movie_results)}

    def search_tv(self, query, *, first_air_date_year=None, language="ja-JP"):
        self.calls.append(("search_tv", query, first_air_date_year))
        return {"results": list(self.tv_results)}

    def movie_details(self, tmdb_id, *, language="ja-JP"):
        self.calls.append(("movie_details", tmdb_id))
        return dict(self.details.get(("movie", int(tmdb_id)), {}))

    def tv_details(self, tmdb_id, *, language="ja-JP"):
        self.calls.append(("tv_details", tmdb_id))
        return dict(self.details.get(("tv", int(tmdb_id)), {}))


def seed_work(connection, *, external_no=1, category="海外映画", title="Back to the Future", year="1985", media_count=1):
    stamp = now_iso()
    connection.execute(
        """
        INSERT INTO works(
          external_work_no,category,year_or_period,official_title,media_file_count,
          subtitle_file_count,subfolder_count,created_at,updated_at
        ) VALUES(?,?,?,?,?,0,0,?,?)
        """,
        (external_no, category, year, title, media_count, stamp, stamp),
    )
    connection.commit()
    return int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])


class TmdbMatchingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "library.db"
        with connect(self.db) as connection:
            initialize_database(connection)

    def tearDown(self):
        self.temp.cleanup()

    def test_title_year_and_media_type_helpers_are_conservative(self):
        self.assertEqual(normalize_title("Ｂａｃｋ　ｔｏ：Ｔｈｅ Ｆｕｔｕｒｅ"), "backtothefuture")
        self.assertEqual(extract_year("1985年 / HD"), 1985)
        self.assertEqual(preferred_media_types("海外映画", 1), (["movie"], "movie"))
        self.assertEqual(preferred_media_types("国内ドラマ", 10), (["tv"], "tv"))
        self.assertEqual(preferred_media_types("アニメ", 24), (["tv", "movie"], "tv"))
        self.assertEqual(preferred_media_types("アニメ", 1), (["tv", "movie"], None))
        self.assertGreaterEqual(AUTO_MATCH_THRESHOLD, 0.9)
        self.assertGreaterEqual(AUTO_MATCH_MARGIN, 0.05)

    def test_exact_movie_title_and_year_auto_matches_and_caches_image_refs(self):
        with connect(self.db) as connection:
            work_id = seed_work(connection)
            work = connection.execute("SELECT * FROM works WHERE id=?", (work_id,)).fetchone()
            client = FakeTmdbClient(
                movie_results=[{
                    "id": 105,
                    "title": "Back to the Future",
                    "original_title": "Back to the Future",
                    "release_date": "1985-07-03",
                    "poster_path": "/search.jpg",
                }],
                details={("movie", 105): {
                    "id": 105,
                    "title": "Back to the Future",
                    "release_date": "1985-07-03",
                    "poster_path": "/poster.jpg",
                    "backdrop_path": "/backdrop.jpg",
                    "overview": "A time travel story.",
                }},
            )
            result = match_work(connection, client, work)
            self.assertEqual(result["status"], "MATCHED")
            self.assertEqual(result["tmdbId"], 105)
            self.assertEqual(result["posterPath"], "/poster.jpg")
            self.assertEqual(result["backdropPath"], "/backdrop.jpg")
            row = connection.execute("SELECT * FROM tmdb_work_links WHERE work_id=?", (work_id,)).fetchone()
            self.assertEqual(row["match_status"], "MATCHED")
            self.assertEqual(row["tmdb_id"], 105)
            self.assertEqual(row["poster_path"], "/poster.jpg")
            self.assertGreaterEqual(float(row["confidence"]), AUTO_MATCH_THRESHOLD)

    def test_equal_top_candidates_are_review_not_auto_matched(self):
        with connect(self.db) as connection:
            work_id = seed_work(connection)
            work = connection.execute("SELECT * FROM works WHERE id=?", (work_id,)).fetchone()
            client = FakeTmdbClient(movie_results=[
                {"id": 1, "title": "Back to the Future", "release_date": "1985-01-01"},
                {"id": 2, "title": "Back to the Future", "release_date": "1985-12-31"},
            ])
            result = match_work(connection, client, work)
            self.assertEqual(result["status"], "REVIEW")
            self.assertEqual(result["margin"], 0.0)
            self.assertFalse(any(call[0] == "movie_details" for call in client.calls))

    def test_anime_searches_tv_and_movie_and_does_not_force_ambiguous_type(self):
        with connect(self.db) as connection:
            work_id = seed_work(connection, category="アニメ", title="Example Anime", year="2020", media_count=1)
            work = connection.execute("SELECT * FROM works WHERE id=?", (work_id,)).fetchone()
            client = FakeTmdbClient(
                movie_results=[{"id": 20, "title": "Example Anime", "release_date": "2020-01-01"}],
                tv_results=[{"id": 10, "name": "Example Anime", "first_air_date": "2020-01-01"}],
            )
            result = match_work(connection, client, work)
            self.assertEqual(result["status"], "REVIEW")
            self.assertTrue(any(call[0] == "search_tv" for call in client.calls))
            self.assertTrue(any(call[0] == "search_movie" for call in client.calls))

    def test_audit_outputs_excel_friendly_csv_and_never_writes_token(self):
        with connect(self.db) as connection:
            seed_work(connection)
        client = FakeTmdbClient(
            movie_results=[{"id": 105, "title": "Back to the Future", "release_date": "1985-07-03"}],
            details={("movie", 105): {"id": 105, "title": "Back to the Future", "release_date": "1985-07-03"}},
        )
        report = audit_tmdb_library(self.db, "SUPER-SECRET-TOKEN", Path(self.temp.name) / "diag", client=client)
        self.assertEqual(report["summary"]["total"], 1)
        self.assertEqual(report["summary"]["matched"], 1)
        json_path = Path(report["jsonReport"])
        csv_path = Path(report["csvReport"])
        self.assertTrue(json_path.is_file())
        self.assertTrue(csv_path.is_file())
        self.assertNotIn("SUPER-SECRET-TOKEN", json_path.read_text(encoding="utf-8"))
        self.assertNotIn("SUPER-SECRET-TOKEN", csv_path.read_text(encoding="utf-8-sig"))
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["summary"]["matched"], 1)
        self.assertTrue(csv_path.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_launcher_exposes_tmdb_matching_without_expanding_main_window(self):
        launcher = (SRC / "launcher.py").read_text(encoding="utf-8")
        self.assertIn("TMDb作品照合", launcher)
        self.assertIn("start_tmdb_match_audit", launcher)
        self.assertIn("audit_tmdb_library", launcher)
        self.assertIn('WINDOW_GEOMETRY = "780x690"', launcher)


if __name__ == "__main__":
    unittest.main()
