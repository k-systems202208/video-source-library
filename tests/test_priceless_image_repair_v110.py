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
from tmdb_cache import get_cached_json, put_cached_json
from tmdb_images import cached_image_path
from tmdb_sync import sync_tmdb_library


IMAGE_REPAIR_KEY = "tmdb:image-cache-repair-version"
IMAGE_REPAIR_GEN2_KEY = "tmdb:image-cache-repair-version:gen2"


class PricelessExistingMatchClient:
    def __init__(self):
        self.detail_calls: list[tuple[int, str]] = []

    def search_movie(self, *args, **kwargs):
        raise AssertionError("existing MATCHED must not be rematched")

    def search_tv(self, *args, **kwargs):
        raise AssertionError("existing MATCHED must not be rematched")

    def tv_details(self, tv_id, *, language="ja-JP"):
        self.detail_calls.append((tv_id, language))
        return {
            "id": tv_id,
            "name": "PRICELESS～あるわけねぇだろ、んなもん！～",
            "first_air_date": "2012-10-22",
            "poster_path": "/correct-priceless-poster.jpg",
            "backdrop_path": "/correct-priceless-backdrop.jpg",
            "overview": "correct",
        }


class PricelessImageRepairV110Tests(unittest.TestCase):
    def test_legacy_repair_marker_is_namespaced_to_a_new_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            with connect(db) as connection:
                initialize_database(connection)
                stamp = now_iso()
                connection.execute(
                    """
                    INSERT INTO tmdb_api_cache(cache_key,payload_json,fetched_at,expires_at)
                    VALUES(?,?,?,NULL)
                    """,
                    (IMAGE_REPAIR_KEY, json.dumps({"version": 3}), stamp),
                )
                connection.commit()

                # The old physical marker must no longer suppress the retry.
                self.assertIsNone(get_cached_json(connection, IMAGE_REPAIR_KEY))

                put_cached_json(
                    connection,
                    IMAGE_REPAIR_KEY,
                    {"version": 3},
                    fetched_at=stamp,
                    expires_at=None,
                )
                connection.commit()

                self.assertEqual(get_cached_json(connection, IMAGE_REPAIR_KEY), {"version": 3})
                keys = {
                    row["cache_key"]
                    for row in connection.execute(
                        "SELECT cache_key FROM tmdb_api_cache WHERE cache_key LIKE 'tmdb:image-cache-repair-version%'"
                    ).fetchall()
                }
                self.assertIn(IMAGE_REPAIR_KEY, keys)
                self.assertIn(IMAGE_REPAIR_GEN2_KEY, keys)

    def test_priceless_70203_is_refreshed_once_even_when_legacy_v3_marker_exists(self):
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
                    ) VALUES(280,'日本映画・ドラマ','2012','Priceless',
                             'PRICELESS〜あるわけねぇだろ、んなもん!〜',10,0,1,?,?)
                    """,
                    (stamp, stamp),
                )
                work_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
                connection.execute(
                    """
                    INSERT INTO tmdb_work_links(
                        work_id,media_type,tmdb_id,match_status,confidence,matched_title,matched_year,
                        poster_path,backdrop_path,overview,synced_at,created_at,updated_at
                    ) VALUES(?, 'tv', 70203, 'MATCHED', 1.0,
                             'PRICELESS～あるわけねぇだろ、んなもん！～', '2012',
                             '/old-poster.jpg', '/old-backdrop.jpg', 'old', ?, ?, ?)
                    """,
                    (work_id, stamp, stamp, stamp),
                )
                put_cached_json(
                    connection,
                    "tmdb:matcher-version",
                    {"version": 7},
                    fetched_at=stamp,
                    expires_at=None,
                )
                # Reproduce the marker written by the previously installed build.
                connection.execute(
                    """
                    INSERT INTO tmdb_api_cache(cache_key,payload_json,fetched_at,expires_at)
                    VALUES(?,?,?,NULL)
                    """,
                    (IMAGE_REPAIR_KEY, json.dumps({"version": 3}), stamp),
                )
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

            client = PricelessExistingMatchClient()
            first = sync_tmdb_library(
                db,
                images,
                reports,
                "token",
                client=client,
                image_downloader=downloader,
            )
            self.assertEqual(client.detail_calls, [(70203, "ja-JP")])
            self.assertEqual(first["summary"]["matched"], 1)
            self.assertEqual(poster.read_bytes(), b"wrong poster")
            self.assertEqual(backdrop.read_bytes(), b"wrong backdrop")
            current_poster = cached_image_path(
                images, work_id, "poster", "/correct-priceless-poster.jpg"
            )
            current_backdrop = cached_image_path(
                images, work_id, "backdrop", "/correct-priceless-backdrop.jpg"
            )
            self.assertIn(b"correct-priceless-poster", current_poster.read_bytes())
            self.assertIn(b"correct-priceless-backdrop", current_backdrop.read_bytes())

            with connect(db) as connection:
                row = connection.execute(
                    "SELECT media_type,tmdb_id,poster_path,backdrop_path FROM tmdb_work_links WHERE work_id=?",
                    (work_id,),
                ).fetchone()
                self.assertEqual(row["media_type"], "tv")
                self.assertEqual(int(row["tmdb_id"]), 70203)
                self.assertEqual(row["poster_path"], "/correct-priceless-poster.jpg")
                self.assertEqual(row["backdrop_path"], "/correct-priceless-backdrop.jpg")

            # The generated marker must make the repair one-shot.
            second = sync_tmdb_library(
                db,
                images,
                reports,
                "token",
                client=client,
                image_downloader=downloader,
            )
            self.assertEqual(client.detail_calls, [(70203, "ja-JP")])
            self.assertEqual(second["summary"]["matched"], 1)


if __name__ == "__main__":
    unittest.main()
