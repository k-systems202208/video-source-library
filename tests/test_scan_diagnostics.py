from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from database import connect, initialize_database, now_iso
from scan_diagnostics import diagnostics_csv_bytes, diagnostics_json_bytes, scan_diagnostics


def seed(db: Path) -> int:
    stamp = now_iso()
    with connect(db) as c:
        initialize_database(c)
        c.execute("INSERT INTO works(external_work_no,category,official_title,media_file_count,subtitle_file_count,subfolder_count,created_at,updated_at) VALUES(1,'日本映画・ドラマ','診断テスト作品',2,1,1,?,?)", (stamp, stamp))
        work_id = int(c.execute("SELECT id FROM works WHERE external_work_no=1").fetchone()[0])
        c.execute("INSERT INTO videos(work_id,external_file_no,official_title,episode_or_type,episode_sort_key,episode_title,content_type,created_at,updated_at) VALUES(?,1,'診断テスト作品','第1話','000001','第1話','EPISODE',?,?)", (work_id, stamp, stamp))
        video1 = int(c.execute("SELECT id FROM videos WHERE external_file_no=1").fetchone()[0])
        c.execute("INSERT INTO video_files(video_id,filename,relative_path,extension,file_size,modified_time_ns,is_available,scan_status,created_at,updated_at) VALUES(?,'Episode01.mkv','old/Show/Episode01.mkv','MKV',123456,100,0,'MISSING',?,?)", (video1, stamp, stamp))
        c.execute("INSERT INTO videos(work_id,external_file_no,official_title,episode_or_type,episode_sort_key,episode_title,content_type,created_at,updated_at) VALUES(?,2,'診断テスト作品','第2話','000002','第2話','EPISODE',?,?)", (work_id, stamp, stamp))
        video2 = int(c.execute("SELECT id FROM videos WHERE external_file_no=2").fetchone()[0])
        c.execute("INSERT INTO video_files(video_id,filename,relative_path,extension,file_size,modified_time_ns,is_available,scan_status,created_at,updated_at) VALUES(?,'Movie.mkv','show/Movie.mkv','MKV',987654,200,1,'MATCHED',?,?)", (video2, stamp, stamp))
        cur = c.execute("INSERT INTO scan_runs(started_at,completed_at,status,files_found,files_matched,files_missing,files_new,subtitles_found,subtitles_matched,subtitles_unmatched,probe_errors,errors,duration_ms,created_at) VALUES(?,?,'SUCCESS',2,1,1,1,1,0,1,1,1,1000,?)", (stamp, stamp, stamp))
        run_id = int(cur.lastrowid)
        c.execute("INSERT INTO scan_discoveries(scan_run_id,relative_path,extension,file_size,modified_time_ns,status,created_at) VALUES(?,'new/Show/Episode01.mkv','MKV',123456,300,'NEW_FILE',?)", (run_id, stamp))
        c.execute("INSERT INTO subtitles(video_id,relative_path,filename,extension,language,is_forced,is_default,match_method,file_size,modified_time_ns,is_available,last_scanned_at,created_at,updated_at) VALUES(NULL,'show/Movie.commentary.srt','Movie.commentary.srt','SRT',NULL,0,0,'UNMATCHED',1234,400,1,?,?,?)", (stamp, stamp, stamp))
        c.execute("INSERT INTO scan_errors(scan_run_id,relative_path,error_type,message,created_at) VALUES(?,'show/Movie.mkv','PROBE_ERROR','probe failed',?)", (run_id, stamp))
        c.commit()
        return run_id


class ScanDiagnosticsTests(unittest.TestCase):
    def test_candidates_are_visible_but_database_is_not_mutated(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "library.db"
            run_id = seed(db)
            with connect(db) as c:
                value = scan_diagnostics(c)
                self.assertEqual(value["scan"]["runId"], run_id)
                self.assertEqual(value["summary"]["missing"], 1)
                self.assertEqual(value["summary"]["newFiles"], 1)
                self.assertEqual(value["summary"]["unmatchedSubtitles"], 1)
                self.assertEqual(value["summary"]["errors"], 1)
                self.assertEqual(value["missing"][0]["candidates"][0]["confidence"], "HIGH")
                self.assertEqual(value["missing"][0]["candidates"][0]["relativePath"], "new/Show/Episode01.mkv")
                self.assertEqual(value["unmatchedSubtitles"][0]["candidates"][0]["videoId"], 2)
                self.assertIsNone(c.execute("SELECT video_id FROM subtitles WHERE relative_path='show/Movie.commentary.srt'").fetchone()[0])
                self.assertEqual(c.execute("SELECT scan_status FROM video_files WHERE relative_path='old/Show/Episode01.mkv'").fetchone()[0], "MISSING")

            exported_json = diagnostics_json_bytes(value).decode("utf-8")
            exported_csv = diagnostics_csv_bytes(value)
            self.assertIn("診断テスト作品", exported_json)
            self.assertTrue(exported_csv.startswith(b"\xef\xbb\xbf"))
            text = exported_csv[3:].decode("utf-8")
            self.assertIn("MISSING_CANDIDATE", text)
            self.assertIn("SUBTITLE_CANDIDATE", text)
            self.assertIn("PROBE_ERROR", text)

    def test_empty_database_has_empty_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "library.db"
            with connect(db) as c:
                initialize_database(c)
                value = scan_diagnostics(c)
            self.assertIsNone(value["scan"])
            self.assertEqual(value["missing"], [])
            self.assertEqual(value["unmatchedSubtitles"], [])


if __name__ == "__main__":
    unittest.main()
