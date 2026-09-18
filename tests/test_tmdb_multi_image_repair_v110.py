from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from database import connect, initialize_database, now_iso
from tmdb_cache import put_cached_json
from tmdb_sync import _IMAGE_CACHE_REPAIR_VERSION, _requires_image_cache_repair, sync_tmdb_library


class ExistingMatchClient:
    def __init__(self):
        self.detail_calls = []

    def search_movie(self, *args, **kwargs):
        raise AssertionError("existing MATCHED must not be rematched")

    def search_tv(self, *args, **kwargs):
        raise AssertionError("existing MATCHED must not be rematched")

    def tv_details(self, tv_id, *, language="ja-JP"):
        self.detail_calls.append((tv_id, language))
        return {
            "id": tv_id,
            "name": "スマイル",
            "first_air_date": "2009-04-17",
            "poster_path": "/correct-smile-poster.jpg",
            "backdrop_path": "/correct-smile-backdrop.jpg",
            "overview": "correct",
        }


class TmdbMultiImageRepairV110Tests(unittest.TestCase):
    def test_repair_version_is_three(self):
        self.assertEqual(_IMAGE_CACHE_REPAIR_VERSION, 3)

    def test_all_reported_titles_and_trick_are_repair_targets(self):
        cases = [
            ("TRICK", "2000-2003"),
            ("PRICELESS〜あるわけねぇだろ、んなもん!〜", "2012"),
            ("スマイル", "2009"),
            ("ビギナーズ!", "2012"),
            ("ビギナーズ！", "2012"),
            ("プライド", "2004"),
        ]
        for title, period in cases:
            with self.subTest(title=title):
                self.assertTrue(_requires_image_cache_repair({
                    "official_title": title,
                    "source_title": "",
                    "year_or_period": period,
                }))
        self.assertFalse(_requires_image_cache_repair({
            "official_title": "プライド", "source_title": "", "year_or_period": "2005"
        }))

    def test_existing_tmdb_id_is_preserved_while_both_images_are_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "library.db"
            images = root / "TMDbImages"
            reports = root / "diagnostics"
            with connect(db) as connection:
                initialize_database(connection)
                stamp = now_iso()
                connection.execute(
                    """
                    INSERT INTO works(
                        external_work_no,category,year_or_period,source_title,official_title,
                        media_file_count,subtitle_file_count,subfolder_count,created_at,updated_at
                    ) VALUES(1,'日本映画・ドラマ','2009','Smile','スマイル',11,0,1,?,?)
                    """,
                    (stamp, stamp),
                )
                work_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
                connection.execute(
                    """
                    INSERT INTO tmdb_work_links(
                        work_id,media_type,tmdb_id,match_status,confidence,matched_title,matched_year,
                        poster_path,backdrop_path,overview,synced_at,created_at,updated_at
                    ) VALUES(?, 'tv', 18819, 'MATCHED', 1.0, 'スマイル', '2009',
                             '/old-poster.jpg', '/old-backdrop.jpg', 'old', ?, ?, ?)
                    """,
                    (work_id, stamp, stamp, stamp),
                )
                put_cached_json(connection, "tmdb:matcher-version", {"version": 7}, fetched_at=stamp, expires_at=None)
                put_cached_json(connection, "tmdb:image-cache-repair-version", {"version": 2}, fetched_at=stamp, expires_at=None)
                connection.commit()

            poster = images / "poster" / f"{work_id}.jpg"
            backdrop = images / "backdrop" / f"{work_id}.jpg"
            poster.parent.mkdir(parents=True)
            backdrop.parent.mkdir(parents=True)
            poster.write_bytes(b"wrong poster")
            backdrop.write_bytes(b"wrong backdrop")

            def downloader(remote_path, destination, *, size):
                target = Path(destination)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(f"{remote_path}:{size}".encode("utf-8"))
                return target

            client = ExistingMatchClient()
            result = sync_tmdb_library(
                db, images, reports, "token", client=client, image_downloader=downloader
            )
            self.assertEqual(client.detail_calls, [(18819, "ja-JP")])
            self.assertEqual(result["summary"]["matcherVersion"], 7)
            self.assertNotEqual(poster.read_bytes(), b"wrong poster")
            self.assertNotEqual(backdrop.read_bytes(), b"wrong backdrop")
            self.assertIn(b"correct-smile-poster", poster.read_bytes())
            self.assertIn(b"correct-smile-backdrop", backdrop.read_bytes())

            with connect(db) as connection:
                row = connection.execute(
                    "SELECT media_type,tmdb_id,poster_path,backdrop_path FROM tmdb_work_links WHERE work_id=?",
                    (work_id,),
                ).fetchone()
                self.assertEqual(row["media_type"], "tv")
                self.assertEqual(int(row["tmdb_id"]), 18819)
                self.assertEqual(row["poster_path"], "/correct-smile-poster.jpg")
                self.assertEqual(row["backdrop_path"], "/correct-smile-backdrop.jpg")

    def test_tmdb_images_use_short_private_browser_cache(self):
        source = (SRC / "server.py").read_text(encoding="utf-8")
        segment = source[source.index("def _serve_tmdb_image"):source.index("def do_GET")]
        self.assertIn('self._common(cache="private, max-age=300")', segment)
        self.assertNotIn('cache="no-store"', segment)

    def test_header_brand_has_centered_override_for_all_breakpoints(self):
        html = (SRC / "video-library.html").read_text(encoding="utf-8")
        marker = html[html.index("/* SEKIMACHI_KITA_CINEMA_HEADER_V2 */"):html.index("/* NAVIGATION_PEOPLE_MENU_V2 */")]
        self.assertIn("justify-content:center!important", marker)
        self.assertIn("@media(min-width:1200px)", marker)
        self.assertIn("@media(min-width:768px) and (max-width:1199px)", marker)
        self.assertIn("@media(max-width:767px)", marker)
        self.assertNotIn("justify-self:start", marker)
        self.assertIn("width:fit-content!important", marker)
        self.assertNotIn("width:100%!important;max-width:none!important", marker)


if __name__ == "__main__":
    unittest.main()
