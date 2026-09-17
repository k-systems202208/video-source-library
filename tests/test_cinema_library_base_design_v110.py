from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "windows-installer" / "src" / "video-library.html"

class CinemaLibraryBaseDesignV110Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML.read_text(encoding="utf-8")
    def test_brand_is_cinema_library(self):
        self.assertIn("<title>シネマ蔵書館</title>", self.html)
        self.assertIn("映画で、また会える。", self.html)
        self.assertIn("PRIVATE CINEMA ARCHIVE", self.html)
    def test_theater_language_is_used(self):
        for value in ("上映中", "NOW SHOWING", "次回上映", "COMING SOON", "← 作品目録"):
            self.assertIn(value, self.html)
    def test_classic_design_marker_and_palette_exist(self):
        for value in ("CINEMA_LIBRARY_BASE_DESIGN_V1", "--cinema-red:#6f171b", "--brass:#b88b3e", "Yu Mincho"):
            self.assertIn(value, self.html)
    def test_existing_functional_ids_are_preserved(self):
        for value in ("scanButton", "continueSection", "nextSection", "search", "sort", "works", "workDetail", "playerModal"):
            self.assertIn(f'id="{value}"', self.html)
    def test_display_version_is_not_changed_by_design(self):
        version = (ROOT / "windows-installer" / "src" / "app_version.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "1.1.0"', version)

if __name__ == "__main__":
    unittest.main()
