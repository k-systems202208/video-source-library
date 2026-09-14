from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from launcher import (
    BODY_FONT,
    MAIN_PADDING,
    MONO_FONT,
    SMALL_FONT,
    STATUS_FONT,
    TITLE_FONT,
    UI_FONT,
    WINDOW_GEOMETRY,
    WINDOW_MINSIZE,
)


class LauncherUiParityTests(unittest.TestCase):
    def test_music_library_visual_tokens_are_shared(self):
        self.assertEqual(UI_FONT, "Yu Gothic UI")
        self.assertEqual(WINDOW_GEOMETRY, "780x690")
        self.assertEqual(WINDOW_MINSIZE, (700, 590))
        self.assertEqual(MAIN_PADDING, 18)
        self.assertEqual(TITLE_FONT, ("Yu Gothic UI", 20, "bold"))
        self.assertEqual(BODY_FONT, ("Yu Gothic UI", 10))
        self.assertEqual(SMALL_FONT, ("Yu Gothic UI", 9))
        self.assertEqual(STATUS_FONT, ("Yu Gothic UI", 10, "bold"))
        self.assertEqual(MONO_FONT, ("Consolas", 9))

    def test_launcher_keeps_video_features_inside_music_style_shell(self):
        source = (SRC / "launcher.py").read_text(encoding="utf-8")
        self.assertIn('ttk.LabelFrame(main, text="動画フォルダー", padding=10)', source)
        self.assertIn('ttk.LabelFrame(main, text="メタデータJSON", padding=10)', source)
        self.assertIn('ttk.LabelFrame(main, text="外部接続（Tailscale）", padding=10)', source)
        self.assertIn('ttk.Button(button_frame, text="データ保存先を開く"', source)
        self.assertIn('ttk.LabelFrame(main, text="起動スキャン", padding=10)', source)
        self.assertNotIn('font=("Segoe UI"', source)


if __name__ == "__main__":
    unittest.main()
