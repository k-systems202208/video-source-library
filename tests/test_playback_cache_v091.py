from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from playback_cache import (
    DEFAULT_CACHE_LIMIT_BYTES,
    clear_playback_cache,
    format_bytes,
    mark_playback_cache_used,
    playback_cache_stats,
    prune_playback_cache,
)


class PlaybackCacheV091Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cache = Path(self.temp.name) / "PlaybackCache"
        self.cache.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, name: str, size: int, age_seconds: int = 0) -> Path:
        path = self.cache / name
        path.write_bytes(b"x" * size)
        when = time.time() - age_seconds
        os.utime(path, (when, when))
        return path

    def test_default_limit_is_20_gib(self):
        self.assertEqual(DEFAULT_CACHE_LIMIT_BYTES, 20 * 1024**3)

    def test_stats_count_only_completed_mp4(self):
        self._write("a.mp4", 100)
        self._write("b.mp4", 200)
        self._write("c.partial.mp4", 300)
        (self.cache / "note.txt").write_text("ignore", encoding="utf-8")
        stats = playback_cache_stats(self.cache)
        self.assertEqual((stats.file_count, stats.total_bytes), (2, 300))

    def test_prune_removes_oldest_and_preserves_protected(self):
        old = self._write("old.mp4", 100, age_seconds=300)
        middle = self._write("middle.mp4", 100, age_seconds=200)
        newest = self._write("new.mp4", 100, age_seconds=100)
        result = prune_playback_cache(self.cache, limit_bytes=150, protected=(middle,))
        self.assertFalse(old.exists())
        self.assertTrue(middle.exists())
        self.assertFalse(newest.exists())
        self.assertEqual(result.remaining_bytes, 100)
        self.assertEqual(result.removed_files, 2)

    def test_mark_used_moves_entry_to_newest_side(self):
        first = self._write("first.mp4", 100, age_seconds=300)
        second = self._write("second.mp4", 100, age_seconds=200)
        before = first.stat().st_mtime_ns
        mark_playback_cache_used(first)
        self.assertGreaterEqual(first.stat().st_mtime_ns, before)
        prune_playback_cache(self.cache, limit_bytes=100)
        self.assertTrue(first.exists())
        self.assertFalse(second.exists())

    def test_clear_removes_completed_and_partial_but_not_unrelated_files(self):
        self._write("a.mp4", 100)
        self._write("b.partial.mp4", 200)
        other = self.cache / "keep.txt"
        other.write_text("keep", encoding="utf-8")
        result = clear_playback_cache(self.cache)
        self.assertEqual(result.removed_files, 2)
        self.assertEqual(playback_cache_stats(self.cache).file_count, 0)
        self.assertTrue(other.exists())

    def test_launcher_exposes_cache_status_and_clear_button(self):
        text = (SRC / "launcher.py").read_text(encoding="utf-8")
        self.assertIn("再生キャッシュ", text)
        self.assertIn("キャッシュをすべて削除", text)
        self.assertIn("refresh_cache_status", text)
        self.assertIn("clear_playback_cache", text)

    def test_format_bytes(self):
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(1024**3), "1.0 GB")


if __name__ == "__main__":
    unittest.main()
