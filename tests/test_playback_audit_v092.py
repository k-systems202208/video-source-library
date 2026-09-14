from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from database import connect, initialize_database
from playback_audit import AuditProbe, _sanitize_process_error, audit_real_library, parse_audit_probe_payload, summarize_audit, write_audit_reports


class PlaybackAuditV092Tests(unittest.TestCase):
    def test_process_errors_do_not_expose_absolute_source_path(self) -> None:
        source = Path(r"Z:\Files\shared\動画\secret.mkv")
        message = f"{source}: Invalid data found when processing input"
        sanitized = _sanitize_process_error(message, source)
        self.assertNotIn(str(source), sanitized)
        self.assertIn("<video>", sanitized)

    def test_second_japanese_audio_requires_transcode(self) -> None:
        payload = {
            "format": {"format_name": "matroska,webm"},
            "streams": [
                {"index": 0, "codec_type": "video", "codec_name": "h264"},
                {"index": 1, "codec_type": "audio", "codec_name": "aac", "tags": {"language": "eng"}},
                {"index": 2, "codec_type": "audio", "codec_name": "flac", "tags": {"language": "jpn", "title": "Japanese"}},
                {"index": 3, "codec_type": "subtitle", "codec_name": "ass", "tags": {"language": "jpn"}},
            ],
        }
        result = parse_audit_probe_payload(payload, extension=".mkv", ffmpeg_available=True)
        self.assertEqual(result.route, "TRANSCODE")
        self.assertTrue(result.has_japanese_audio)
        self.assertEqual(result.preferred_audio_index, 2)
        self.assertEqual(result.preferred_audio_codec, "flac")
        self.assertEqual(result.audio_track_count, 2)
        self.assertEqual(result.embedded_subtitle_count, 1)

    def test_direct_mp4_is_classified_direct(self) -> None:
        payload = {
            "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
            "streams": [
                {"index": 0, "codec_type": "video", "codec_name": "h264"},
                {"index": 1, "codec_type": "audio", "codec_name": "aac", "tags": {"language": "jpn"}},
            ],
        }
        result = parse_audit_probe_payload(payload, extension=".mp4", ffmpeg_available=True)
        self.assertEqual(result.route, "DIRECT")
        self.assertTrue(result.preferred_audio_is_first)

    def test_non_direct_without_ffmpeg_has_no_route(self) -> None:
        payload = {
            "format": {"format_name": "avi"},
            "streams": [
                {"index": 0, "codec_type": "video", "codec_name": "mpeg4"},
                {"index": 1, "codec_type": "audio", "codec_name": "mp3"},
            ],
        }
        result = parse_audit_probe_payload(payload, extension=".avi", ffmpeg_available=False)
        self.assertEqual((result.route, result.reason), ("NO_ROUTE", "FFMPEG_NOT_AVAILABLE"))

    def test_no_video_stream_has_no_route(self) -> None:
        result = parse_audit_probe_payload(
            {"format": {"format_name": "matroska"}, "streams": [{"codec_type": "audio", "codec_name": "aac"}]},
            extension=".mkv",
            ffmpeg_available=True,
        )
        self.assertEqual((result.route, result.reason), ("NO_ROUTE", "NO_VIDEO_STREAM"))

    def test_summary_counts_routes_audio_and_subtitles(self) -> None:
        items = [
            {"extension": ".mp4", "route": "DIRECT", "videoCodec": "h264", "audioCodecs": ["aac"], "audioTrackCount": 1, "hasJapaneseAudio": True, "externalSubtitleCount": 1, "embeddedSubtitleCount": 0},
            {"extension": ".mkv", "route": "TRANSCODE", "videoCodec": "hevc", "audioCodecs": ["flac", "aac"], "audioTrackCount": 2, "hasJapaneseAudio": True, "externalSubtitleCount": 0, "embeddedSubtitleCount": 2},
            {"extension": ".avi", "route": "NO_ROUTE", "reason": "PROBE_ERROR", "audioCodecs": [], "audioTrackCount": 0, "externalSubtitleCount": 0, "embeddedSubtitleCount": 0},
        ]
        summary = summarize_audit(items)
        self.assertEqual((summary["total"], summary["direct"], summary["transcode"], summary["noRoute"]), (3, 1, 1, 1))
        self.assertEqual(summary["probeErrors"], 1)
        self.assertEqual(summary["withJapaneseAudio"], 2)
        self.assertEqual(summary["multiAudio"], 1)
        self.assertEqual(summary["externalSubtitleFiles"], 1)
        self.assertEqual(summary["embeddedSubtitleStreams"], 2)

    def test_reports_are_json_and_excel_friendly_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = {
                "summary": {"total": 1},
                "items": [{
                    "videoId": 1, "externalFileNo": 1, "title": "日本語", "episode": "01",
                    "relativePath": "anime/test.mkv", "extension": ".mkv", "containerFormat": "matroska",
                    "videoCodec": "h264", "audioCodecs": ["aac", "flac"], "audioLanguages": ["eng", "jpn"],
                    "audioTrackCount": 2, "hasJapaneseAudio": True, "preferredAudioIndex": 2,
                    "preferredAudioCodec": "flac", "preferredAudioLanguage": "jpn", "externalSubtitleCount": 1,
                    "embeddedSubtitleCount": 1, "route": "TRANSCODE", "reason": "", "error": "",
                }],
            }
            json_path, csv_path = write_audit_reports(Path(temp), report, stamp="test")
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["summary"]["total"], 1)
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("anime/test.mkv", csv_text)
            self.assertIn("aac;flac", csv_text)
            self.assertNotIn("C:\\", csv_text)

    def test_real_library_audit_counts_external_subtitles_and_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "videos"
            root.mkdir()
            source = root / "movie.mp4"
            source.write_bytes(b"video")
            db = Path(temp) / "library.db"
            output = Path(temp) / "diagnostics"
            with connect(db) as connection:
                initialize_database(connection)
                stamp = "2026-09-14T00:00:00+09:00"
                connection.execute(
                    "INSERT INTO works(external_work_no,category,official_title,created_at,updated_at) VALUES(1,'映画','作品',?,?)",
                    (stamp, stamp),
                )
                work_id = int(connection.execute("SELECT id FROM works").fetchone()[0])
                connection.execute(
                    "INSERT INTO videos(work_id,external_file_no,official_title,episode_sort_key,created_at,updated_at) VALUES(?,1,'作品','0001',?,?)",
                    (work_id, stamp, stamp),
                )
                video_id = int(connection.execute("SELECT id FROM videos").fetchone()[0])
                connection.execute(
                    "INSERT INTO video_files(video_id,filename,relative_path,extension,created_at,updated_at) VALUES(?, 'movie.mp4','movie.mp4','.mp4',?,?)",
                    (video_id, stamp, stamp),
                )
                connection.execute(
                    "INSERT INTO subtitles(video_id,relative_path,filename,extension,created_at,updated_at) VALUES(?, 'movie.ja.srt','movie.ja.srt','.srt',?,?)",
                    (video_id, stamp, stamp),
                )
                connection.commit()

            fake = AuditProbe(
                status="OK", container_format="mov,mp4", video_codec="h264", audio_codecs=("aac",),
                audio_languages=("jpn",), audio_track_count=1, has_japanese_audio=True,
                preferred_audio_index=1, preferred_audio_codec="aac", preferred_audio_language="jpn",
                embedded_subtitle_count=1, route="DIRECT",
            )
            with mock.patch("playback_audit.find_ffprobe", return_value=Path("ffprobe")), mock.patch(
                "playback_audit.find_ffmpeg", return_value=Path("ffmpeg")
            ), mock.patch("playback_audit.probe_for_audit", return_value=fake), mock.patch(
                "playback_audit.verify_playback_sample", return_value=(True, "")
            ):
                report = audit_real_library(db, root, output)
            self.assertEqual(report["summary"]["total"], 1)
            self.assertEqual(report["summary"]["direct"], 1)
            self.assertEqual(report["summary"]["externalSubtitleFiles"], 1)
            self.assertEqual(report["summary"]["embeddedSubtitleStreams"], 1)
            self.assertTrue(Path(report["jsonReport"]).is_file())
            self.assertTrue(Path(report["csvReport"]).is_file())


if __name__ == "__main__":
    unittest.main()
