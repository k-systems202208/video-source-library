from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from database import connect, now_iso
from library_service import get_video
from metadata_importer import import_file
from sample_metadata import build_metadata
from server import create_server
from subtitle_stream import subtitle_bytes_to_webvtt


class SubtitleConversionV080Tests(unittest.TestCase):
    def test_srt_is_converted_to_webvtt(self):
        raw = "1\r\n00:00:01,250 --> 00:00:03,500\r\nこんにちは\r\n".encode("utf-8")
        text = subtitle_bytes_to_webvtt(raw, ".srt").decode("utf-8")
        self.assertTrue(text.startswith("WEBVTT\n\n"))
        self.assertIn("00:00:01.250 --> 00:00:03.500", text)
        self.assertIn("こんにちは", text)

    def test_cp932_srt_is_supported(self):
        raw = "1\n00:00:01,000 --> 00:00:02,000\n日本語字幕\n".encode("cp932")
        text = subtitle_bytes_to_webvtt(raw, "srt").decode("utf-8")
        self.assertIn("日本語字幕", text)

    def test_vtt_is_normalized_without_double_header(self):
        raw = b"WEBVTT\r\n\r\n00:00:01.000 --> 00:00:02.000\r\nHello\r\n"
        text = subtitle_bytes_to_webvtt(raw, ".vtt").decode("utf-8")
        self.assertEqual(text.count("WEBVTT"), 1)
        self.assertIn("Hello", text)

    def test_ass_and_ssa_dialogue_are_converted(self):
        source = """[Script Info]\nTitle: Test\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:01.20,0:00:03.45,Default,,0,0,0,,{\\an8}一行目\\N二行目\n"""
        for extension in (".ass", ".ssa"):
            with self.subTest(extension=extension):
                text = subtitle_bytes_to_webvtt(source.encode("utf-8"), extension).decode("utf-8")
                self.assertIn("00:00:01.200 --> 00:00:03.450", text)
                self.assertIn("一行目\n二行目", text)
                self.assertNotIn("an8", text)


class SubtitleHttpV080Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.db = base / "library.db"
        self.root = base / "videos"
        self.root.mkdir()
        metadata = base / "fixture.json"
        metadata.write_text(json.dumps(build_metadata(work_count=4, video_count=4), ensure_ascii=False), encoding="utf-8")
        import_file(metadata, self.db)
        with connect(self.db) as connection:
            row = connection.execute("SELECT id FROM videos ORDER BY id LIMIT 1").fetchone()
            self.video_id = int(row["id"])
            stamp = now_iso()
            self.subtitle = self.root / "episode.jpn.srt"
            self.subtitle.write_text("1\n00:00:01,000 --> 00:00:02,500\n字幕テスト\n", encoding="utf-8")
            connection.execute(
                """
                INSERT INTO subtitles(video_id,relative_path,filename,extension,language,is_forced,is_default,
                    match_method,is_available,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (self.video_id, "episode.jpn.srt", "episode.jpn.srt", ".srt", "ja", 0, 0,
                 "TEST", 1, stamp, stamp),
            )
            self.subtitle_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
            outside = base / "outside.srt"
            outside.write_text("1\n00:00:00,000 --> 00:00:01,000\noutside\n", encoding="utf-8")
            connection.execute(
                """
                INSERT INTO subtitles(video_id,relative_path,filename,extension,language,is_forced,is_default,
                    match_method,is_available,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (self.video_id, "../outside.srt", "outside.srt", ".srt", "en", 0, 0,
                 "TEST", 1, stamp, stamp),
            )
            self.outside_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
            connection.commit()
        self.server = create_server(self.db, host="127.0.0.1", port=0, video_root=self.root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def test_subtitle_endpoint_returns_webvtt_without_exposing_source_path(self):
        with urlopen(f"{self.base}/subtitle/{self.subtitle_id}.vtt") as response:
            body = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
            self.assertTrue(response.headers.get("Content-Type", "").startswith("text/vtt"))
            self.assertEqual(response.headers.get("Cache-Control"), "no-store")
            self.assertIn("WEBVTT", body)
            self.assertIn("字幕テスト", body)
            self.assertNotIn(str(self.root), body)

    def test_missing_and_root_escape_subtitles_are_not_served(self):
        for subtitle_id in (999999, self.outside_id):
            with self.subTest(subtitle_id=subtitle_id):
                with self.assertRaises(HTTPError) as ctx:
                    urlopen(f"{self.base}/subtitle/{subtitle_id}.vtt")
                self.assertEqual(ctx.exception.code, 404)


class SubtitlePreferenceV080Tests(unittest.TestCase):
    def test_video_api_prefers_japanese_then_default_and_marks_one_preferred(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            db = base / "library.db"
            metadata = base / "fixture.json"
            metadata.write_text(json.dumps(build_metadata(work_count=4, video_count=4), ensure_ascii=False), encoding="utf-8")
            import_file(metadata, db)
            with connect(db) as connection:
                video_id = int(connection.execute("SELECT id FROM videos ORDER BY id LIMIT 1").fetchone()[0])
                stamp = now_iso()
                rows = [
                    ("english.default.srt", "en", 0, 1),
                    ("japanese.srt", "ja", 0, 0),
                    ("unknown.srt", None, 0, 0),
                ]
                for filename, language, forced, default in rows:
                    connection.execute(
                        """
                        INSERT INTO subtitles(video_id,relative_path,filename,extension,language,is_forced,is_default,
                            match_method,is_available,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (video_id, filename, filename, ".srt", language, forced, default, "TEST", 1, stamp, stamp),
                    )
                connection.commit()
                value = get_video(connection, video_id)
            self.assertIsNotNone(value)
            subtitles = value["subtitles"]
            self.assertEqual(subtitles[0]["language"], "ja")
            self.assertTrue(subtitles[0]["preferred"])
            self.assertEqual(sum(1 for item in subtitles if item["preferred"]), 1)

    def test_player_contains_external_tracks_and_default_on_logic(self):
        html = (SRC / "video-library.html").read_text(encoding="utf-8")
        self.assertIn("function attachExternalSubtitles", html)
        self.assertIn("/subtitle/${s.id}.vtt", html)
        self.assertIn("t.default=i===preferred", html)
        self.assertIn("'showing'", html)
        self.assertIn("attachExternalSubtitles(p,v.subtitles||[])", html)

    def test_service_worker_does_not_cache_subtitles(self):
        sw = (SRC / "service-worker.js").read_text(encoding="utf-8")
        self.assertIn("url.pathname.startsWith('/subtitle/')", sw)


if __name__ == "__main__":
    unittest.main()
