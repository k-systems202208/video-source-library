from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from scan_progress import ScanProgressStore


class ScanProgressStoreTests(unittest.TestCase):
    def test_progress_snapshot_and_completion(self):
        store = ScanProgressStore()
        store.start()
        store.update({
            "phase": "SCANNING",
            "message": "動画ファイルを走査中",
            "current": 25,
            "total": 100,
            "filesMatched": 20,
            "filesNew": 5,
            "currentItem": "Drama/episode01.mkv",
        })
        time.sleep(0.001)
        running = store.snapshot()
        self.assertTrue(running["running"])
        self.assertEqual(running["percent"], 25)
        self.assertEqual(running["filesMatched"], 20)
        self.assertEqual(running["currentItem"], "Drama/episode01.mkv")
        self.assertGreaterEqual(running["elapsedMs"], 0)

        store.complete({"filesMatched": 95, "filesMissing": 3, "filesNew": 2})
        completed = store.snapshot()
        self.assertFalse(completed["running"])
        self.assertEqual(completed["phase"], "SUCCESS")
        self.assertEqual(completed["filesMatched"], 95)
        self.assertIsNone(completed["currentItem"])

    def test_failure_is_reported_without_resetting_counts(self):
        store = ScanProgressStore()
        store.start()
        store.update({"filesMatched": 12, "current": 15, "total": 100})
        store.fail("boom")
        failed = store.snapshot()
        self.assertFalse(failed["running"])
        self.assertEqual(failed["phase"], "FAILED")
        self.assertEqual(failed["filesMatched"], 12)
        self.assertEqual(failed["error"], "boom")


if __name__ == "__main__":
    unittest.main()
