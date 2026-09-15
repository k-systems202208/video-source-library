from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from playback_audit import summarize_audit, write_audit_reports


class PlaybackAuditV095Tests(unittest.TestCase):
    def test_summary_separates_application_route_and_source_data_errors(self) -> None:
        summary = summarize_audit([
            {"extension": "mkv", "route": "NO_ROUTE", "reason": "SUBTITLE_CONTENT_REGISTERED_AS_VIDEO", "audioCodecs": []},
            {"extension": "mp4", "route": "DIRECT", "reason": "", "videoCodec": "h264", "audioCodecs": ["aac"]},
            {"extension": "avi", "route": "TRANSCODE", "reason": "BROWSER_INCOMPATIBLE_OR_TRACK_SELECTION", "videoCodec": "mpeg4", "audioCodecs": ["mp3"]},
        ])
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["playableVideoTotal"], 2)
        self.assertEqual(summary["noRoute"], 1)
        self.assertEqual(summary["applicationNoRoute"], 0)
        self.assertEqual(summary["sourceDataErrors"], 1)
        self.assertEqual(summary["subtitleContentRegisteredAsVideo"], 1)

    def test_real_playback_failure_stays_application_no_route(self) -> None:
        summary = summarize_audit([
            {"extension": "mkv", "route": "NO_ROUTE", "reason": "DECODE_ERROR", "videoCodec": "hevc", "audioCodecs": ["aac"]}
        ])
        self.assertEqual(summary["playableVideoTotal"], 1)
        self.assertEqual(summary["applicationNoRoute"], 1)
        self.assertEqual(summary["sourceDataErrors"], 0)

    def test_source_error_csv_contains_only_source_data_errors(self) -> None:
        bad = {
            "videoId": 1, "externalFileNo": 10, "title": "bad", "episode": "ep1", "relativePath": "bad.mkv", "extension": "mkv",
            "containerFormat": "ass", "videoCodec": "", "videoProfile": "", "pixelFormat": "", "audioCodecs": [], "audioLanguages": [],
            "audioTrackCount": 0, "hasJapaneseAudio": False, "preferredAudioIndex": None, "preferredAudioCodec": "", "preferredAudioLanguage": "",
            "externalSubtitleCount": 0, "embeddedSubtitleCount": 1, "sampleDecode": "NOT_RUN", "route": "NO_ROUTE",
            "reason": "SUBTITLE_CONTENT_REGISTERED_AS_VIDEO", "error": "",
        }
        good = dict(bad)
        good.update({"videoId": 2, "externalFileNo": 11, "title": "good", "relativePath": "good.mp4", "extension": "mp4",
                     "containerFormat": "mov,mp4,m4a,3gp,3g2,mj2", "videoCodec": "h264", "audioCodecs": ["aac"],
                     "audioLanguages": ["jpn"], "audioTrackCount": 1, "sampleDecode": "PASS", "route": "DIRECT", "reason": ""})
        report = {"summary": {}, "items": [bad, good]}
        with tempfile.TemporaryDirectory() as temp:
            _, _, source_errors = write_audit_reports(Path(temp), report, stamp="test")
            with source_errors.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "bad")
        self.assertEqual(rows[0]["reason"], "SUBTITLE_CONTENT_REGISTERED_AS_VIDEO")

    def test_launcher_displays_application_and_source_results_separately(self) -> None:
        text = (SRC / "launcher.py").read_text(encoding="utf-8")
        self.assertIn("アプリ再生不可", text)
        self.assertIn("元データ異常", text)
        self.assertIn("sourceErrorsCsvReport", text)
        self.assertIn("実動画の再生互換性は合格です", text)


if __name__ == "__main__":
    unittest.main()
