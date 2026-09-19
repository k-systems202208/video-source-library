from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from database import connect, initialize_database, now_iso
from tmdb_cache import put_cached_json
from tmdb_sync import sync_tmdb_library


class RuntimeAuditClient:
    def search_movie(self, query, *, year=None, language="ja-JP"):
        return {"results": []}

    def search_tv(self, query, *, first_air_date_year=None, language="ja-JP"):
        return {
            "results": [{
                "id": 71404,
                "name": "Q10（キュート）",
                "original_name": "Q10",
                "first_air_date": "2010-10-16",
                "poster_path": "/q10.jpg",
                "backdrop_path": None,
                "overview": "TV drama",
            }]
        }


def seed_v3_database(db: Path) -> int:
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
            ) VALUES(?, 'movie', 999, 'MATCHED', 1.0, 'Wrong Q10', '2010', ?, ?)
            """,
            (work_id, stamp, stamp),
        )
        put_cached_json(
            connection,
            "tmdb:matcher-version",
            {"version": 3},
            fetched_at=stamp,
            expires_at=None,
        )
        connection.commit()
        return work_id


class TmdbRuntimeAuditTests(unittest.TestCase):
    def test_v3_marker_is_reassessed_and_reports_runtime_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "library.db"
            image_root = root / "TMDbImages"
            reports = root / "diagnostics"
            work_id = seed_v3_database(db)

            def fake_download(remote_path, destination, *, size):
                destination = Path(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"image")
                return destination

            result = sync_tmdb_library(
                db,
                image_root,
                reports,
                "token",
                client=RuntimeAuditClient(),
                image_downloader=fake_download,
            )

            self.assertEqual(result["summary"]["appVersion"], "1.2.0")
            self.assertEqual(result["summary"]["matcherVersion"], 8)
            self.assertEqual(result["summary"]["matched"], 1)

            with Path(result["jsonReport"]).open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(payload["summary"]["appVersion"], "1.2.0")
            self.assertEqual(payload["summary"]["matcherVersion"], 8)
            self.assertEqual(payload["items"][0]["appVersion"], "1.2.0")
            self.assertEqual(payload["items"][0]["matcherVersion"], 8)

            with Path(result["csvReport"]).open("r", encoding="utf-8-sig", newline="") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["appVersion"], "1.2.0")
            self.assertEqual(row["matcherVersion"], "8")
            self.assertEqual(row["mediaType"], "tv")
            self.assertEqual(int(row["tmdbId"]), 71404)

            with connect(db) as connection:
                link = connection.execute(
                    "SELECT media_type,tmdb_id,match_status FROM tmdb_work_links WHERE work_id=?",
                    (work_id,),
                ).fetchone()
                self.assertEqual(link["media_type"], "tv")
                self.assertEqual(int(link["tmdb_id"]), 71404)
                marker = connection.execute(
                    "SELECT payload_json FROM tmdb_api_cache WHERE cache_key='tmdb:matcher-version'"
                ).fetchone()
                self.assertIn('\"version\":8', marker["payload_json"])


if __name__ == "__main__":
    unittest.main()
