from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from playback_audit import AuditProbe, _repair_candidate_score, audit_real_library
from database import connect, initialize_database


class PlaybackAuditV096Tests(unittest.TestCase):
    def test_episode_match_is_prioritized(self) -> None:
        target = Path("Show E01.mkv")
        same = Path("Show Episode 01 1080p.mp4")
        other = Path("Show E02.mp4")
        same_score, same_reason = _repair_candidate_score(target, same)
        other_score, other_reason = _repair_candidate_score(target, other)
        self.assertEqual(same_reason, "EPISODE_MATCH")
        self.assertEqual(other_reason, "EPISODE_MISMATCH")
        self.assertGreater(same_score, other_score)

    def test_audit_adds_same_folder_video_candidate_without_modifying_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "videos"
            root.mkdir()
            target = root / "Show E01.mkv"
            candidate = root / "Show Episode 01.mp4"
            wrong_episode = root / "Show E02.mp4"
            target.write_text("subtitle", encoding="utf-8")
            candidate.write_bytes(b"video-one")
            wrong_episode.write_bytes(b"video-two")
            before = target.read_bytes()
            db = Path(temp) / "library.db"
            with connect(db) as connection:
                initialize_database(connection)
                stamp = "2026-09-15T00:00:00+09:00"
                connection.execute("INSERT INTO works(external_work_no,category,official_title,created_at,updated_at) VALUES(1,'ドラマ','Show',?,?)", (stamp, stamp))
                work_id = int(connection.execute("SELECT id FROM works").fetchone()[0])
                connection.execute("INSERT INTO videos(work_id,external_file_no,official_title,episode_or_type,episode_title,episode_sort_key,created_at,updated_at) VALUES(?,1,'Show','01','Episode 1','0001',?,?)", (work_id, stamp, stamp))
                video_id = int(connection.execute("SELECT id FROM videos").fetchone()[0])
                connection.execute("INSERT INTO video_files(video_id,filename,relative_path,extension,created_at,updated_at) VALUES(?, 'Show E01.mkv','Show E01.mkv','mkv',?,?)", (video_id, stamp, stamp))
                connection.commit()

            subtitle_probe = AuditProbe(status="OK", container_format="srt", embedded_subtitle_count=1, route="NO_ROUTE", reason="SUBTITLE_CONTENT_REGISTERED_AS_VIDEO")
            video_probe = AuditProbe(status="OK", container_format="mov,mp4", video_codec="h264", audio_codecs=("aac",), audio_track_count=1, route="DIRECT")

            def fake_probe(source: Path, **kwargs):
                return subtitle_probe if source.name == target.name else video_probe

            with mock.patch("playback_audit.find_ffprobe", return_value=Path("ffprobe")), mock.patch("playback_audit.find_ffmpeg", return_value=Path("ffmpeg")), mock.patch("playback_audit.probe_for_audit", side_effect=fake_probe):
                report = audit_real_library(db, root, Path(temp) / "out")

            item = report["items"][0]
            self.assertEqual(report["summary"]["sourceDataErrors"], 1)
            self.assertEqual(report["summary"]["sourceDataErrorsWithCandidates"], 1)
            self.assertEqual(report["summary"]["sourceDataErrorsWithoutCandidates"], 0)
            self.assertGreaterEqual(item["repairCandidateCount"], 1)
            self.assertEqual(item["repairCandidates"][0]["relativePath"], candidate.name)
            self.assertEqual(item["repairCandidates"][0]["reason"], "EPISODE_MATCH")
            self.assertNotIn(str(root), str(item["repairCandidates"]))
            self.assertEqual(target.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
