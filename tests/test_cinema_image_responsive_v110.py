from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "windows-installer" / "src" / "video-library.html"
SERVER = ROOT / "windows-installer" / "src" / "server.py"
SPEC = ROOT / "windows-installer" / "build" / "VideoLibrary.spec"
SW = ROOT / "windows-installer" / "src" / "service-worker.js"
SRC = ROOT / "windows-installer" / "src"


class CinemaImageResponsiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = HTML.read_text(encoding="utf-8")
        cls.server = SERVER.read_text(encoding="utf-8")
        cls.spec = SPEC.read_text(encoding="utf-8")
        cls.sw = SW.read_text(encoding="utf-8")

    def test_decorative_svg_assets_exist(self) -> None:
        for name in ("cinema-header.svg", "cinema-sidebar.svg", "cinema-footer.svg"):
            self.assertTrue((SRC / name).is_file(), name)
            self.assertIn(name, self.server)
            self.assertIn(name, self.spec)
            self.assertIn("/" + name, self.sw)

    def test_image_chrome_marker_and_assets_are_used(self) -> None:
        self.assertIn("CINEMA_LIBRARY_IMAGE_RESPONSIVE_V5", self.html)
        self.assertIn("url('/cinema-header.svg')", self.html)
        self.assertIn("url('/cinema-sidebar.svg')", self.html)
        self.assertIn("url('/cinema-footer.svg')", self.html)

    def test_desktop_tablet_and_mobile_breakpoints_exist(self) -> None:
        self.assertIn("@media(min-width:1200px)", self.html)
        self.assertIn("@media(min-width:768px) and (max-width:1199px)", self.html)
        self.assertIn("@media(max-width:767px)", self.html)

    def test_mobile_drawer_and_bottom_navigation_exist(self) -> None:
        self.assertIn('id="cinemaMenuToggle"', self.html)
        self.assertIn('id="cinemaSidebar"', self.html)
        self.assertIn('id="cinemaDrawerOverlay"', self.html)
        self.assertIn("cinema-bottom-nav", self.html)
        self.assertIn("aria-expanded", self.html)

    def test_existing_interactions_are_retained(self) -> None:
        for marker in (
            "上映中 <small>NOW SHOWING</small>",
            "次回上映 <small>COMING SOON</small>",
            'id="search"',
            'id="scanButton"',
            "FEATURE PRESENTATION",
            "makeOpenable",
            "person-link",
        ):
            self.assertIn(marker, self.html)

    def test_display_version_is_unchanged(self) -> None:
        version = (ROOT / "windows-installer" / "src" / "app_version.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "1.1.0"', version)


if __name__ == "__main__":
    unittest.main()
