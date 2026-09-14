from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "windows-installer" / "src" / "video-library.html"


class AudioPreferenceUiV078Tests(unittest.TestCase):
    def test_player_prefers_japanese_when_audio_track_api_is_available(self):
        html = HTML.read_text(encoding="utf-8")
        self.assertIn("function preferJapaneseAudio(p)", html)
        self.assertIn("lang==='ja'||lang==='jpn'", html)
        self.assertIn("label.includes('japanese')", html)
        self.assertIn("label.includes('日本語')", html)
        self.assertIn("p.addEventListener('loadedmetadata',()=>preferJapaneseAudio(p))", html)
        self.assertIn("p.audioTracks.addEventListener('addtrack',()=>preferJapaneseAudio(p))", html)


if __name__ == "__main__":
    unittest.main()
