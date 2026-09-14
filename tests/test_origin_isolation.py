from __future__ import annotations

import sys
import unittest
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from launcher import APP_VERSION, DEFAULT_PORT, request_local_owner_browser_url


class OriginIsolationTests(unittest.TestCase):
    def test_video_default_port_is_separate_from_music_library(self):
        self.assertEqual(DEFAULT_PORT, 8876)
        self.assertNotEqual(DEFAULT_PORT, 8765)

    def test_owner_bootstrap_stays_on_video_origin(self):
        base = f"http://127.0.0.1:{DEFAULT_PORT}/"
        url = request_local_owner_browser_url(base, "control-" + "x" * 40)
        parsed = urlsplit(url)
        self.assertEqual(parsed.hostname, "127.0.0.1")
        self.assertEqual(parsed.port, 8876)
        self.assertEqual(parsed.path, "/offline.html")
        self.assertEqual(parsed.query, "owner-bootstrap=1")
        self.assertTrue(parsed.fragment.startswith("token="))

    def test_windows_version_is_068(self):
        self.assertEqual(APP_VERSION, "0.6.8")


if __name__ == "__main__":
    unittest.main()
