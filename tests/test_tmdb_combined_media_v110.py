from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from database import connect, initialize_database, now_iso
from tmdb_sync import _media_types_for, sync_tmdb_library


class CombinedClient:
    def __init__(self):
        self.movie_calls = 0
        self.tv_calls = 0

    def search_movie(self, query, *, year=None, language="ja-JP"):
        self.movie_calls += 1
        return {"results": []}

    def search_tv(self, query, *, first_air_date_year=None, language="ja-JP"):
        self.tv_calls += 1
        return {"results": [{
            "id": 1396,
            "name": "ブレイキング・バッド",
            "original_name": "Breaking Bad",
            "first_air_date": "2008-01-20",
            "poster_path": "/bb.jpg",
            "backdrop_path": "/bb-bg.jpg",
            "overview": "TV series",
        }]}


def seed_combined_work(db: Path) -> int:
    with connect(db) as connection:
        initialize_database(connection)
        stamp = now_iso()
        connection.execute(
            """
            INSERT INTO works(
                external_work_no,category,year_or_period,source_title,official_title,
                media_file_count,subtitle_file_count,subfolder_count,created_at,updated_at
            ) VALUES(1,'海外映画・ドラマ','2008','Breaking Bad','ブレイキング・バッド',1,0,0,?,?)
            """,
            (stamp, stamp),
        )
        work_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.execute(
            """
            INSERT INTO tmdb_work_links(
                work_id,media_type,tmdb_id,match_status,confidence,matched_title,matched_year,
                created_at,updated_at
            ) VALUES(?, 'movie', 999, 'MATCHED', 1.0, 'Wrong Movie', '2008', ?, ?)
            """,
            (work_id, stamp, stamp),
        )
        connection.commit()
        return work_id


class CombinedMediaMatchingTests(unittest.TestCase):
    def test_combined_categories_search_movie_and_tv(self):
        self.assertEqual(_media_types_for("日本映画・ドラマ"), ("movie", "tv"))
        self.assertEqual(_media_types_for("海外映画・ドラマ"), ("movie", "tv"))
        self.assertEqual(_media_types_for("日本映画"), ("movie",))
        self.assertEqual(_media_types_for("国内ドラマ"), ("tv",))

    def test_legacy_existing_match_is_reassessed_once_and_tv_can_win(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "library.db"
            image_root = root / "TMDbImages"
            reports = root / "diagnostics"
            work_id = seed_combined_work(db)
            client = CombinedClient()

            def fake_download(remote_path, destination, *, size):
                destination = Path(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"image")
                return destination

            report = sync_tmdb_library(
                db, image_root, reports, "token", client=client, image_downloader=fake_download
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
                self.assertEqual(int(row["tmdb_id"]), 1396)
                self.assertEqual(row["match_status"], "MATCHED")
                marker = connection.execute(
                    "SELECT payload_json FROM tmdb_api_cache WHERE cache_key='tmdb:matcher-version'"
                ).fetchone()
                self.assertIn('\"version\":6', marker["payload_json"])

            second_client = CombinedClient()
            second = sync_tmdb_library(
                db, image_root, reports, "token", client=second_client, image_downloader=fake_download
            )
            self.assertEqual(second["summary"]["matched"], 1)
            self.assertEqual(second_client.movie_calls, 0)
            self.assertEqual(second_client.tv_calls, 0)
            with connect(db) as connection:
                row = connection.execute(
                    "SELECT media_type,tmdb_id,match_status FROM tmdb_work_links WHERE work_id=?",
                    (work_id,),
                ).fetchone()
                self.assertEqual(row["media_type"], "tv")
                self.assertEqual(int(row["tmdb_id"]), 1396)
                self.assertEqual(row["match_status"], "MATCHED")


if __name__ == "__main__":
    unittest.main()
