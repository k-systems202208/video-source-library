from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from app_version import APP_VERSION


class ReleaseV100Tests(unittest.TestCase):
    def test_release_version_and_docs_are_fixed(self):
        self.assertEqual(APP_VERSION, "1.0.0")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        notes = (ROOT / "docs" / "39-1.0.0-release.md").read_text(encoding="utf-8")
        self.assertIn("### 1.0.0: 正式版", readme)
        self.assertIn("実動画4,845件", readme)
        self.assertIn("applicationNoRoute = 0", readme)
        self.assertIn("元データ異常24件", readme)
        self.assertIn("DIRECT: 1,826件", notes)
        self.assertIn("TRANSCODE: 3,019件", notes)
        self.assertIn("repairCandidateCount = 0", notes)

    def test_installer_is_1_0_0(self):
        installer = (ROOT / "windows-installer" / "installer" / "VideoLibrary.iss").read_text(encoding="utf-8")
        self.assertIn('#define MyAppVersion "1.0.0"', installer)


if __name__ == "__main__":
    unittest.main()
