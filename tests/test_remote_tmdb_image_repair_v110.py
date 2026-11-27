from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from tmdb_images import cached_image_path, resolve_or_repair_cached_tmdb_image


class RemoteTmdbImageRepairTests(unittest.TestCase):
    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute(
            """
            CREATE TABLE tmdb_work_links(
                work_id INTEGER PRIMARY KEY,
                match_status TEXT NOT NULL,
                poster_path TEXT,
                backdrop_path TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO tmdb_work_links(work_id,match_status,poster_path,backdrop_path) VALUES(1,'MATCHED','/poster.jpg','/backdrop.jpg')"
        )
        return connection

    def test_missing_poster_cache_is_repaired_on_demand(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            connection = self._connection()
            calls = []

            def fake_download(remote_path, destination, *, size):
                calls.append((remote_path, size))
                destination = Path(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"poster")
                return destination

            resolved = resolve_or_repair_cached_tmdb_image(
                connection, root, 1, "poster", image_downloader=fake_download
            )
            self.assertIsNotNone(resolved)
            self.assertEqual(calls, [("/poster.jpg", "w500")])
            self.assertEqual(resolved[0], cached_image_path(root, 1, "poster", "/poster.jpg"))
            self.assertEqual(resolved[1], "image/jpeg")
            connection.close()

    def test_existing_cache_does_not_redownload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            connection = self._connection()
            target = cached_image_path(root, 1, "backdrop", "/backdrop.jpg")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"backdrop")

            def should_not_download(*args, **kwargs):
                self.fail("existing TMDb image cache must not be downloaded again")

            resolved = resolve_or_repair_cached_tmdb_image(
                connection, root, 1, "backdrop", image_downloader=should_not_download
            )
            self.assertEqual(resolved[0], target)
            self.assertEqual(resolved[1], "image/jpeg")
            connection.close()

    def test_unmatched_work_is_not_repaired(self):
        with tempfile.TemporaryDirectory() as tmp:
            connection = self._connection()
            connection.execute("UPDATE tmdb_work_links SET match_status='REVIEW' WHERE work_id=1")
            calls = []

            def fake_download(*args, **kwargs):
                calls.append(args)

            self.assertIsNone(
                resolve_or_repair_cached_tmdb_image(
                    connection, Path(tmp), 1, "poster", image_downloader=fake_download
                )
            )
            self.assertEqual(calls, [])
            connection.close()


if __name__ == "__main__":
    unittest.main()
