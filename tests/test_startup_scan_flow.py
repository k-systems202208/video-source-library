from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from launcher import VideoLibraryLauncher, run_startup_scan


class StartupScanFlowTests(unittest.TestCase):
    def test_run_startup_scan_uses_scanner_with_progress_callback(self):
        callback = MagicMock()
        fake_connection = MagicMock(name="connection")
        expected = {"status": "SUCCESS", "filesMatched": 1}

        with patch("launcher.connect") as connect_mock, patch("launcher.scan_library") as scan_mock:
            connect_mock.return_value.__enter__.return_value = fake_connection
            scan_mock.return_value = expected

            actual = run_startup_scan(
                Path("library.db"),
                Path("videos"),
                progress_callback=callback,
            )

        self.assertEqual(actual, expected)
        connect_mock.assert_called_once_with(Path("library.db"))
        scan_mock.assert_called_once_with(
            fake_connection,
            Path("videos"),
            progress_callback=callback,
        )

    def test_success_starts_server_before_opening_browser(self):
        source = inspect.getsource(VideoLibraryLauncher._startup_scan_succeeded)
        self.assertLess(source.index("self._start_http_server"), source.index("self.open_browser"))

    def test_normal_start_launches_background_scan_not_http_server_directly(self):
        source = inspect.getsource(VideoLibraryLauncher.start_library)
        self.assertIn("target=self._startup_scan_worker", source)
        self.assertNotIn("create_server(", source)

    def test_launcher_schedules_automatic_start_when_previous_settings_are_ready(self):
        source = inspect.getsource(VideoLibraryLauncher.__init__)
        self.assertIn("self._auto_start_if_ready", source)


if __name__ == "__main__":
    unittest.main()
