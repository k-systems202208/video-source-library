from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "windows-installer" / "src" / "launcher.py"


class PlaybackAuditLauncherV092Tests(unittest.TestCase):
    def test_launcher_exposes_full_playback_audit(self) -> None:
        text = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("from playback_audit import audit_real_library", text)
        self.assertIn('text="全件再生監査"', text)
        self.assertIn("def start_playback_audit", text)
        self.assertIn('PLAYBACK_AUDIT_OUTPUT_PATH = DATA_ROOT / "diagnostics"', text)
        self.assertIn("DIRECT {direct:,} / 互換変換 {transcode:,} / ", text)
        self.assertIn("アプリ再生不可 {application_no_route:,} / 元データ異常 {source_errors:,}", text)
        self.assertIn("実動画の再生互換性は合格です", text)
        self.assertIn("sourceErrorsCsvReport", text)


if __name__ == "__main__":
    unittest.main()
