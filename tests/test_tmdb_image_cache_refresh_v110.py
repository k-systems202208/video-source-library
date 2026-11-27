from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from tmdb_images import cached_image_path
from tmdb_sync import Candidate, _cache_candidate_images, _image_refresh_flags


def candidate(tmdb_id: int = 19616, poster: str = "/new-poster.jpg", backdrop: str = "/new-backdrop.jpg") -> Candidate:
    return Candidate("tv", tmdb_id, "トリック", "2000", poster, backdrop, "", 1.0, 1.0, 1.0)


class TmdbImageCacheRefreshV110Tests(unittest.TestCase):
    def test_changed_match_forces_both_images_to_refresh(self):
        existing = {
            "match_status": "MATCHED", "media_type": "movie", "tmdb_id": 1812,
            "poster_path": "/old-poster.jpg", "backdrop_path": "/old-backdrop.jpg",
        }
        self.assertEqual(_image_refresh_flags(existing, "MATCHED", candidate()), (True, True))

    def test_unchanged_match_does_not_force_refresh(self):
        c = candidate()
        existing = {
            "match_status": "MATCHED", "media_type": "tv", "tmdb_id": 19616,
            "poster_path": c.poster_path, "backdrop_path": c.backdrop_path,
        }
        self.assertEqual(_image_refresh_flags(existing, "MATCHED", c), (False, False))

    def test_force_refresh_replaces_existing_cached_files(self):
        c = candidate()
        calls = []
        def downloader(remote_path, destination, *, size):
            calls.append((remote_path, size))
            Path(destination).parent.mkdir(parents=True, exist_ok=True)
            Path(destination).write_bytes((remote_path + size).encode("utf-8"))
            return Path(destination)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            poster = cached_image_path(root, 112, "poster", c.poster_path)
            backdrop = cached_image_path(root, 112, "backdrop", c.backdrop_path)
            poster.parent.mkdir(parents=True)
            backdrop.parent.mkdir(parents=True)
            poster.write_bytes(b"wrong poster")
            backdrop.write_bytes(b"wrong backdrop")
            result = _cache_candidate_images(
                112, c, root, image_downloader=downloader,
                force_poster_refresh=True, force_backdrop_refresh=True,
            )
            self.assertEqual(result, (True, True))
            self.assertEqual(calls, [("/new-poster.jpg", "w500"), ("/new-backdrop.jpg", "w1280")])
            self.assertNotEqual(poster.read_bytes(), b"wrong poster")
            self.assertNotEqual(backdrop.read_bytes(), b"wrong backdrop")


if __name__ == "__main__":
    unittest.main()
