from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'windows-installer'/'src'/'video-library.html').read_text(encoding='utf-8')
SERVER=(ROOT/'windows-installer'/'src'/'server.py').read_text(encoding='utf-8')
SPEC=(ROOT/'windows-installer'/'build'/'VideoLibrary.spec').read_text(encoding='utf-8')

class ImageResponsiveCinemaUiTests(unittest.TestCase):
    def test_image_assets_are_served_and_packaged(self):
        for name in ('cinema-header.svg','cinema-sidebar.svg','cinema-footer.svg'):
            self.assertIn(name,SERVER)
            self.assertIn(name,SPEC)
            self.assertTrue((ROOT/'windows-installer'/'src'/name).is_file())
    def test_responsive_shell_exists(self):
        self.assertIn('CINEMA_IMAGE_RESPONSIVE_V1',HTML)
        self.assertIn('id="cinemaNav"',HTML)
        self.assertIn('id="mobileMenuToggle"',HTML)
        self.assertIn('@media(min-width:1200px)',HTML)
        self.assertIn('@media(min-width:768px) and (max-width:1199px)',HTML)
        self.assertIn('@media(max-width:767px)',HTML)
    def test_header_search_reuses_existing_search(self):
        self.assertIn('id="headerSearch"',HTML)
        self.assertIn("$('search').dispatchEvent(new Event('input'",HTML)
    def test_existing_features_remain(self):
        self.assertIn('FEATURE PRESENTATION',HTML)
        self.assertIn('上映プログラム',HTML)
        self.assertIn('上映目録',HTML)
        self.assertIn('const PAGE=60',HTML)
        self.assertIn('/api/me/continue-watching',HTML)
        self.assertIn('/api/me/next-up',HTML)

if __name__=='__main__': unittest.main()
