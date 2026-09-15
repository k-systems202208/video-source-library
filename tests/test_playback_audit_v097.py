from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from playback_audit import AuditProbe, _find_repair_candidates, summarize_audit


class PlaybackAuditV097Tests(unittest.TestCase):
    def _video_probe(self) -> AuditProbe:
        return AuditProbe(
            status="OK",
            container_format="mov,mp4",
            video_codec="h264",
            audio_codecs=("aac",),
            audio_track_count=1,
            route="DIRECT",
        )

    def test_episode_mismatch_is_not_repair_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "Show E01.mkv"
            source.write_text("subtitle", encoding="utf-8")
            (root / "Show E02.mp4").write_bytes(b"video")
            (root / "Show E03.mp4").write_bytes(b"video")

            with mock.patch("playback_audit.probe_for_audit", return_value=self._video_probe()):
                candidates = _find_repair_candidates(
                    source,
                    video_root=root,
                    ffprobe_path=Path("ffprobe"),
                    ffmpeg_available=True,
                    directory_cache={},
                )

            self.assertEqual(candidates, [])

    def test_same_episode_alternate_name_remains_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "Show E01.mkv"
            source.write_text("subtitle", encoding="utf-8")
            (root / "Show Episode 01 remux.mp4").write_bytes(b"video")
            (root / "Show E02.mp4").write_bytes(b"video")

            with mock.patch("playback_audit.probe_for_audit", return_value=self._video_probe()):
                candidates = _find_repair_candidates(
                    source,
                    video_root=root,
                    ffprobe_path=Path("ffprobe"),
                    ffmpeg_available=True,
                    directory_cache={},
                )

            self.assertEqual(len(candidates), 1)
            self.assertIn("Episode 01", candidates[0]["relativePath"])
            self.assertEqual(candidates[0]["reason"], "EPISODE_MATCH")

    def test_summary_counts_only_valid_candidates(self) -> None:
        items = [
            {
                "route": "NO_ROUTE",
                "reason": "SUBTITLE_CONTENT_REGISTERED_AS_VIDEO",
                "repairCandidateCount": 0,
                "extension": "mkv",
            },
            {
                "route": "NO_ROUTE",
                "reason": "SUBTITLE_CONTENT_REGISTERED_AS_VIDEO",
                "repairCandidateCount": 1,
                "extension": "mkv",
            },
        ]
        summary = summarize_audit(items)
        self.assertEqual(summary["sourceDataErrorsWithCandidates"], 1)
        self.assertEqual(summary["sourceDataErrorsWithoutCandidates"], 1)


if __name__ == "__main__":
    unittest.main()
