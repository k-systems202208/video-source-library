from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from database import connect, initialize_database, now_iso
from scan_diagnostics import diagnostics_csv_bytes, scan_diagnostics
import scan_runner
from scan_runner import record_unsupported_subtitles
import server


class UnsupportedSubtitleDiagnostics072Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.db = base / "library.db"
        self.video_root = base / "videos"
        self.video_root.mkdir()
        work = self.video_root / "movie_jpn" / "Liar Game"
        work.mkdir(parents=True)
        (work / "movie.idx").write_bytes(b"idx")
        (work / "movie.sub").write_bytes(b"sub")
        (work / "movie.smi").write_text("<SAMI></SAMI>", encoding="utf-8")
        (work / "ignore.txt").write_text("not subtitle", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def _success_run(self, connection) -> int:
        stamp = now_iso()
        cursor = connection.execute(
            """
            INSERT INTO scan_runs(
                started_at, completed_at, status,
                files_found, files_matched, files_missing, files_new,
                subtitles_found, subtitles_matched, subtitles_unmatched,
                probe_errors, errors, duration_ms, created_at
            ) VALUES (?, ?, 'SUCCESS', 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, ?)
            """,
            (stamp, stamp, stamp),
        )
        connection.commit()
        return int(cursor.lastrowid)

    def test_only_idx_sub_smi_are_recorded_as_diagnostics(self):
        with connect(self.db) as connection:
            initialize_database(connection)
            run_id = self._success_run(connection)
            count = record_unsupported_subtitles(connection, self.video_root, run_id)
            self.assertEqual(count, 3)
            rows = connection.execute(
                """
                SELECT extension, status FROM scan_discoveries
                WHERE scan_run_id=? ORDER BY extension
                """,
                (run_id,),
            ).fetchall()
            self.assertEqual(
                [(row["extension"], row["status"]) for row in rows],
                [
                    ("IDX", "UNSUPPORTED_SUBTITLE"),
                    ("SMI", "UNSUPPORTED_SUBTITLE"),
                    ("SUB", "UNSUPPORTED_SUBTITLE"),
                ],
            )
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM subtitles").fetchone()[0], 0)

    def test_diagnostics_and_csv_expose_unsupported_subtitles_separately(self):
        with connect(self.db) as connection:
            initialize_database(connection)
            run_id = self._success_run(connection)
            record_unsupported_subtitles(connection, self.video_root, run_id)
            value = scan_diagnostics(connection, run_id=run_id)
            self.assertEqual(value["summary"]["unsupportedSubtitles"], 3)
            self.assertEqual(len(value["unsupportedSubtitles"]), 3)
            self.assertEqual(value["summary"]["unmatchedSubtitles"], 0)
            exported = diagnostics_csv_bytes(value).decode("utf-8-sig")
            self.assertEqual(exported.count("UNSUPPORTED_SUBTITLE"), 3)
            self.assertIn("movie.idx", exported)
            self.assertIn("movie.sub", exported)
            self.assertIn("movie.smi", exported)

    def test_browser_rescan_uses_same_scan_runner_as_startup_scan(self):
        self.assertIs(server.scan_library, scan_runner.scan_library)
        self.assertEqual(server.APP_VERSION, "0.7.2")


if __name__ == "__main__":
    unittest.main()
