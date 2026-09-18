from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from tmdb_images import (
    cached_image_path,
    resolve_cached_tmdb_image,
    resolve_or_repair_cached_tmdb_image,
)


class TmdbWorkImageCacheTests(unittest.TestCase):
    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute(
            """
            CREATE TABLE tmdb_work_links (
                work_id INTEGER PRIMARY KEY,
                match_status TEXT NOT NULL,
                poster_path TEXT,
                backdrop_path TEXT
            )
            """
        )
        return connection

    def test_cache_path_changes_when_tmdb_remote_path_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            movie = cached_image_path(root, 153, "poster", "/movie-poster.jpg")
            tv = cached_image_path(root, 153, "poster", "/tv-poster.jpg")

            self.assertNotEqual(movie, tv)
            self.assertEqual(movie.parent, root / "poster")
            self.assertEqual(tv.parent, root / "poster")
            self.assertTrue(movie.name.startswith("153-"))
            self.assertTrue(tv.name.startswith("153-"))
            self.assertEqual(movie.suffix, ".jpg")
            self.assertEqual(tv.suffix, ".jpg")

    def test_legacy_work_id_only_cache_is_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "poster" / "153.jpg"
            legacy.parent.mkdir(parents=True, exist_ok=True)
            legacy.write_bytes(b"old-movie-image")

            connection = self._connection()
            try:
                connection.execute(
                    """
                    INSERT INTO tmdb_work_links(work_id,match_status,poster_path,backdrop_path)
                    VALUES(153,'MATCHED','/tv-current.jpg','/tv-current-bg.jpg')
                    """
                )
                connection.commit()

                self.assertIsNone(resolve_cached_tmdb_image(connection, root, 153, "poster"))
                self.assertEqual(legacy.read_bytes(), b"old-movie-image")
            finally:
                connection.close()

    def test_on_demand_repair_downloads_current_tmdb_image_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            connection = self._connection()
            calls: list[tuple[str, Path, str]] = []
            try:
                connection.execute(
                    """
                    INSERT INTO tmdb_work_links(work_id,match_status,poster_path,backdrop_path)
                    VALUES(153,'MATCHED','/tv-current.jpg','/tv-current-bg.jpg')
                    """
                )
                connection.commit()

                def downloader(remote_path, destination, *, size):
                    target = Path(destination)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(f"downloaded:{remote_path}".encode("utf-8"))
                    calls.append((remote_path, target, size))
                    return target

                poster = resolve_or_repair_cached_tmdb_image(
                    connection,
                    root,
                    153,
                    "poster",
                    image_downloader=downloader,
                )
                backdrop = resolve_or_repair_cached_tmdb_image(
                    connection,
                    root,
                    153,
                    "backdrop",
                    image_downloader=downloader,
                )

                self.assertIsNotNone(poster)
                self.assertIsNotNone(backdrop)
                poster_path, poster_type = poster
                backdrop_path, backdrop_type = backdrop

                self.assertEqual(
                    poster_path,
                    cached_image_path(root, 153, "poster", "/tv-current.jpg"),
                )
                self.assertEqual(
                    backdrop_path,
                    cached_image_path(root, 153, "backdrop", "/tv-current-bg.jpg"),
                )
                self.assertEqual(poster_path.read_bytes(), b"downloaded:/tv-current.jpg")
                self.assertEqual(backdrop_path.read_bytes(), b"downloaded:/tv-current-bg.jpg")
                self.assertEqual(poster_type, "image/jpeg")
                self.assertEqual(backdrop_type, "image/jpeg")
                self.assertEqual(
                    [(remote, size) for remote, _target, size in calls],
                    [
                        ("/tv-current.jpg", "w500"),
                        ("/tv-current-bg.jpg", "w1280"),
                    ],
                )
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
