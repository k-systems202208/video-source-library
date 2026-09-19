from __future__ import annotations

import sqlite3
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

from database import SCHEMA_VERSION, connect, initialize_database
from library_service import get_work, get_video, list_people, list_works
from metadata_importer import import_metadata
from sample_metadata import build_metadata
from server import create_server
from user_state import (
    continue_watching,
    ensure_local_owner,
    favorite_videos,
    favorite_works,
    history,
    next_up,
    recent_works,
    record_progress,
    set_video_favorite,
    set_work_favorite,
    start_playback,
)
from work_visibility import list_work_visibility, replace_visible_work_ids


class WorkVisibilityV121Tests(unittest.TestCase):
    def _seed_library(self, db: Path, work_count: int = 4, video_count: int = 8) -> dict[str, int]:
        with connect(db) as connection:
            initialize_database(connection)
            import_metadata(
                connection,
                build_metadata(work_count=work_count, video_count=video_count),
            )
            rows = connection.execute(
                "SELECT id,external_work_no FROM works ORDER BY external_work_no"
            ).fetchall()
            work_ids = {int(row["external_work_no"]): int(row["id"]) for row in rows}
            connection.execute(
                "UPDATE works SET director_or_direction='非表示監督',main_cast_or_voice_actors='非表示出演者' WHERE id=?",
                (work_ids[1],),
            )
            connection.execute(
                "UPDATE works SET director_or_direction='表示監督',main_cast_or_voice_actors='表示出演者' WHERE id=?",
                (work_ids[2],),
            )
            connection.execute("UPDATE video_files SET is_available=1")
            owner = ensure_local_owner(connection)
            videos = connection.execute(
                "SELECT id,work_id FROM videos ORDER BY work_id,episode_sort_key,id"
            ).fetchall()
            first_video_by_work: dict[int, int] = {}
            for row in videos:
                first_video_by_work.setdefault(int(row["work_id"]), int(row["id"]))
            connection.commit()
            return {
                "hiddenWork": work_ids[1],
                "visibleWork": work_ids[2],
                "hiddenVideo": first_video_by_work[work_ids[1]],
                "visibleVideo": first_video_by_work[work_ids[2]],
                "owner": int(owner["id"]),
            }

    def test_schema7_database_upgrades_existing_works_to_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "legacy.db"
            raw = sqlite3.connect(db)
            raw.executescript(
                """
                CREATE TABLE schema_info(
                    schema_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO schema_info VALUES(7,'x','x');
                CREATE TABLE works(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    external_work_no INTEGER NOT NULL UNIQUE,
                    category TEXT NOT NULL,
                    official_title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO works(
                    external_work_no,category,official_title,created_at,updated_at
                ) VALUES(1,'テスト','旧作品','x','x');
                """
            )
            raw.commit()
            raw.close()

            with connect(db) as connection:
                initialize_database(connection)
                self.assertEqual(SCHEMA_VERSION, 8)
                self.assertEqual(
                    int(connection.execute("SELECT schema_version FROM schema_info").fetchone()[0]),
                    8,
                )
                self.assertEqual(
                    int(
                        connection.execute(
                            "SELECT is_visible FROM works WHERE external_work_no=1"
                        ).fetchone()["is_visible"]
                    ),
                    1,
                )

    def test_launcher_selection_replaces_visible_set_in_one_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            self._seed_library(db)

            with connect(db) as connection:
                items = list_work_visibility(connection)
                self.assertEqual(len(items), 4)
                self.assertTrue(all(item["visible"] for item in items))

                selected = [int(items[0]["id"]), int(items[2]["id"])]
                result = replace_visible_work_ids(connection, selected)
                self.assertEqual(result, {"total": 4, "visible": 2, "hidden": 2})

                flags = {
                    int(row["id"]): bool(row["is_visible"])
                    for row in connection.execute(
                        "SELECT id,is_visible FROM works ORDER BY id"
                    ).fetchall()
                }
                self.assertEqual(
                    {work_id for work_id, visible in flags.items() if visible},
                    set(selected),
                )

                cleared = replace_visible_work_ids(connection, [])
                self.assertEqual(cleared, {"total": 4, "visible": 0, "hidden": 4})
                self.assertEqual(
                    int(connection.execute("SELECT SUM(is_visible) FROM works").fetchone()[0]),
                    0,
                )

                all_ids = [int(item["id"]) for item in list_work_visibility(connection)]
                restored = replace_visible_work_ids(connection, all_ids)
                self.assertEqual(restored, {"total": 4, "visible": 4, "hidden": 0})

    def test_metadata_reimport_preserves_launcher_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            metadata = build_metadata(work_count=4, video_count=8)
            with connect(db) as connection:
                initialize_database(connection)
                import_metadata(connection, metadata)
                ids = [
                    int(row["id"])
                    for row in connection.execute(
                        "SELECT id FROM works ORDER BY external_work_no"
                    ).fetchall()
                ]
                replace_visible_work_ids(connection, [ids[1], ids[3]])
                import_metadata(connection, metadata)
                selected = {
                    int(row["id"])
                    for row in connection.execute(
                        "SELECT id FROM works WHERE is_visible=1"
                    ).fetchall()
                }
                self.assertEqual(selected, {ids[1], ids[3]})

    def test_hidden_works_are_removed_from_all_browser_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            ids = self._seed_library(db)
            with connect(db) as connection:
                replace_visible_work_ids(connection, [ids["visibleWork"]])

                normal = list_works(connection)
                self.assertNotIn(
                    ids["hiddenWork"], [int(item["id"]) for item in normal["items"]]
                )
                self.assertIsNone(get_work(connection, ids["hiddenWork"], user_id=ids["owner"]))
                self.assertIsNone(get_video(connection, ids["hiddenVideo"], user_id=ids["owner"]))

                directors = list_people(connection, role="director")
                cast = list_people(connection, role="cast")
                self.assertNotIn("非表示監督", [item["name"] for item in directors["items"]])
                self.assertNotIn("非表示出演者", [item["name"] for item in cast["items"]])
                self.assertIn("表示監督", [item["name"] for item in directors["items"]])
                self.assertIn("表示出演者", [item["name"] for item in cast["items"]])

                for work_id, video_id in (
                    (ids["hiddenWork"], ids["hiddenVideo"]),
                    (ids["visibleWork"], ids["visibleVideo"]),
                ):
                    set_work_favorite(connection, ids["owner"], work_id, True)
                    set_video_favorite(connection, ids["owner"], video_id, True)
                    start_playback(connection, ids["owner"], video_id)
                    record_progress(
                        connection,
                        ids["owner"],
                        video_id,
                        position_ms=60_000,
                        duration_ms=600_000,
                        event="pause",
                    )

                self.assertNotIn(
                    ids["hiddenWork"],
                    [int(item["id"]) for item in favorite_works(connection, ids["owner"])["items"]],
                )
                self.assertNotIn(
                    ids["hiddenWork"],
                    [int(item["workId"]) for item in favorite_videos(connection, ids["owner"])["items"]],
                )
                for payload in (
                    continue_watching(connection, ids["owner"]),
                    history(connection, ids["owner"]),
                    recent_works(connection, ids["owner"]),
                    next_up(connection, ids["owner"]),
                ):
                    self.assertNotIn(
                        ids["hiddenWork"],
                        [
                            int(item.get("workId", item.get("id")))
                            for item in payload["items"]
                        ],
                    )

    def test_hidden_work_cannot_be_opened_or_streamed_from_browser(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "library.db"
            ids = self._seed_library(db)
            with connect(db) as connection:
                replace_visible_work_ids(connection, [ids["visibleWork"]])

            server = create_server(
                db,
                host="127.0.0.1",
                port=0,
                video_root=root,
                data_root=root,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                for path in (
                    f"/api/works/{ids['hiddenWork']}",
                    f"/api/videos/{ids['hiddenVideo']}",
                    f"/video/{ids['hiddenVideo']}",
                ):
                    with self.assertRaises(HTTPError) as denied:
                        urlopen(base + path, timeout=10)
                    self.assertEqual(denied.exception.code, 404)

                with urlopen(base + "/api/works?visibility=all", timeout=10) as response:
                    payload = __import__("json").loads(response.read().decode("utf-8"))
                returned_ids = {int(item["id"]) for item in payload["items"]}
                self.assertNotIn(ids["hiddenWork"], returned_ids)
                self.assertIn(ids["visibleWork"], returned_ids)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_browser_has_no_visibility_management_ui_or_api(self):
        html = (SRC / "video-library.html").read_text(encoding="utf-8")
        server = (SRC / "server.py").read_text(encoding="utf-8")
        launcher = (SRC / "launcher.py").read_text(encoding="utf-8")

        for forbidden in (
            "visibilityModeButton",
            "visibilityControls",
            "visibilityHideSelected",
            "visibilityShowSelected",
            "/api/admin/works/visibility",
        ):
            self.assertNotIn(forbidden, html + server)

        self.assertIn('text="表示設定"', launcher)
        self.assertIn("すべて選択 / すべて解除", launcher)
        self.assertIn("list_work_visibility", launcher)
        self.assertIn("replace_visible_work_ids", launcher)


if __name__ == "__main__":
    unittest.main()
