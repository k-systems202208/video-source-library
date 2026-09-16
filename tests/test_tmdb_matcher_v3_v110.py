from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from database import connect, initialize_database, now_iso
from tmdb_cache import put_cached_json
from tmdb_sync import Candidate, _title_similarity, choose_candidate, sync_tmdb_library


class AmbiguousDramaClient:
    def __init__(self) -> None:
        self.movie_calls = 0
        self.tv_calls = 0

    def search_movie(self, query, *, year=None, language="ja-JP"):
        self.movie_calls += 1
        return {
            "results": [{
                "id": 1001,
                "title": "プライド",
                "original_title": "Pride",
                "release_date": "2004-01-12",
                "poster_path": "/movie.jpg",
                "backdrop_path": "/movie-bg.jpg",
                "overview": "same-title movie",
            }]
        }

    def search_tv(self, query, *, first_air_date_year=None, language="ja-JP"):
        self.tv_calls += 1
        return {
            "results": [{
                "id": 2001,
                "name": "プライド",
                "original_name": "Pride",
                "first_air_date": "2004-01-12",
                "poster_path": "/tv.jpg",
                "backdrop_path": "/tv-bg.jpg",
                "overview": "serial drama",
            }]
        }


def seed_v2_ambiguous_drama(db: Path) -> int:
    with connect(db) as connection:
        initialize_database(connection)
        stamp = now_iso()
        connection.execute(
            """
            INSERT INTO works(
                external_work_no,category,year_or_period,source_title,official_title,
                media_file_count,subtitle_file_count,subfolder_count,created_at,updated_at
            ) VALUES(1,'日本映画・ドラマ','2004','Pride','プライド',11,0,1,?,?)
            """,
            (stamp, stamp),
        )
        work_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.execute(
            """
            INSERT INTO tmdb_work_links(
                work_id,media_type,tmdb_id,match_status,confidence,matched_title,matched_year,
                created_at,updated_at
            ) VALUES(?, 'movie', 1001, 'MATCHED', 1.0, 'プライド', '2004', ?, ?)
            """,
            (work_id, stamp, stamp),
        )
        put_cached_json(
            connection,
            "tmdb:matcher-version",
            {"version": 2},
            fetched_at=stamp,
            expires_at=None,
        )
        connection.commit()
        return work_id


class TmdbMatcherV3Tests(unittest.TestCase):
    def test_title_variants_accept_audited_notation_differences(self):
        pairs = (
            ("YASHA-夜叉-", "夜叉"),
            ("Q10（キュート）", "Q10"),
            ("HiGH&LOW ～THE STORY OF S.W.O.R.D.～", "HiGH&LOW"),
            ("ミス・シャーロック/Miss Sherlock", "ミス・シャーロック"),
        )
        for local, remote in pairs:
            with self.subTest(local=local, remote=remote):
                self.assertEqual(_title_similarity(local, remote), 1.0)

    def test_serial_media_context_breaks_movie_tv_tie_in_favor_of_tv(self):
        work = {
            "category": "日本映画・ドラマ",
            "year_or_period": "2004",
            "media_file_count": 11,
            "episode_count": 10,
            "movie_content_count": 0,
        }
        movie = Candidate("movie", 1001, "プライド", "2004", "/m.jpg", None, "", 1.0, 1.0, 1.0)
        tv = Candidate("tv", 2001, "プライド", "2004", "/t.jpg", None, "", 1.0, 1.0, 1.0)
        status, selected, reason = choose_candidate(work, [movie, tv])
        self.assertEqual(status, "MATCHED")
        self.assertEqual(selected.tmdb_id, 2001)
        self.assertEqual(reason, "AUTO_MEDIA_CONTEXT")

    def test_episode_context_can_overcome_slightly_higher_movie_base_score(self):
        work = {
            "category": "日本映画・ドラマ",
            "year_or_period": "2000-2003",
            "media_file_count": 30,
            "episode_count": 30,
            "movie_content_count": 0,
        }
        movie = Candidate("movie", 1812, "Trick", "1999", "/m.jpg", None, "", 1.0, 0.65, 0.9475)
        tv = Candidate("tv", 19616, "TRICK", "2000", "/t.jpg", None, "", 0.98, 1.0, 0.984)
        status, selected, reason = choose_candidate(work, [movie, tv])
        self.assertEqual(status, "MATCHED")
        self.assertEqual(selected.tmdb_id, 19616)
        self.assertEqual(reason, "AUTO_MEDIA_CONTEXT")

    def test_multi_year_collection_is_not_auto_matched_to_single_movie(self):
        work = {
            "category": "日本映画・ドラマ",
            "year_or_period": "1969-2019",
            "media_file_count": 48,
            "episode_count": 0,
            "movie_content_count": 48,
        }
        movie = Candidate("movie", 100, "男はつらいよ", "1969", "/m.jpg", None, "", 1.0, 1.0, 1.0)
        status, selected, reason = choose_candidate(work, [movie])
        self.assertEqual(status, "REVIEW")
        self.assertEqual(selected.tmdb_id, 100)
        self.assertEqual(reason, "MULTI_YEAR_MOVIE_REVIEW")

    def test_v2_match_is_reassessed_and_serial_work_switches_to_tv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "library.db"
            image_root = root / "TMDbImages"
            reports = root / "diagnostics"
            work_id = seed_v2_ambiguous_drama(db)
            client = AmbiguousDramaClient()

            def fake_download(remote_path, destination, *, size):
                destination = Path(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((remote_path + size).encode("utf-8"))
                return destination

            report = sync_tmdb_library(
                db,
                image_root,
                reports,
                "token",
                client=client,
                image_downloader=fake_download,
            )
            self.assertEqual(report["summary"]["matched"], 1)
            self.assertGreater(client.movie_calls, 0)
            self.assertGreater(client.tv_calls, 0)

            with connect(db) as connection:
                row = connection.execute(
                    "SELECT media_type,tmdb_id,match_status FROM tmdb_work_links WHERE work_id=?",
                    (work_id,),
                ).fetchone()
                self.assertEqual(row["media_type"], "tv")
                self.assertEqual(int(row["tmdb_id"]), 2001)
                self.assertEqual(row["match_status"], "MATCHED")
                marker = connection.execute(
                    "SELECT payload_json FROM tmdb_api_cache WHERE cache_key='tmdb:matcher-version'"
                ).fetchone()
                self.assertIn('\"version\":6', marker["payload_json"])


if __name__ == "__main__":
    unittest.main()
