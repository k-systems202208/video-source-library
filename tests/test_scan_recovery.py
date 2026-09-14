from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from database import connect, initialize_database, now_iso
from launcher import recover_interrupted_scans
from scanner import latest_scan_status


class InterruptedScanRecoveryTests(unittest.TestCase):
    def test_recover_interrupted_scan_marks_stale_running_row(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "library.db"
            with connect(db) as connection:
                initialize_database(connection)
                stamp = now_iso()
                connection.execute(
                    "INSERT INTO scan_runs(started_at, status, created_at) VALUES (?, 'RUNNING', ?)",
                    (stamp, stamp),
                )
                connection.commit()

            recovered = recover_interrupted_scans(db)
            self.assertEqual(recovered, 1)

            with connect(db) as connection:
                status = latest_scan_status(connection)
                self.assertFalse(status["running"])
                self.assertEqual(status["latest"]["status"], "INTERRUPTED")
                self.assertIsNotNone(status["latest"]["completedAt"])

    def test_recovery_does_not_change_completed_scan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "library.db"
            with connect(db) as connection:
                initialize_database(connection)
                stamp = now_iso()
                connection.execute(
                    """
                    INSERT INTO scan_runs(started_at, completed_at, status, created_at)
                    VALUES (?, ?, 'SUCCESS', ?)
                    """,
                    (stamp, stamp, stamp),
                )
                connection.commit()

            recovered = recover_interrupted_scans(db)
            self.assertEqual(recovered, 0)

            with connect(db) as connection:
                status = latest_scan_status(connection)
                self.assertFalse(status["running"])
                self.assertEqual(status["latest"]["status"], "SUCCESS")


if __name__ == "__main__":
    unittest.main()
