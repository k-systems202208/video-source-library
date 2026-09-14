from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from playback_compat import REAL_LIBRARY_VIDEO_EXTENSIONS
from scanner import SUPPORTED_VIDEO_EXTENSIONS


class RealLibraryFormatCoverageTests(unittest.TestCase):
    def test_all_current_real_library_extensions_have_ci_playback_coverage(self):
        fixture = json.loads(
            (ROOT / "tests" / "fixtures" / "real_library_video_extensions.json").read_text(encoding="utf-8")
        )
        extensions = {str(value).casefold() for value in fixture["extensions"]}
        self.assertEqual(int(fixture["total"]), 4869)
        self.assertEqual(sum(int(value) for value in fixture["extensions"].values()), 4869)
        self.assertEqual(extensions, {".mkv", ".mp4", ".avi", ".webm", ".mpg", ".flv"})
        self.assertEqual(extensions, REAL_LIBRARY_VIDEO_EXTENSIONS)
        self.assertTrue(extensions.issubset(SUPPORTED_VIDEO_EXTENSIONS))


if __name__ == "__main__":
    unittest.main()
