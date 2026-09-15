from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from database import connect, initialize_database, now_iso
from library_service import get_work, list_works
from tmdb_images import cached_image_path, resolve_cached_tmdb_image
from tmdb_sync import Candidate, choose_candidate, sync_tmdb_library


class FakeTmdbClient:
    def search_movie(self, query, *, year=None, language="ja-JP"):
        return {
            "results": [
                {
                    "id": 101,
                    "title": "テスト映画",
                    "original_title": "Test Movie",
                    "release_date": "2020-04-03",
                    "poster_path": "/poster101.jpg",
                    "backdrop_path": "/backdrop101.jpg",
                    "overview": "これはTMDbの概要です。",
                }
            ]
        }

    def search_tv(self, query, *, first_air_date_year=None, language="ja-JP"):
        return {"results": []}


def seed_work(db: Path) -> int:
    with connect(db) as connection:
        initialize_database(connection)
        stamp = now_iso()
        connection.execute(
            """
            INSERT INTO works(
                external_work_no,category,year_or_period,source_title,official_title,
                media_file_count,subtitle_file_count,subfolder_count,created_at,updated_at
            ) VALUES(1,'日本映画','2020','Test Movie','テスト映画',0,0,0,?,?)
            """,
            (stamp, stamp),
        )
        work_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.commit()
        return work_id


class TmdbMatchingTests(unittest.TestCase):
    def test_close_candidates_require_review(self):
        work = {"year_or_period": "2020"}
        first = Candidate("movie", 1, "作品", "2020", "/a.jpg", None, "", 0.99, 1.0, 0.97)
        second = Candidate("movie", 2, "作品", "2020", "/b.jpg", None, "", 0.98, 1.0, 0.94)
        status, selected, reason = choose_candidate(work, [first, second])
        self.assertEqual(status, "REVIEW")
        self.assertEqual(selected.tmdb_id, 1)
        self.assertEqual(reason, "REVIEW_REQUIRED")

    def test_sync_matches_exact_title_year_and_caches_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "library.db"
            image_root = root / "TMDbImages"
            reports = root / "diagnostics"
            work_id = seed_work(db)

            def fake_download(remote_path, destination, *, size):
                destination = Path(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((remote_path + size).encode("utf-8"))
                return destination

            report = sync_tmdb_library(
                db,
                image_root,
                reports,
                "not-a-real-token",
                client=FakeTmdbClient(),
                image_downloader=fake_download,
            )
            self.assertEqual(report["summary"]["total"], 1)
            self.assertEqual(report["summary"]["matched"], 1)
            self.assertEqual(report["summary"]["review"], 0)
            self.assertEqual(report["summary"]["unmatched"], 0)
            self.assertEqual(report["summary"]["posterCached"], 1)
            self.assertEqual(report["summary"]["backdropCached"], 1)
            self.assertTrue(Path(report["jsonReport"]).is_file())
            self.assertTrue(Path(report["csvReport"]).is_file())

            poster = cached_image_path(image_root, work_id, "poster", "/poster101.jpg")
            backdrop = cached_image_path(image_root, work_id, "backdrop", "/backdrop101.jpg")
            self.assertTrue(poster.is_file())
            self.assertTrue(backdrop.is_file())

            with connect(db) as connection:
                row = connection.execute(
                    "SELECT match_status,tmdb_id,confidence,poster_path,backdrop_path FROM tmdb_work_links WHERE work_id=?",
                    (work_id,),
                ).fetchone()
                self.assertEqual(row["match_status"], "MATCHED")
                self.assertEqual(int(row["tmdb_id"]), 101)
                self.assertGreaterEqual(float(row["confidence"]), 0.92)
                resolved = resolve_cached_tmdb_image(connection, image_root, work_id, "poster")
                self.assertIsNotNone(resolved)
                self.assertEqual(resolved[0], poster)
                self.assertEqual(resolved[1], "image/jpeg")

                listing = list_works(connection)
                self.assertEqual(listing["items"][0]["posterUrl"], f"/tmdb-image/poster/{work_id}")
                detail = get_work(connection, work_id)
                self.assertEqual(detail["posterUrl"], f"/tmdb-image/poster/{work_id}")
                self.assertEqual(detail["backdropUrl"], f"/tmdb-image/backdrop/{work_id}")
                self.assertEqual(detail["tmdb"]["status"], "MATCHED")
                self.assertEqual(detail["tmdb"]["overview"], "これはTMDbの概要です。")

    def test_review_candidate_does_not_expose_image_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            work_id = seed_work(db)
            stamp = now_iso()
            with connect(db) as connection:
                connection.execute(
                    """
                    INSERT INTO tmdb_work_links(
                        work_id,media_type,tmdb_id,match_status,confidence,matched_title,matched_year,
                        poster_path,backdrop_path,created_at,updated_at
                    ) VALUES(?, 'movie', 55, 'REVIEW', 0.88, '別候補', '2020', '/x.jpg', '/y.jpg', ?, ?)
                    """,
                    (work_id, stamp, stamp),
                )
                connection.commit()
                listing = list_works(connection)
                self.assertIsNone(listing["items"][0]["posterUrl"])
                detail = get_work(connection, work_id)
                self.assertIsNone(detail["posterUrl"])
                self.assertEqual(detail["tmdb"]["status"], "REVIEW")


class TmdbUiAndSafetyTests(unittest.TestCase):
    def test_launcher_server_and_ui_expose_tmdb_sync_and_local_images(self):
        launcher = (SRC / "launcher.py").read_text(encoding="utf-8")
        server = (SRC / "server.py").read_text(encoding="utf-8")
        html = (SRC / "video-library.html").read_text(encoding="utf-8")
        sw = (SRC / "service-worker.js").read_text(encoding="utf-8")
        self.assertIn('text="TMDb同期"', launcher)
        self.assertIn("sync_tmdb_library", launcher)
        self.assertIn("/tmdb-image/(poster|backdrop)/", server)
        self.assertIn("resolve_cached_tmdb_image", server)
        self.assertIn("posterUrl", html)
        self.assertIn("backdropUrl", html)
        self.assertIn("poster-fallback", html)
        self.assertIn("This product uses the TMDB API but is not endorsed or certified by TMDB.", html)
        self.assertIn("/tmdb-image/", sw)

    def test_source_never_embeds_tmdb_token_in_image_or_report_url(self):
        sync_source = (SRC / "tmdb_sync.py").read_text(encoding="utf-8")
        image_source = (SRC / "tmdb_images.py").read_text(encoding="utf-8")
        self.assertNotIn("api_key=", sync_source)
        self.assertNotIn("access_token=", sync_source)
        self.assertNotIn("api_key=", image_source)
        self.assertNotIn("access_token=", image_source)


if __name__ == "__main__":
    unittest.main()
