from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from database import SCHEMA_VERSION, connect, initialize_database, now_iso
from library_service import get_work, list_people, list_works, set_work_visibility
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


class WorkVisibilityV120Tests(unittest.TestCase):
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
                row = connection.execute(
                    "SELECT is_visible FROM works WHERE external_work_no=1"
                ).fetchone()
                self.assertEqual(int(row["is_visible"]), 1)

    def test_metadata_reimport_preserves_hidden_setting(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            metadata = build_metadata(work_count=4, video_count=8)
            with connect(db) as connection:
                initialize_database(connection)
                import_metadata(connection, metadata)
                work_id = int(
                    connection.execute(
                        "SELECT id FROM works WHERE external_work_no=1"
                    ).fetchone()[0]
                )
                set_work_visibility(connection, [work_id], visible=False)
                import_metadata(connection, metadata)
                row = connection.execute(
                    "SELECT is_visible FROM works WHERE id=?", (work_id,)
                ).fetchone()
                self.assertEqual(int(row["is_visible"]), 0)

    def _seed_library(self, db: Path) -> dict[str, int]:
        with connect(db) as connection:
            initialize_database(connection)
            import_metadata(connection, build_metadata(work_count=4, video_count=8))
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

    def test_hidden_works_are_removed_from_normal_catalog_people_and_state_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            ids = self._seed_library(db)
            with connect(db) as connection:
                set_work_visibility(connection, [ids["hiddenWork"]], visible=False)

                normal = list_works(connection)
                self.assertNotIn(
                    ids["hiddenWork"], [int(item["id"]) for item in normal["items"]]
                )
                hidden = list_works(connection, visibility="hidden")
                self.assertEqual(
                    [int(item["id"]) for item in hidden["items"]],
                    [ids["hiddenWork"]],
                )
                self.assertFalse(hidden["items"][0]["visible"])

                detail = get_work(connection, ids["hiddenWork"], user_id=ids["owner"])
                self.assertIsNotNone(detail)
                self.assertFalse(detail["visible"])

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

    def test_http_owner_can_manage_visibility_and_direct_urls_still_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            ids = self._seed_library(db)
            server = create_server(db, host="127.0.0.1", port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                payload = json.dumps(
                    {"workIds": [ids["hiddenWork"]], "visible": False}
                ).encode("utf-8")
                req = Request(
                    base + "/api/admin/works/visibility",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="PUT",
                )
                with urlopen(req, timeout=10) as response:
                    changed = json.loads(response.read().decode("utf-8"))
                self.assertEqual(changed["updated"], 1)
                self.assertFalse(changed["visible"])

                with urlopen(base + "/api/works", timeout=10) as response:
                    normal = json.loads(response.read().decode("utf-8"))
                self.assertNotIn(
                    ids["hiddenWork"], [int(item["id"]) for item in normal["items"]]
                )

                with urlopen(base + "/api/works?visibility=hidden", timeout=10) as response:
                    hidden = json.loads(response.read().decode("utf-8"))
                self.assertEqual(
                    [int(item["id"]) for item in hidden["items"]],
                    [ids["hiddenWork"]],
                )

                with urlopen(
                    base + f"/api/works/{ids['hiddenWork']}", timeout=10
                ) as response:
                    detail = json.loads(response.read().decode("utf-8"))
                self.assertFalse(detail["visible"])

                with urlopen(
                    base + f"/api/videos/{ids['hiddenVideo']}", timeout=10
                ) as response:
                    video = json.loads(response.read().decode("utf-8"))
                self.assertEqual(int(video["work"]["id"]), ids["hiddenWork"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_anonymous_user_cannot_list_or_change_hidden_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "library.db"
            ids = self._seed_library(db)
            with connect(db) as connection:
                set_work_visibility(connection, [ids["hiddenWork"]], visible=False)

            server = create_server(
                db,
                host="127.0.0.1",
                port=0,
                owner_control_secret="test-secret-for-visibility-tests-1234567890",
                data_root=root,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(base + "/api/works", timeout=10) as response:
                    normal = json.loads(response.read().decode("utf-8"))
                self.assertNotIn(
                    ids["hiddenWork"], [int(item["id"]) for item in normal["items"]]
                )

                with self.assertRaises(HTTPError) as denied:
                    urlopen(base + "/api/works?visibility=all", timeout=10)
                self.assertEqual(denied.exception.code, 401)

                payload = json.dumps(
                    {"workIds": [ids["hiddenWork"]], "visible": True}
                ).encode("utf-8")
                req = Request(
                    base + "/api/admin/works/visibility",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="PUT",
                )
                with self.assertRaises(HTTPError) as denied_put:
                    urlopen(req, timeout=10)
                self.assertEqual(denied_put.exception.code, 401)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
