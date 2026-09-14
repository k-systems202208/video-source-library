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
        self.assertIn("DIRECT {direct:,} / 互換変換 {transcode:,} / 再生経路なし {no_route:,}", text)
        self.assertIn("v1.0受入条件（再生経路なし0件）", text)


if __name__ == "__main__":
    unittest.main()
