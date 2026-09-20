from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ISS = ROOT / "windows-installer" / "installer" / "VideoLibrary.iss"


class InstallerCloseApplicationTests(unittest.TestCase):
    def test_inno_setup_closes_running_video_library_before_overwrite(self):
        text = ISS.read_text(encoding="utf-8")
        self.assertIn("CloseApplications=yes", text)
        self.assertIn("CloseApplicationsFilter={#MyAppExeName}", text)
        self.assertIn("RestartApplications=no", text)
        self.assertIn('Filename: "{app}\\{#MyAppExeName}"', text)

    def test_display_version_matches_current_release(self):
        text = ISS.read_text(encoding="utf-8")
        self.assertIn('#define MyAppVersion "1.2.3"', text)


if __name__ == "__main__":
    unittest.main()
