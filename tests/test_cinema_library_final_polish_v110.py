import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML = ROOT / "windows-installer" / "src" / "video-library.html"


class CinemaLibraryFinalPolishV110Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML.read_text(encoding="utf-8")

    def test_final_polish_marker_and_poster_placeholder_exist(self):
        self.assertIn("CINEMA_LIBRARY_FINAL_POLISH", self.html)
        self.assertIn("function posterFallback", self.html)
        self.assertIn("POSTER NOT AVAILABLE", self.html)
        self.assertIn("poster-fallback-mark", self.html)
        self.assertNotIn(".trim().slice(0,1)", self.html)

    def test_screening_strips_have_scroll_guidance(self):
        self.assertIn('class="strip-shell"', self.html)
        self.assertIn('class="strip-scroll-hint"', self.html)
        self.assertIn("function setupStripNavigation", self.html)
        self.assertIn("function updateStripHint", self.html)
        self.assertIn("scrollBy", self.html)
        self.assertIn("pointer:fine", self.html)

    def test_catalog_and_screening_cards_are_keyboard_openable(self):
        self.assertIn("c.tabIndex=0", self.html)
        self.assertIn("c.setAttribute('role','button')", self.html)
        self.assertIn("c.onkeydown", self.html)
        self.assertIn("focus-visible", self.html)

    def test_existing_catalog_and_detail_design_remain(self):
        self.assertIn("CINEMA_LIBRARY_CATALOG_V3", self.html)
        self.assertIn("CINEMA_LIBRARY_DETAIL_V2", self.html)
        self.assertIn("作品目録", self.html)
        self.assertIn("上映プログラム", self.html)
        self.assertIn("上映目録", self.html)


if __name__ == "__main__":
    unittest.main()
