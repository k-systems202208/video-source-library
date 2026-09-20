from __future__ import annotations

import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from database import SCHEMA_VERSION, connect, initialize_database
from identity_service import resolve_tailscale_user
from library_service import get_video, get_work, library_stats, list_people, list_works
from metadata_importer import import_metadata
from sample_metadata import build_metadata
from server import create_server
from tailscale_identity import TailscaleIdentity
from user_state import (
    favorite_works,
    record_progress,
    set_work_favorite,
    start_playback,
)
from work_visibility import (
    has_user_visibility_overrides,
    list_visibility_targets,
    list_work_visibility,
    replace_visible_work_ids,
    reset_user_visibility,
)


class TailscaleUserVisibilityV130Tests(unittest.TestCase):
    def _seed(self, db: Path) -> dict[str, object]:
        with connect(db) as connection:
            initialize_database(connection)
            import_metadata(connection, build_metadata(work_count=4, video_count=8))
            work_rows = connection.execute(
                "SELECT id,external_work_no FROM works ORDER BY external_work_no"
            ).fetchall()
            works = {
                int(row["external_work_no"]): int(row["id"])
                for row in work_rows
            }
            connection.execute(
                "UPDATE works SET director_or_direction='一番監督',main_cast_or_voice_actors='一番出演者' WHERE id=?",
                (works[1],),
            )
            connection.execute(
                "UPDATE works SET director_or_direction='二番監督',main_cast_or_voice_actors='二番出演者' WHERE id=?",
                (works[2],),
            )
            connection.execute("UPDATE video_files SET is_available=1")
            connection.commit()

            users = {}
            for key, login, name in (
                ("alice", "alice@example.com", "Alice"),
                ("bob", "bob@example.com", "Bob"),
                ("carol", "carol@example.com", "Carol"),
            ):
                user = resolve_tailscale_user(
                    connection,
                    TailscaleIdentity(
                        subject=login,
                        login_name=login,
                        display_name=name,
                        profile_picture_url="",
                    ),
                )
                self.assertIsNotNone(user)
                users[key] = int(user["id"])

            videos = connection.execute(
                "SELECT id,work_id FROM videos ORDER BY work_id,episode_sort_key,id"
            ).fetchall()
            first_video = {}
            for row in videos:
                first_video.setdefault(int(row["work_id"]), int(row["id"]))

            return {
                "works": works,
                "users": users,
                "videos": first_video,
            }

    def test_schema9_has_user_work_visibility_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            with connect(db) as connection:
                initialize_database(connection)
                self.assertEqual(SCHEMA_VERSION, 9)
                self.assertEqual(
                    int(connection.execute(
                        "SELECT schema_version FROM schema_info"
                    ).fetchone()[0]),
                    9,
                )
                columns = {
                    str(row["name"])
                    for row in connection.execute(
                        "PRAGMA table_info(user_work_visibility)"
                    ).fetchall()
                }
                self.assertEqual(
                    columns,
                    {"user_id", "work_id", "is_visible", "created_at", "updated_at"},
                )

    def test_three_tailscale_users_can_have_independent_visibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            ids = self._seed(db)
            works = ids["works"]
            users = ids["users"]

            with connect(db) as connection:
                replace_visible_work_ids(
                    connection,
                    [works[1], works[2], works[3]],
                )
                replace_visible_work_ids(
                    connection,
                    [works[1]],
                    user_id=users["alice"],
                )
                replace_visible_work_ids(
                    connection,
                    [works[2]],
                    user_id=users["bob"],
                )

                alice_ids = {
                    int(item["id"])
                    for item in list_works(
                        connection, user_id=users["alice"], limit=100
                    )["items"]
                }
                bob_ids = {
                    int(item["id"])
                    for item in list_works(
                        connection, user_id=users["bob"], limit=100
                    )["items"]
                }
                carol_ids = {
                    int(item["id"])
                    for item in list_works(
                        connection, user_id=users["carol"], limit=100
                    )["items"]
                }

                self.assertEqual(alice_ids, {works[1]})
                self.assertEqual(bob_ids, {works[2]})
                self.assertEqual(carol_ids, {works[1], works[2], works[3]})
                self.assertTrue(has_user_visibility_overrides(connection, users["alice"]))
                self.assertFalse(has_user_visibility_overrides(connection, users["carol"]))

                self.assertIsNotNone(
                    get_work(connection, works[1], user_id=users["alice"])
                )
                self.assertIsNone(
                    get_work(connection, works[2], user_id=users["alice"])
                )
                self.assertIsNone(
                    get_video(
                        connection,
                        ids["videos"][works[2]],
                        user_id=users["alice"],
                    )
                )

                alice_people = list_people(
                    connection, role="director", user_id=users["alice"]
                )
                bob_people = list_people(
                    connection, role="director", user_id=users["bob"]
                )
                self.assertIn("一番監督", [x["name"] for x in alice_people["items"]])
                self.assertNotIn("二番監督", [x["name"] for x in alice_people["items"]])
                self.assertIn("二番監督", [x["name"] for x in bob_people["items"]])
                self.assertNotIn("一番監督", [x["name"] for x in bob_people["items"]])

                self.assertEqual(
                    library_stats(connection, user_id=users["alice"])["works"],
                    1,
                )
                self.assertEqual(
                    library_stats(connection, user_id=users["carol"])["works"],
                    3,
                )

    def test_user_state_lists_follow_that_users_visibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            ids = self._seed(db)
            works = ids["works"]
            users = ids["users"]
            videos = ids["videos"]

            with connect(db) as connection:
                replace_visible_work_ids(
                    connection,
                    [works[1]],
                    user_id=users["alice"],
                )
                for work_id in (works[1], works[2]):
                    set_work_favorite(connection, users["alice"], work_id, True)
                    start_playback(connection, users["alice"], videos[work_id])
                    record_progress(
                        connection,
                        users["alice"],
                        videos[work_id],
                        position_ms=30_000,
                        duration_ms=300_000,
                        event="pause",
                    )

                favorite_ids = {
                    int(item["id"])
                    for item in favorite_works(connection, users["alice"])["items"]
                }
                self.assertEqual(favorite_ids, {works[1]})

    def test_new_work_without_user_row_inherits_common_visibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            ids = self._seed(db)
            works = ids["works"]
            alice = ids["users"]["alice"]

            with connect(db) as connection:
                replace_visible_work_ids(connection, [works[1]], user_id=alice)
                self.assertTrue(has_user_visibility_overrides(connection, alice))

                import_metadata(
                    connection,
                    build_metadata(work_count=5, video_count=10),
                )
                new_work = int(connection.execute(
                    "SELECT id FROM works WHERE external_work_no=5"
                ).fetchone()["id"])
                row = next(
                    item
                    for item in list_work_visibility(connection, user_id=alice)
                    if int(item["id"]) == new_work
                )
                self.assertTrue(row["inherited"])
                self.assertTrue(row["visible"])

    def test_reset_returns_user_to_common_visibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            ids = self._seed(db)
            works = ids["works"]
            alice = ids["users"]["alice"]

            with connect(db) as connection:
                replace_visible_work_ids(connection, [works[1], works[2]])
                replace_visible_work_ids(connection, [works[1]], user_id=alice)
                self.assertTrue(has_user_visibility_overrides(connection, alice))

                result = reset_user_visibility(connection, alice)
                self.assertTrue(result["reset"])
                self.assertFalse(has_user_visibility_overrides(connection, alice))
                visible = {
                    int(item["id"])
                    for item in list_work_visibility(connection, user_id=alice)
                    if item["visible"]
                }
                self.assertEqual(visible, {works[1], works[2]})

    def test_launcher_targets_are_known_tailscale_users_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            ids = self._seed(db)
            with connect(db) as connection:
                targets = list_visibility_targets(connection)
            self.assertEqual(targets[0]["key"], "common")
            subjects = {
                str(item["subject"])
                for item in targets[1:]
            }
            self.assertEqual(
                subjects,
                {"alice@example.com", "bob@example.com", "carol@example.com"},
            )

    def test_http_requests_use_tailscale_login_to_select_visibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "library.db"
            ids = self._seed(db)
            works = ids["works"]

            with connect(db) as connection:
                alice = ids["users"]["alice"]
                bob = ids["users"]["bob"]
                replace_visible_work_ids(connection, [works[1]], user_id=alice)
                replace_visible_work_ids(connection, [works[2]], user_id=bob)

            server = create_server(
                db,
                host="127.0.0.1",
                port=0,
                video_root=root,
                data_root=root,
                owner_control_secret="test-secret-0123456789abcdef0123456789abcdef",
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            def request(login: str, path: str) -> tuple[int, dict]:
                connection = http.client.HTTPConnection(
                    "127.0.0.1", server.server_port, timeout=10
                )
                try:
                    connection.request(
                        "GET",
                        path,
                        headers={
                            "Host": "cinema.example.ts.net:8443",
                            "Tailscale-User-Login": login,
                            "Tailscale-User-Name": login.split("@", 1)[0],
                        },
                    )
                    response = connection.getresponse()
                    body = response.read()
                    payload = (
                        json.loads(body.decode("utf-8"))
                        if body
                        and response.getheader("Content-Type", "").startswith(
                            "application/json"
                        )
                        else {}
                    )
                    return response.status, payload
                finally:
                    connection.close()

            try:
                alice_status, alice_payload = request(
                    "alice@example.com", "/api/works?limit=100"
                )
                bob_status, bob_payload = request(
                    "bob@example.com", "/api/works?limit=100"
                )
                self.assertEqual(alice_status, 200)
                self.assertEqual(bob_status, 200)
                self.assertEqual(
                    {int(x["id"]) for x in alice_payload["items"]},
                    {works[1]},
                )
                self.assertEqual(
                    {int(x["id"]) for x in bob_payload["items"]},
                    {works[2]},
                )

                hidden_status, _ = request(
                    "alice@example.com",
                    f"/api/works/{works[2]}",
                )
                self.assertEqual(hidden_status, 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_launcher_contains_user_selector_and_inheritance_reset(self):
        launcher = (SRC / "launcher.py").read_text(encoding="utf-8")
        self.assertIn('text="対象ユーザー"', launcher)
        self.assertIn("list_visibility_targets", launcher)
        self.assertIn("has_user_visibility_overrides", launcher)
        self.assertIn('text="共通設定に戻す"', launcher)
        self.assertIn("reset_user_visibility", launcher)


if __name__ == "__main__":
    unittest.main()
