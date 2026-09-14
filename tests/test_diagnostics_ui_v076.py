from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"


class DiagnosticsUiV076Tests(unittest.TestCase):
    def test_scan_header_counts_orphans_as_judged_subtitles(self):
        html = (SRC / "diagnostics.html").read_text(encoding="utf-8")
        self.assertIn(
            "const judged=(Number(scan.subtitlesMatched)||0)+(Number(s.orphanSubtitles)||0);",
            html,
        )
        self.assertIn(
            "字幕判定 ${judged}/${scan.subtitlesFound}（紐付 ${scan.subtitlesMatched}・対応動画なし ${s.orphanSubtitles||0}）",
            html,
        )
        self.assertNotIn(
            "· 字幕 ${scan.subtitlesMatched}/${scan.subtitlesFound}",
            html,
        )

    def test_windows_version_is_076(self):
        launcher = (SRC / "launcher.py").read_text(encoding="utf-8")
        installer = (ROOT / "windows-installer" / "installer" / "VideoLibrary.iss").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "0.7.6"', launcher)
        self.assertIn('#define MyAppVersion "0.7.6"', installer)


if __name__ == "__main__":
    unittest.main()
