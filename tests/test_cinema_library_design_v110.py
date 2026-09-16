from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "windows-installer" / "src" / "video-library.html"
MANIFEST = ROOT / "windows-installer" / "src" / "manifest.webmanifest"
LAUNCHER = ROOT / "windows-installer" / "src" / "launcher.py"


class CinemaLibraryDesignV110Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML.read_text(encoding="utf-8")
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.launcher = LAUNCHER.read_text(encoding="utf-8")

    def test_brand_name_is_consistent(self):
        self.assertIn("<title>シネマ蔵書館</title>", self.html)
        self.assertIn("<h1>シネマ蔵書館</h1>", self.html)
        self.assertEqual(self.manifest["name"], "シネマ蔵書館")
        self.assertEqual(self.manifest["short_name"], "シネマ蔵書館")
        self.assertIn('APP_NAME = "シネマ蔵書館"', self.launcher)

    def test_classic_cinema_theme_markers_are_present(self):
        self.assertIn("cinema-library-theme-v1", self.html)
        self.assertIn("--wine:#741c22", self.html)
        self.assertIn('font-family:"Yu Mincho"', self.html)
        self.assertIn("#c9a45b", self.html)

    def test_cinema_language_keeps_existing_section_ids(self):
        self.assertIn('id="continueSection" class="home-strip" hidden><h2>上映中</h2>', self.html)
        self.assertIn('id="nextSection" class="home-strip" hidden><h2>次回上映</h2>', self.html)
        self.assertIn('id="back">← 作品目録</button>', self.html)
        self.assertIn('id="continueStrip"', self.html)
        self.assertIn('id="nextStrip"', self.html)
        self.assertIn('id="works"', self.html)

    def test_functional_controls_are_preserved(self):
        for control_id in ("search", "sort", "scanButton", "loadMore", "playerModal", "scanModal"):
            self.assertIn(f'id="{control_id}"', self.html)
        self.assertIn("TMDb同期", self.launcher)

    def test_manifest_uses_matching_dark_cinema_colors(self):
        self.assertEqual(self.manifest["background_color"], "#100c0a")
        self.assertEqual(self.manifest["theme_color"], "#1a100d")


if __name__ == "__main__":
    unittest.main()
