from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from database import connect, initialize_database, now_iso
from library_service import list_people
from server import create_server
from tmdb_client import TmdbClient
from tmdb_images import cached_person_image_path
from tmdb_people import mark_people_sync_complete, people_sync_required, sync_cast_people_for_work


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def close(self):
        pass


class CreditsClient:
    def __init__(self):
        self.movie_calls = 0
        self.tv_calls = 0

    def movie_credits(self, movie_id, *, language="ja-JP"):
        self.movie_calls += 1
        return {"cast": self._cast()}

    def tv_aggregate_credits(self, tv_id, *, language="ja-JP"):
        self.tv_calls += 1
        return {"cast": self._cast()}

    @staticmethod
    def _cast():
        return [
            {
                "id": 101,
                "name": "仲間由紀恵",
                "original_name": "仲間由紀恵",
                "profile_path": "/nakama.jpg",
                "known_for_department": "Acting",
                "roles": [{"character": "山田奈緒子", "order": 0}],
                "order": 0,
            },
            {
                "id": 102,
                "name": "阿部寛",
                "original_name": "阿部寛",
                "profile_path": "/abe.jpg",
                "known_for_department": "Acting",
                "roles": [{"character": "上田次郎", "order": 1}],
                "order": 1,
            },
        ]


class TmdbPeoplePhase1Tests(unittest.TestCase):
    def _database_with_work(self, root: Path, cast: str = "仲間由紀恵、阿部寛、未照合俳優"):
        db = root / "library.db"
        with connect(db) as connection:
            initialize_database(connection)
            stamp = now_iso()
            connection.execute(
                """
                INSERT INTO works(
                    external_work_no,category,official_title,main_cast_or_voice_actors,created_at,updated_at
                ) VALUES(1,'日本映画・ドラマ','TRICK',?,?,?)
                """,
                (cast, stamp, stamp),
            )
            work_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
            connection.commit()
        return db, work_id

    def test_client_uses_movie_credits_and_tv_aggregate_credits_endpoints(self):
        urls = []

        def opener(request, timeout):
            urls.append(request.full_url)
            return FakeResponse({"cast": []})

        client = TmdbClient("token", opener=opener, max_retries=0)
        client.movie_credits(123)
        client.tv_aggregate_credits(456)
        self.assertTrue(any("/movie/123/credits" in url for url in urls))
        self.assertTrue(any("/tv/456/aggregate_credits" in url for url in urls))

    def test_cast_names_are_matched_from_work_credits_and_profiles_are_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, work_id = self._database_with_work(root)
            images = root / "TMDbImages"
            client = CreditsClient()
            downloads = []

            def downloader(remote_path, destination, *, size):
                downloads.append((remote_path, size))
                target = Path(destination)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"profile-image")
                return target

            with connect(db) as connection:
                result = sync_cast_people_for_work(
                    connection,
                    client,
                    work_id=work_id,
                    media_type="tv",
                    tmdb_id=999,
                    local_cast="仲間由紀恵、阿部寛、未照合俳優",
                    image_root=images,
                    image_downloader=downloader,
                )
                links = connection.execute(
                    "SELECT local_name,tmdb_person_id FROM tmdb_work_people ORDER BY billing_order"
                ).fetchall()
                people = list_people(connection, role="cast")

            self.assertEqual(client.tv_calls, 1)
            self.assertEqual(result["matched"], 2)
            self.assertEqual(result["profileCached"], 2)
            self.assertEqual([(row["local_name"], row["tmdb_person_id"]) for row in links], [
                ("仲間由紀恵", 101),
                ("阿部寛", 102),
            ])
            self.assertEqual(downloads, [("/nakama.jpg", "w185"), ("/abe.jpg", "w185")])
            self.assertTrue(cached_person_image_path(images, 101, "/nakama.jpg").is_file())
            self.assertTrue(cached_person_image_path(images, 102, "/abe.jpg").is_file())

            by_name = {item["name"]: item for item in people["items"]}
            self.assertEqual(by_name["仲間由紀恵"]["profileUrl"], "/tmdb-person-image/101")
            self.assertEqual(by_name["阿部寛"]["tmdbPersonId"], 102)
            self.assertNotIn("profileUrl", by_name["未照合俳優"])

    def test_credits_api_payload_is_cached_between_syncs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, work_id = self._database_with_work(root, "仲間由紀恵")
            client = CreditsClient()

            def downloader(remote_path, destination, *, size):
                target = Path(destination)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"profile")
                return target

            with connect(db) as connection:
                for _ in range(2):
                    sync_cast_people_for_work(
                        connection,
                        client,
                        work_id=work_id,
                        media_type="movie",
                        tmdb_id=1000,
                        local_cast="仲間由紀恵",
                        image_root=root / "TMDbImages",
                        image_downloader=downloader,
                    )
            self.assertEqual(client.movie_calls, 1)

    def test_ambiguous_same_name_is_not_auto_matched(self):
        class AmbiguousClient:
            def movie_credits(self, movie_id, *, language="ja-JP"):
                return {
                    "cast": [
                        {"id": 1, "name": "同名俳優", "original_name": "同名俳優", "profile_path": "/a.jpg"},
                        {"id": 2, "name": "同名俳優", "original_name": "同名俳優", "profile_path": "/b.jpg"},
                    ]
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, work_id = self._database_with_work(root, "同名俳優")
            with connect(db) as connection:
                result = sync_cast_people_for_work(
                    connection,
                    AmbiguousClient(),
                    work_id=work_id,
                    media_type="movie",
                    tmdb_id=10,
                    local_cast="同名俳優",
                    image_root=root / "TMDbImages",
                    image_downloader=lambda *args, **kwargs: None,
                )
                count = int(connection.execute("SELECT COUNT(*) FROM tmdb_work_people").fetchone()[0])
            self.assertEqual(result["matched"], 0)
            self.assertEqual(count, 0)

    def test_people_sync_marker_is_one_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            with connect(db) as connection:
                initialize_database(connection)
                self.assertTrue(people_sync_required(connection))
                mark_people_sync_complete(connection)
                connection.commit()
                self.assertFalse(people_sync_required(connection))

    def test_launcher_starts_background_people_sync_after_browser_start(self):
        launcher = (SRC / "launcher.py").read_text(encoding="utf-8")
        self.assertIn("def _start_people_sync_if_needed", launcher)
        self.assertIn("sync_tmdb_people_library(", launcher)
        self.assertIn("self.open_browser()", launcher)
        self.assertIn("self._start_people_sync_if_needed()", launcher)
        self.assertIn("次回起動時に自動再試行します", launcher)

    def test_person_image_is_served_through_local_application_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, work_id = self._database_with_work(root, "仲間由紀恵")
            images = root / "TMDbImages"
            with connect(db) as connection:
                stamp = now_iso()
                connection.execute(
                    """
                    INSERT INTO tmdb_people(
                        tmdb_person_id,display_name,original_name,profile_path,known_for_department,
                        synced_at,created_at,updated_at
                    ) VALUES(101,'仲間由紀恵','仲間由紀恵','/nakama.png','Acting',?,?,?)
                    """,
                    (stamp, stamp, stamp),
                )
                connection.execute(
                    """
                    INSERT INTO tmdb_work_people(
                        work_id,role,local_name,tmdb_person_id,created_at,updated_at
                    ) VALUES(?,'CAST','仲間由紀恵',101,?,?)
                    """,
                    (work_id, stamp, stamp),
                )
                connection.commit()
            target = cached_person_image_path(images, 101, "/nakama.png")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"fake-png")

            server = create_server(db, port=0, data_root=root)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urlopen(
                    f"http://127.0.0.1:{server.server_port}/tmdb-person-image/101",
                    timeout=10,
                ) as response:
                    body = response.read()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers.get_content_type(), "image/png")
                    self.assertEqual(body, b"fake-png")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
