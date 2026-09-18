from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
CONFIG = (ROOT / "browser-e2e" / "playwright.config.js").read_text(encoding="utf-8")
SPEC = (ROOT / "browser-e2e" / "tests" / "library.spec.js").read_text(encoding="utf-8")
SERVER = (ROOT / "scripts" / "run_browser_e2e_server.py").read_text(encoding="utf-8")
PACKAGE = (ROOT / "browser-e2e" / "package.json").read_text(encoding="utf-8")


class PlaywrightBrowserE2ECITests(unittest.TestCase):
    def test_ci_has_browser_e2e_job_and_installer_depends_on_it(self):
        self.assertIn("browser-e2e:", WORKFLOW)
        self.assertIn("Run browser E2E", WORKFLOW)
        self.assertIn("npx playwright install chromium", WORKFLOW)
        self.assertIn("needs: [test, playback-formats, browser-e2e]", WORKFLOW)

    def test_three_viewport_projects_exist(self):
        for name in ("PC", "Tablet", "Smartphone"):
            self.assertIn(f"name: '{name}'", CONFIG)
        self.assertIn("width: 1440, height: 900", CONFIG)
        self.assertIn("width: 1024, height: 768", CONFIG)
        self.assertIn("width: 390, height: 844", CONFIG)

    def test_requested_browser_scenarios_are_present(self):
        for label in ("上映中", "次回上映", "作品目録", "監督／演出", "主な出演者／声優"):
            self.assertIn(label, SPEC)
        self.assertIn("initial view starts at the header and renders the catalog", SPEC)
        self.assertIn("work cards open the work detail screen", SPEC)
        self.assertIn("responsive shell matches PC, Tablet, and Smartphone behavior", SPEC)
        self.assertIn("cast directory shows profile photos, fallback, and opens person works", SPEC)
        self.assertIn("tmdb-person-image", SPEC)
        self.assertIn("pageerror", SPEC)

    def test_e2e_server_uses_synthetic_fixture(self):
        self.assertIn("build_metadata(work_count=12, video_count=24)", SERVER)
        self.assertIn('host="127.0.0.1"', SERVER)
        self.assertIn("create_server(", SERVER)

    def test_playwright_version_is_pinned(self):
        self.assertIn('"@playwright/test": "1.55.0"', PACKAGE)


if __name__ == "__main__":
    unittest.main()
