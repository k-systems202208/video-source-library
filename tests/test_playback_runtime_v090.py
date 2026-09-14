from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from playback_compat import AudioSelection, browser_direct_playback, prepare_browser_playback


class PlaybackRuntimeV090Tests(unittest.TestCase):
    def test_direct_and_fallback_policy(self) -> None:
        self.assertTrue(browser_direct_playback(".mp4", "h264", "aac"))
        self.assertTrue(browser_direct_playback(".webm", "vp9", "opus"))
        for ext in (".mkv", ".avi", ".mpg", ".flv"):
            self.assertFalse(browser_direct_playback(ext, "h264", "aac"))

    def test_second_japanese_audio_forces_preparation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "movie.mp4"
            source.write_bytes(b"source")
            cached = Path(temp) / "cache" / "converted.mp4"
            cached.parent.mkdir()
            cached.write_bytes(b"converted")
            japanese = AudioSelection(stream_index=2, codec="aac", language="jpn", japanese=True, first_audio=False)
            with mock.patch("playback_compat.preferred_audio_selection", return_value=japanese), mock.patch(
                "playback_compat.transcode_to_browser_mp4", return_value=(cached, "ja")
            ) as transcode:
                prepared = prepare_browser_playback(source, ".mp4", "h264", "aac", Path(temp) / "cache")
            self.assertTrue(prepared.transcoded)
            self.assertEqual(prepared.audio_language, "ja")
            transcode.assert_called_once()

    def test_server_wires_playback_cache_before_range_streaming(self) -> None:
        text = (SRC / "server.py").read_text(encoding="utf-8")
        self.assertIn("prepare_browser_playback", text)
        self.assertIn('app_data_root / "PlaybackCache"', text)
        self.assertIn('"PLAYBACK_PREPARATION_FAILED"', text)
        self.assertIn('"X-Video-Library-Playback"', text)

    def test_browser_player_is_modal_with_head_preflight_and_explicit_error(self) -> None:
        text = (SRC / "video-library.html").read_text(encoding="utf-8")
        self.assertIn('id="playerModal"', text)
        self.assertIn('id="playerClose"', text)
        self.assertIn("method:'HEAD'", text)
        self.assertIn("ブラウザ互換形式を準備しています", text)
        self.assertIn("再生用動画を準備できませんでした", text)
        self.assertIn("Escape", text)

    def test_installer_packages_ffmpeg_and_ffprobe(self) -> None:
        spec = (ROOT / "windows-installer" / "build" / "VideoLibrary.spec").read_text(encoding="utf-8")
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn('("ffprobe.exe", "ffmpeg.exe")', spec)
        self.assertIn("Stage FFmpeg and ffprobe for installer", ci)
        self.assertIn("Copy-Item $ffmpeg.FullName", ci)
        self.assertIn("Copy-Item $ffprobe.FullName", ci)

    def test_version_is_090(self) -> None:
        spec = importlib.util.spec_from_file_location("app_version_v090", SRC / "app_version.py")
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        self.assertEqual(module.APP_VERSION, "0.9.0")
        installer = (ROOT / "windows-installer" / "installer" / "VideoLibrary.iss").read_text(encoding="utf-8")
        self.assertIn('#define MyAppVersion "0.9.0"', installer)


if __name__ == "__main__":
    unittest.main()
