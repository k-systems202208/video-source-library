from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from database import connect, foreign_key_error_count, quick_check  # noqa: E402
from metadata_importer import import_file  # noqa: E402
from sample_metadata import ZERO_VIDEO_WORK_NOS, build_metadata  # noqa: E402


class Phase1ImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        temp_root = Path(self.temp.name)
        self.db_path = temp_root / "library.db"
        self.metadata_path = temp_root / "fixture.json"
        self.payload = build_metadata()
        self.metadata_path.write_text(
            json.dumps(self.payload, ensure_ascii=False), encoding="utf-8"
        )
        import_file(self.metadata_path, self.db_path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_exact_master_counts(self) -> None:
        with connect(self.db_path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM works").fetchone()[0], 440)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0], 4869)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM video_files").fetchone()[0], 4869)

    def test_zero_video_works_are_preserved(self) -> None:
        with connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT w.external_work_no, COUNT(v.id) AS video_count
                FROM works w
                LEFT JOIN videos v ON v.work_id = w.id
                GROUP BY w.id
                HAVING COUNT(v.id) = 0
                ORDER BY w.external_work_no
                """
            ).fetchall()
            self.assertEqual(
                [row["external_work_no"] for row in rows],
                sorted(ZERO_VIDEO_WORK_NOS),
            )

    def test_user_work_and_video_states_exist(self) -> None:
        with connect(self.db_path) as connection:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            self.assertIn("user_work_state", tables)
            self.assertIn("user_video_state", tables)

    def test_reimport_preserves_personal_state(self) -> None:
        with connect(self.db_path) as connection:
            now = "2026-09-14T00:00:00+09:00"
            connection.execute(
                "INSERT INTO users(display_name,is_owner,is_active,created_at,updated_at) VALUES ('Owner',1,1,?,?)",
                (now, now),
            )
            user_id = connection.execute("SELECT id FROM users WHERE is_owner=1").fetchone()[0]
            work_id = connection.execute("SELECT id FROM works WHERE external_work_no=1").fetchone()[0]
            video_id = connection.execute("SELECT id FROM videos WHERE external_file_no=1").fetchone()[0]
            connection.execute(
                "INSERT INTO user_work_state(user_id,work_id,favorite,created_at,updated_at) VALUES (?,?,1,?,?)",
                (user_id, work_id, now, now),
            )
            connection.execute(
                """
                INSERT INTO user_video_state(
                    user_id,video_id,favorite,watched,play_count,position_ms,created_at,updated_at
                ) VALUES (?,?,1,0,2,123456,?,?)
                """,
                (user_id, video_id, now, now),
            )
            connection.commit()

        import_file(self.metadata_path, self.db_path)

        with connect(self.db_path) as connection:
            work_state = connection.execute("SELECT favorite FROM user_work_state").fetchone()
            video_state = connection.execute(
                "SELECT favorite, watched, play_count, position_ms FROM user_video_state"
            ).fetchone()
            self.assertEqual(work_state["favorite"], 1)
            self.assertEqual(tuple(video_state), (1, 0, 2, 123456))

    def test_sqlite_integrity(self) -> None:
        with connect(self.db_path) as connection:
            self.assertEqual(quick_check(connection).casefold(), "ok")
            self.assertEqual(foreign_key_error_count(connection), 0)

    def test_external_ids_are_unique(self) -> None:
        with connect(self.db_path) as connection:
            duplicate_works = connection.execute(
                "SELECT COUNT(*) FROM (SELECT external_work_no FROM works GROUP BY external_work_no HAVING COUNT(*) > 1)"
            ).fetchone()[0]
            duplicate_videos = connection.execute(
                "SELECT COUNT(*) FROM (SELECT external_file_no FROM videos GROUP BY external_file_no HAVING COUNT(*) > 1)"
            ).fetchone()[0]
            self.assertEqual(duplicate_works, 0)
            self.assertEqual(duplicate_videos, 0)


if __name__ == "__main__":
    unittest.main()
