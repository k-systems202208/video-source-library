from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'windows-installer'/'src'/'video-library.html').read_text(encoding='utf-8')

class ResponsiveImageShellTests(unittest.TestCase):
    def test_image_shell_marker_and_svg_images(self):
        self.assertIn('CINEMA_LIBRARY_RESPONSIVE_IMAGE_SHELL_V1',HTML)
        self.assertGreaterEqual(HTML.count('data:image/svg+xml'),3)
    def test_desktop_sidebar_and_navigation(self):
        self.assertIn('id="cinemaNav"',HTML)
        self.assertIn('data-cinema-nav="continue"',HTML)
        self.assertIn('data-cinema-nav="next"',HTML)
        self.assertIn('data-cinema-nav="catalog"',HTML)
        self.assertIn("location.href='/diagnostics.html'",HTML)
    def test_tablet_and_phone_breakpoints(self):
        self.assertIn('@media(max-width:1199px)',HTML)
        self.assertIn('@media(max-width:767px)',HTML)
        self.assertIn('cinema-mobile-nav',HTML)
        self.assertIn('cinema-drawer-backdrop',HTML)
    def test_drawer_accessibility_and_keyboard(self):
        self.assertIn('aria-controls="cinemaNav"',HTML)
        self.assertIn("toggle.setAttribute('aria-expanded'",HTML)
        self.assertIn("e.key==='Escape'",HTML)
    def test_existing_features_remain(self):
        self.assertIn("const PAGE=60",HTML)
        self.assertIn("FEATURE PRESENTATION",HTML)
        self.assertIn("posterFallback",HTML)
        self.assertIn("creditRow",HTML)
        self.assertIn("runScan",HTML)
        self.assertIn("/api/me/works/${w.id}/favorite",HTML)

if __name__=='__main__':unittest.main()
