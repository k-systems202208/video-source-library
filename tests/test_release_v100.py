from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReleaseV100Tests(unittest.TestCase):
    def test_v100_acceptance_docs_are_preserved(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        notes = (ROOT / "docs" / "39-1.0.0-release.md").read_text(encoding="utf-8")
        self.assertIn("### 1.0.0: 正式版", readme)
        self.assertIn("実動画4,845件", readme)
        self.assertIn("applicationNoRoute = 0", readme)
        self.assertIn("元データ異常24件", readme)
        self.assertIn("DIRECT: 1,826件", notes)
        self.assertIn("TRANSCODE: 3,019件", notes)
        self.assertIn("repairCandidateCount = 0", notes)


if __name__ == "__main__":
    unittest.main()
