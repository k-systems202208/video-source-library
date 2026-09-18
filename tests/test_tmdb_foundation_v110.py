from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from app_config import configured_tmdb_token, load_config, save_tmdb_token, tmdb_token_source
from database import SCHEMA_VERSION, connect, initialize_database, now_iso
from tmdb_cache import get_cached_json, put_cached_json
from tmdb_client import TmdbClient, TmdbError


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.closed = False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

    def close(self):
        self.closed = True


class TmdbConfigTests(unittest.TestCase):
    def test_environment_precedes_local_config_and_local_can_be_cleared(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("VIDEO_LIBRARY_TMDB_TOKEN", None)
                save_tmdb_token("local-token", config_path=config)
                self.assertEqual(configured_tmdb_token(config_path=config), "local-token")
                self.assertEqual(tmdb_token_source(config_path=config), "config")
                with patch.dict(os.environ, {"VIDEO_LIBRARY_TMDB_TOKEN": "env-token"}):
                    self.assertEqual(configured_tmdb_token(config_path=config), "env-token")
                    self.assertEqual(tmdb_token_source(config_path=config), "environment")
                save_tmdb_token(None, config_path=config)
                self.assertIsNone(configured_tmdb_token(config_path=config))
                self.assertNotIn("tmdbReadAccessToken", load_config(config))


class TmdbClientTests(unittest.TestCase):
    def test_bearer_header_is_used_without_credentials_in_url(self):
        captured = {}

        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["authorization"] = request.get_header("Authorization")
            captured["timeout"] = timeout
            return FakeResponse({"results": []})

        client = TmdbClient("secret-test-token", opener=opener, timeout=9)
        payload = client.search_movie("七人の侍", year=1954)
        self.assertEqual(payload, {"results": []})
        self.assertEqual(captured["authorization"], "Bearer secret-test-token")
        self.assertNotIn("secret-test-token", captured["url"])
        self.assertNotIn("api_key", captured["url"])
        self.assertIn("query=", captured["url"])
        self.assertEqual(captured["timeout"], 9)

    def test_credential_query_params_are_rejected(self):
        client = TmdbClient("secret-test-token", opener=lambda *args, **kwargs: FakeResponse({}))
        with self.assertRaises(ValueError):
            client.get_json("/configuration", {"api_key": "do-not-put-here"})

    def test_connection_error_does_not_expose_token(self):
        def opener(request, timeout):
            raise TimeoutError("network timeout")

        client = TmdbClient("top-secret-token", opener=opener)
        with self.assertRaises(TmdbError) as captured:
            client.configuration()
        self.assertNotIn("top-secret-token", str(captured.exception))


class TmdbDatabaseTests(unittest.TestCase):
    def test_schema6_tables_and_schema5_upgrade_preserve_user_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            with connect(db) as connection:
                initialize_database(connection)
                stamp = now_iso()
                connection.execute(
                    "INSERT INTO works(external_work_no,category,official_title,created_at,updated_at) VALUES(1,'映画','作品',?,?)",
                    (stamp, stamp),
                )
                work_id = int(connection.execute("SELECT id FROM works WHERE external_work_no=1").fetchone()[0])
                connection.execute(
                    "INSERT INTO users(display_name,is_owner,created_at,updated_at) VALUES('Owner',1,?,?)",
                    (stamp, stamp),
                )
                user_id = int(connection.execute("SELECT id FROM users WHERE is_owner=1").fetchone()[0])
                connection.execute(
                    "INSERT INTO user_work_state(user_id,work_id,favorite,created_at,updated_at) VALUES(?,?,1,?,?)",
                    (user_id, work_id, stamp, stamp),
                )
                connection.execute("DROP TABLE tmdb_work_people")
                connection.execute("DROP TABLE tmdb_people")
                connection.execute("DROP TABLE tmdb_api_cache")
                connection.execute("DROP TABLE tmdb_work_links")
                connection.execute("UPDATE schema_info SET schema_version=5")
                connection.commit()
                initialize_database(connection)
                connection.commit()
                self.assertEqual(SCHEMA_VERSION, 6)
                self.assertEqual(int(connection.execute("SELECT schema_version FROM schema_info").fetchone()[0]), 6)
                self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tmdb_work_links'").fetchone())
                self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tmdb_api_cache'").fetchone())
                self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE type=\'table\' AND name=\'tmdb_people\'").fetchone())
                self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE type=\'table\' AND name=\'tmdb_work_people\'").fetchone())
                favorite = int(connection.execute("SELECT favorite FROM user_work_state WHERE user_id=? AND work_id=?", (user_id, work_id)).fetchone()[0])
                self.assertEqual(favorite, 1)

    def test_tmdb_json_cache_round_trip_and_expiry(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            with connect(db) as connection:
                initialize_database(connection)
                current = datetime.now(timezone.utc).astimezone()
                expiry = (current + timedelta(minutes=10)).isoformat(timespec="seconds")
                put_cached_json(connection, "search:movie:test", {"results": [{"id": 1}]}, expires_at=expiry)
                connection.commit()
                self.assertEqual(get_cached_json(connection, "search:movie:test", now=current.isoformat(timespec="seconds")), {"results": [{"id": 1}]})
                after = (current + timedelta(minutes=20)).isoformat(timespec="seconds")
                self.assertIsNone(get_cached_json(connection, "search:movie:test", now=after))

    def test_launcher_uses_masked_tmdb_dialog_without_expanding_main_layout(self):
        launcher = (SRC / "launcher.py").read_text(encoding="utf-8")
        self.assertIn('text="TMDb設定"', launcher)
        self.assertIn('show="*"', launcher)
        self.assertIn("tmdb_token_source", launcher)
        self.assertIn('WINDOW_GEOMETRY = "780x690"', launcher)


if __name__ == "__main__":
    unittest.main()
