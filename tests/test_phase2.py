from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from database import connect  # noqa: E402
from library_service import get_video, get_work, list_work_videos, list_works  # noqa: E402
from metadata_importer import import_metadata  # noqa: E402
from sample_metadata import build_metadata  # noqa: E402
from server import create_server  # noqa: E402


class Phase2ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "library.db"
        self.payload = build_metadata(work_count=60, video_count=180)
        with connect(self.db_path) as connection:
            import_metadata(connection, self.payload)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_list_works_supports_search_category_and_paging(self) -> None:
        with connect(self.db_path) as connection:
            page = list_works(connection, limit=10, offset=0)
            self.assertEqual(page["total"], 60)
            self.assertEqual(len(page["items"]), 10)
            self.assertEqual(page["limit"], 10)

            search = list_works(connection, q="Test Work 001")
            self.assertEqual(search["total"], 1)
            self.assertEqual(search["items"][0]["externalWorkNo"], 1)

            category = list_works(connection, category="テスト")
            self.assertEqual(category["total"], 60)

    def test_zero_video_work_remains_browsable(self) -> None:
        with connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT id FROM works WHERE external_work_no = 42"
            ).fetchone()
            detail = get_work(connection, int(row["id"]))
            self.assertIsNotNone(detail)
            self.assertEqual(detail["videoCount"], 0)
            self.assertEqual(detail["groups"], [])

    def test_work_group_and_video_detail_do_not_expose_paths(self) -> None:
        with connect(self.db_path) as connection:
            work_row = connection.execute(
                "SELECT id FROM works WHERE external_work_no = 1"
            ).fetchone()
            work_id = int(work_row["id"])
            detail = get_work(connection, work_id)
            self.assertTrue(detail["groups"])
            group_id = detail["groups"][0]["id"]

            videos = list_work_videos(connection, work_id, group_id=group_id)
            self.assertTrue(videos["items"])
            video_id = videos["items"][0]["id"]
            video = get_video(connection, video_id)

            serialized = json.dumps(
                {"work": detail, "videos": videos, "video": video}, ensure_ascii=False
            )
            self.assertNotIn("relative_path", serialized)
            self.assertNotIn("relativePath", serialized)
            self.assertNotIn("source_folder", serialized)
            self.assertNotIn("filename", serialized)
            self.assertIn("navigation", video)


class Phase2HttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "library.db"
        with connect(self.db_path) as connection:
            import_metadata(connection, build_metadata(work_count=60, video_count=180))
        self.server = create_server(self.db_path, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tempdir.cleanup()

    def get_json(self, path: str) -> tuple[int, dict]:
        with urlopen(self.base + path, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_health_works_and_detail_routes(self) -> None:
        status, health = self.get_json("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["quickCheck"], "ok")

        status, listing = self.get_json("/api/works?limit=5")
        self.assertEqual(status, 200)
        self.assertEqual(listing["total"], 60)
        self.assertEqual(len(listing["items"]), 5)

        work_id = listing["items"][0]["id"]
        status, work = self.get_json(f"/api/works/{work_id}")
        self.assertEqual(status, 200)
        self.assertEqual(work["id"], work_id)

        group_id = work["groups"][0]["id"]
        status, videos = self.get_json(
            f"/api/works/{work_id}/videos?groupId={group_id}"
        )
        self.assertEqual(status, 200)
        self.assertTrue(videos["items"])

        video_id = videos["items"][0]["id"]
        status, video = self.get_json(f"/api/videos/{video_id}")
        self.assertEqual(status, 200)
        self.assertEqual(video["id"], video_id)

    def test_unknown_resource_is_404(self) -> None:
        with self.assertRaises(HTTPError) as ctx:
            urlopen(self.base + "/api/works/999999", timeout=10)
        self.assertEqual(ctx.exception.code, 404)
        payload = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "WORK_NOT_FOUND")

    def test_web_ui_is_served_and_is_paginated(self) -> None:
        with urlopen(self.base + "/", timeout=10) as response:
            html = response.read().decode("utf-8")
        self.assertIn("自宅動画ライブラリ", html)
        self.assertIn("const PAGE=60", html)
        self.assertIn("/api/works", html)
        self.assertNotIn("video_library.json", html)


if __name__ == "__main__":
    unittest.main()
