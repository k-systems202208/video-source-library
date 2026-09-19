from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SRC)); sys.path.insert(0, str(TESTS))

from database import SCHEMA_VERSION, connect, initialize_database
from library_service import get_video, library_stats
from media_probe import ProbeResult, parse_probe_payload, playback_support
from metadata_importer import import_file
from sample_metadata import build_metadata
from scanner import normalize_relative_path, scan_library
from subtitle_tools import match_subtitle_to_video


class ProbeTests(unittest.TestCase):
    def test_parse_ffprobe_payload(self):
        payload = {
            "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "123.456"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080},
                {"codec_type": "audio", "codec_name": "aac"},
                {"codec_type": "subtitle", "codec_name": "mov_text"},
            ],
        }
        result = parse_probe_payload(payload, extension=".mp4")
        self.assertEqual(result.status, "OK")
        self.assertEqual(result.duration_ms, 123456)
        self.assertEqual(result.video_codec, "h264")
        self.assertEqual(result.audio_codec, "aac")
        self.assertEqual((result.width, result.height), (1920, 1080))
        self.assertEqual(result.embedded_subtitle_count, 1)
        self.assertEqual(result.playback_support, "DIRECT")

    def test_playback_support_is_conservative(self):
        self.assertEqual(playback_support(".mp4", "h264", "aac"), "DIRECT")
        self.assertEqual(playback_support(".mp4", "hevc", "aac"), "UNKNOWN")
        self.assertEqual(playback_support(".mkv", "h264", "aac"), "UNKNOWN")
        self.assertEqual(playback_support(".webm", "vp9", "opus"), "DIRECT")


class SubtitleTests(unittest.TestCase):
    def test_exact_and_language_suffix_matching(self):
        videos = ["show/episode01.mkv", "show/episode02.mkv"]
        exact = match_subtitle_to_video("show/episode01.srt", videos)
        self.assertEqual(exact.video_relative_path, "show/episode01.mkv")
        self.assertEqual(exact.match_method, "EXACT_STEM")
        ja = match_subtitle_to_video("show/episode02.ja.forced.srt", videos)
        self.assertEqual(ja.video_relative_path, "show/episode02.mkv")
        self.assertEqual(ja.language, "ja")
        self.assertTrue(ja.is_forced)
        self.assertEqual(ja.match_method, "LANGUAGE_SUFFIX")

    def test_unknown_suffix_is_not_guessed(self):
        videos = ["show/episode01.mkv"]
        value = match_subtitle_to_video("show/episode01.commentary.srt", videos)
        self.assertIsNone(value.video_relative_path)
        self.assertEqual(value.match_method, "UNMATCHED")


class SchemaAndScannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.db = base / "library.db"
        self.video_root = base / "videos"
        self.video_root.mkdir()
        self.metadata = base / "fixture.json"
        self.payload = build_metadata(work_count=6, video_count=6)
        self.metadata.write_text(json.dumps(self.payload, ensure_ascii=False), encoding="utf-8")
        import_file(self.metadata, self.db)
        first = self.payload["works"][0]["files"][0]
        relative = normalize_relative_path(first["relative_path"])
        self.video = self.video_root.joinpath(*relative.split("/"))
        self.video.parent.mkdir(parents=True, exist_ok=True)
        self.video.write_bytes(b"fake-video")
        self.video.with_suffix(".ja.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n字幕\n", encoding="utf-8")
        self.video.with_suffix(".en.vtt").write_text("WEBVTT\n", encoding="utf-8")
        (self.video.parent / "orphan.srt").write_text("orphan", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def good_probe() -> ProbeResult:
        return ProbeResult(
            status="OK",
            container_format="mov,mp4,m4a,3gp,3g2,mj2",
            duration_ms=98765,
            video_codec="h264",
            audio_codec="aac",
            width=1280,
            height=720,
            embedded_subtitle_count=1,
            playback_support="DIRECT",
        )

    def test_schema8_and_tables(self):
        with connect(self.db) as connection:
            initialize_database(connection)
            version = int(connection.execute("SELECT schema_version FROM schema_info").fetchone()[0])
            self.assertEqual(version, 8)
            self.assertEqual(SCHEMA_VERSION, 8)
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='subtitles'").fetchone())
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tmdb_people'").fetchone())
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tmdb_work_people'").fetchone())
            columns = {row[1] for row in connection.execute("PRAGMA table_info(video_files)").fetchall()}
            self.assertTrue({"probe_status", "probed_at", "embedded_subtitle_count"}.issubset(columns))

    def test_scan_saves_probe_and_subtitles_without_paths_in_api(self):
        with patch("scanner.find_ffprobe", return_value=Path("fake-ffprobe")), patch("scanner.probe_media", return_value=self.good_probe()):
            with connect(self.db) as connection:
                result = scan_library(connection, self.video_root)
                self.assertTrue(result["ffprobeAvailable"])
                self.assertEqual(result["filesProbed"], 1)
                self.assertEqual(result["subtitlesFound"], 3)
                self.assertEqual(result["subtitlesMatched"], 3)
                self.assertEqual(result["subtitlesUnmatched"], 0)
                video_id = int(connection.execute("SELECT id FROM videos WHERE external_file_no=1").fetchone()[0])
                detail = get_video(connection, video_id)
                self.assertEqual(detail["file"]["videoCodec"], "h264")
                self.assertEqual(detail["file"]["audioCodec"], "aac")
                self.assertEqual(detail["file"]["durationMs"], 98765)
                self.assertEqual(detail["file"]["embeddedSubtitleCount"], 1)
                self.assertEqual(len(detail["subtitles"]), 3)
                serialized = json.dumps(detail, ensure_ascii=False)
                self.assertNotIn(str(self.video_root), serialized)
                self.assertNotIn("relativePath", serialized)
                self.assertNotIn("relative_path", serialized)
                stats = library_stats(connection)
                self.assertEqual(stats["subtitles"], 3)
                self.assertEqual(stats["matchedSubtitles"], 3)
                self.assertEqual(stats["unmatchedSubtitles"], 0)
                self.assertEqual(stats["probedVideos"], 1)

    def test_video_is_probed_after_ffprobe_becomes_available(self):
        with patch("scanner.find_ffprobe", return_value=None):
            with connect(self.db) as connection:
                first = scan_library(connection, self.video_root)
                self.assertFalse(first["ffprobeAvailable"])
                status = connection.execute("SELECT probe_status FROM video_files WHERE is_available=1").fetchone()[0]
                self.assertEqual(status, "NOT_AVAILABLE")
        with patch("scanner.find_ffprobe", return_value=Path("fake-ffprobe")), patch("scanner.probe_media", return_value=self.good_probe()):
            with connect(self.db) as connection:
                second = scan_library(connection, self.video_root)
                self.assertEqual(second["filesProbed"], 1)
                row = connection.execute("SELECT probe_status,video_codec FROM video_files WHERE is_available=1").fetchone()
                self.assertEqual(tuple(row), ("OK", "h264"))


class PackagingTests(unittest.TestCase):
    def test_packaging_files_exist_and_keep_data_outside_install_dir(self):
        spec = (ROOT / "windows-installer" / "build" / "VideoLibrary.spec").read_text(encoding="utf-8")
        iss = (ROOT / "windows-installer" / "installer" / "VideoLibrary.iss").read_text(encoding="utf-8")
        build = (ROOT / "windows-installer" / "build" / "build.ps1").read_text(encoding="utf-8")
        sw = (ROOT / "windows-installer" / "src" / "service-worker.js").read_text(encoding="utf-8")
        self.assertIn("launcher.py", spec)
        self.assertIn("video-library.html", spec)
        self.assertIn("tools", spec)
        self.assertIn("PrivilegesRequired=lowest", iss)
        self.assertIn("{localappdata}\\Programs\\VideoLibrary", iss)
        self.assertIn("NOT removed", iss)
        self.assertIn("PyInstaller", build)
        self.assertIn("ISCC.exe", build)
        self.assertIn("video-library-shell-v5", sw)
        self.assertIn("/api/", sw)
        self.assertIn("/video/", sw)
        self.assertIn("/subtitle/", sw)


if __name__ == "__main__":
    unittest.main()
