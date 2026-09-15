from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "windows-installer" / "src" / "launcher.py"


class PlaybackAuditLauncherV096Tests(unittest.TestCase):
    def test_launcher_reports_repair_candidate_counts(self) -> None:
        text = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn('sourceDataErrorsWithCandidates', text)
        self.assertIn('sourceDataErrorsWithoutCandidates', text)
        self.assertIn('修復候補あり', text)
        self.assertIn('修復候補なし', text)
        self.assertIn('元データ異常CSVの修復候補', text)


if __name__ == "__main__":
    unittest.main()
