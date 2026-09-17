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

    def test_header_is_centered_full_width_and_header_controls_are_removed(self):
        self.assertIn('SEKIMACHI_KITA_CINEMA_HEADER_V1',HTML)
        self.assertIn('<title>関町北映画館</title>',HTML)
        self.assertIn('<strong>関町北映画館</strong>',HTML)
        self.assertNotIn('シネマ蔵書館',HTML)
        self.assertNotIn('id="headerSearch"',HTML)
        self.assertNotIn('id="scanButton"',HTML)
        self.assertNotIn('映画で、また会える。',HTML)
        self.assertIn('justify-content:center!important',HTML)
        self.assertIn('width:100%!important;max-width:none!important',HTML)
        self.assertIn('min-height:112px;padding:16px 0 18px!important',HTML)
        self.assertIn('min-height:96px;padding:12px 0!important',HTML)
        self.assertIn('min-height:74px;padding:8px 0!important',HTML)

    def test_catalog_copy_and_initial_scroll_behavior(self):
        self.assertIn('アーカイブに収められた作品から、次の一本を。',HTML)
        self.assertNotIn('この蔵書館に収められた作品から、次の一本を。',HTML)
        self.assertIn("history.scrollRestoration='manual'",HTML)
        self.assertIn("await route(true)",HTML)
        self.assertIn("showLibraryRoute('catalog',!initial)",HTML)
        self.assertIn("window.scrollTo({top:0,left:0,behavior:'auto'})",HTML)

    def test_remote_image_loading_is_resilient(self):
        self.assertIn('function loadImageResilient',HTML)
        self.assertIn('function loadBackgroundResilient',HTML)
        self.assertIn('_image_retry=',HTML)
        self.assertIn('resolve_or_repair_cached_tmdb_image',SERVER)
        self.assertIn('private, max-age=300',SERVER)

    def test_existing_features_remain(self):
        self.assertIn('FEATURE PRESENTATION',HTML)
        self.assertIn('上映プログラム',HTML)
        self.assertIn('上映目録',HTML)
        self.assertIn('const PAGE=60',HTML)
        self.assertIn('/api/me/continue-watching',HTML)
        self.assertIn('/api/me/next-up',HTML)

if __name__=='__main__': unittest.main()
