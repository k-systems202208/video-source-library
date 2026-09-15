from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from playback_audit import parse_audit_probe_payload, summarize_audit, verify_playback_sample
from playback_compat import browser_direct_playback, browser_transcode_codec_args, normalize_video_extension


class PlaybackAuditV094Tests(unittest.TestCase):
    def test_direct_detection_accepts_database_extensions_without_dot(self) -> None:
        mp4 = {
            "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
            "streams": [
                {"index": 0, "codec_type": "video", "codec_name": "h264"},
                {"index": 1, "codec_type": "audio", "codec_name": "aac", "tags": {"language": "jpn"}},
            ],
        }
        webm = {
            "format": {"format_name": "matroska,webm"},
            "streams": [
                {"index": 0, "codec_type": "video", "codec_name": "vp9"},
                {"index": 1, "codec_type": "audio", "codec_name": "opus"},
            ],
        }
        self.assertEqual(parse_audit_probe_payload(mp4, extension="mp4", ffmpeg_available=True).route, "DIRECT")
        self.assertEqual(parse_audit_probe_payload(webm, extension="webm", ffmpeg_available=True).route, "DIRECT")
        self.assertTrue(browser_direct_playback("mp4", "h264", "aac"))
        self.assertTrue(browser_direct_playback("webm", "vp9", "opus"))
        self.assertEqual(normalize_video_extension("MP4"), ".mp4")

    def test_subtitle_payload_registered_as_video_is_distinguished(self) -> None:
        for format_name in ("ass", "srt", "subrip"):
            payload = {
                "format": {"format_name": format_name},
                "streams": [{"index": 0, "codec_type": "subtitle", "codec_name": format_name}],
            }
            result = parse_audit_probe_payload(payload, extension="mkv", ffmpeg_available=True)
            self.assertEqual(result.route, "NO_ROUTE")
            self.assertEqual(result.reason, "SUBTITLE_CONTENT_REGISTERED_AS_VIDEO")
            self.assertEqual(result.embedded_subtitle_count, 1)

    def test_real_no_video_container_keeps_no_video_stream_reason(self) -> None:
        payload = {
            "format": {"format_name": "matroska,webm"},
            "streams": [{"index": 0, "codec_type": "audio", "codec_name": "aac"}],
        }
        result = parse_audit_probe_payload(payload, extension="mkv", ffmpeg_available=True)
        self.assertEqual(result.reason, "NO_VIDEO_STREAM")

    def test_direct_sample_is_decode_only(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        with mock.patch("playback_audit.subprocess.run", return_value=completed) as run:
            ok, error = verify_playback_sample(
                Path("direct.mp4"),
                preferred_audio_index=1,
                ffmpeg_path=Path("ffmpeg"),
                route="DIRECT",
            )
        self.assertTrue(ok, error)
        command = run.call_args.args[0]
        self.assertNotIn("libx264", command)
        self.assertNotIn("-c:a", command)
        self.assertEqual(command[-3:], ["-f", "null", "-"])

    def test_transcode_sample_uses_h264_aac_and_stereo_normalization(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        with mock.patch("playback_audit.subprocess.run", return_value=completed) as run:
            ok, error = verify_playback_sample(
                Path("source.mkv"),
                preferred_audio_index=2,
                ffmpeg_path=Path("ffmpeg"),
                route="TRANSCODE",
            )
        self.assertTrue(ok, error)
        command = run.call_args.args[0]
        self.assertIn("libx264", command)
        self.assertIn("aac", command)
        ac = command.index("-ac")
        self.assertEqual(command[ac + 1], "2")

    def test_production_transcode_codec_profile_normalizes_audio_to_stereo(self) -> None:
        args = browser_transcode_codec_args()
        self.assertIn("libx264", args)
        self.assertIn("aac", args)
        ac = args.index("-ac")
        self.assertEqual(args[ac + 1], "2")

    def test_summary_counts_misregistered_subtitle_content(self) -> None:
        summary = summarize_audit(
            [
                {"extension": "mkv", "route": "NO_ROUTE", "reason": "SUBTITLE_CONTENT_REGISTERED_AS_VIDEO", "audioCodecs": []},
                {"extension": "mp4", "route": "DIRECT", "reason": "", "audioCodecs": ["aac"]},
            ]
        )
        self.assertEqual(summary["subtitleContentRegisteredAsVideo"], 1)
        self.assertEqual(summary["noVideoStream"], 0)
        self.assertEqual(summary["noRoute"], 1)


if __name__ == "__main__":
    unittest.main()
