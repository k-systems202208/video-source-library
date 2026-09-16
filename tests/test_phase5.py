from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SRC)); sys.path.insert(0, str(TESTS))

from backup_restore import apply_pending_restore, create_manual_backup, list_backups, schedule_restore
from database import connect
from launcher import request_local_owner_browser_url
from local_auth import LocalOwnerAuth, cookie_value, session_cookie_header
from metadata_importer import import_file
from remote_access import build_remote_app_url, parse_backend_state, parse_serve_url
from sample_metadata import build_metadata
from server import CONTROL_HEADER, create_server
from tailscale_identity import parse_tailscale_identity


class LocalAuthTests(unittest.TestCase):
    def test_one_time_token_session_and_cookie(self):
        auth = LocalOwnerAuth("s" * 48)
        token = "A" * 43
        self.assertEqual(auth.register_one_time_token(token), 60)
        self.assertTrue(auth.consume_one_time_token(token))
        self.assertFalse(auth.consume_one_time_token(token))
        issue = auth.issue_session()
        self.assertTrue(auth.validate_session(issue.value))
        header = session_cookie_header(issue)
        self.assertIn("HttpOnly", header)
        self.assertIn("SameSite=Strict", header)
        self.assertEqual(cookie_value(header.split(";", 1)[0]), issue.value)


class TailscaleIdentityTests(unittest.TestCase):
    def test_identity_is_normalized_and_invalid_profile_is_dropped(self):
        identity = parse_tailscale_identity({
            "Tailscale-User-Login": "Alice@Example.COM",
            "Tailscale-User-Name": "Alice",
            "Tailscale-User-Profile-Pic": "javascript:bad",
        })
        self.assertIsNotNone(identity)
        self.assertEqual(identity.subject, "alice@example.com")
        self.assertEqual(identity.display_name, "Alice")
        self.assertEqual(identity.profile_picture_url, "")

    def test_remote_access_parsers(self):
        self.assertEqual(parse_backend_state('{"BackendState":"Running"}'), "Running")
        self.assertEqual(parse_serve_url("Available on your tailnet: https://sample.ts.net/"), "https://sample.ts.net")
        self.assertEqual(build_remote_app_url("https://sample.ts.net"), "https://sample.ts.net/")


class BackupTests(unittest.TestCase):
    def test_backup_schedule_and_restore_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = root / "library.db"; metadata = root / "fixture.json"
            metadata.write_text(json.dumps(build_metadata(work_count=6, video_count=6), ensure_ascii=False), encoding="utf-8")
            import_file(metadata, db)
            backup = create_manual_backup(database_path=db, backup_dir=root / "Backups")
            self.assertTrue(backup["valid"])
            self.assertEqual(backup["workCount"], 6)
            self.assertEqual(len(list_backups(root / "Backups")), 1)
            with connect(db) as connection:
                original = connection.execute("SELECT official_title FROM works WHERE external_work_no=1").fetchone()[0]
                connection.execute("UPDATE works SET official_title='MUTATED' WHERE external_work_no=1"); connection.commit()
            schedule_restore(backup["name"], data_root=root, backup_dir=root / "Backups")
            result = apply_pending_restore(root)
            self.assertEqual(result["state"], "restored")
            with connect(db) as connection:
                restored = connection.execute("SELECT official_title FROM works WHERE external_work_no=1").fetchone()[0]
            self.assertEqual(restored, original)
            self.assertNotEqual(restored, "MUTATED")
            self.assertTrue((root / "Backups" / result["preRestoreBackupName"]).is_file())


class SecureServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); root = Path(self.temp.name)
        self.db = root / "library.db"; metadata = root / "fixture.json"
        metadata.write_text(json.dumps(build_metadata(work_count=5, video_count=5), ensure_ascii=False), encoding="utf-8")
        import_file(metadata, self.db)
        self.secret = "control-" + "x" * 40
        self.server = create_server(self.db, host="127.0.0.1", port=0, owner_control_secret=self.secret, data_root=root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.port = self.server.server_port

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=3); self.temp.cleanup()

    def request(self, method: str, path: str, *, body: dict | None = None, headers: dict | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        raw = None if body is None else json.dumps(body).encode("utf-8")
        request_headers = {"Accept": "application/json", **(headers or {})}
        if raw is not None: request_headers["Content-Type"] = "application/json"
        connection.request(method, path, body=raw, headers=request_headers)
        response = connection.getresponse(); payload = response.read(); all_headers = dict(response.getheaders()); status = response.status
        connection.close()
        data = json.loads(payload.decode("utf-8")) if payload and all_headers.get("Content-Type", "").startswith("application/json") else payload.decode("utf-8", errors="replace")
        return status, all_headers, data

    def owner_cookie(self) -> str:
        token = "T" * 43
        status, _, data = self.request("POST", "/api/local-auth/token", body={"token": token, "expiresInSeconds": 60}, headers={CONTROL_HEADER: self.secret})
        self.assertEqual(status, 201); self.assertTrue(data["registered"])
        status, headers, _ = self.request("GET", f"/api/local-auth/exchange?token={token}")
        self.assertEqual(status, 302)
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        status2, _, _ = self.request("GET", f"/api/local-auth/exchange?token={token}")
        self.assertEqual(status2, 401)
        return cookie

    def test_anonymous_then_local_owner_exchange(self):
        status, _, data = self.request("GET", "/api/current-user")
        self.assertEqual(status, 200); self.assertFalse(data["authenticated"])
        status, _, _ = self.request("PUT", "/api/me/works/1/favorite", body={"favorite": True})
        self.assertEqual(status, 401)
        cookie = self.owner_cookie()
        status, _, data = self.request("GET", "/api/current-user", headers={"Cookie": cookie})
        self.assertEqual(status, 200); self.assertTrue(data["authenticated"]); self.assertTrue(data["user"]["isOwner"])
        status, _, data = self.request("PUT", "/api/me/works/1/favorite", body={"favorite": True}, headers={"Cookie": cookie})
        self.assertEqual(status, 200); self.assertTrue(data["favorite"])

    def test_launcher_owner_auth_bypasses_system_proxy(self):
        base = f"http://127.0.0.1:{self.port}/"
        proxy_env = {
            "http_proxy": "http://127.0.0.1:1",
            "https_proxy": "http://127.0.0.1:1",
            "HTTP_PROXY": "http://127.0.0.1:1",
            "HTTPS_PROXY": "http://127.0.0.1:1",
            "no_proxy": "",
            "NO_PROXY": "",
        }
        with patch.dict(os.environ, proxy_env, clear=False):
            browser_url = request_local_owner_browser_url(base, self.secret)
        self.assertTrue(browser_url.startswith(base + "offline.html?owner-bootstrap=1#token="))

    def test_owner_token_endpoint_still_rejects_cross_origin_request(self):
        status, _, data = self.request(
            "POST",
            "/api/local-auth/token",
            body={"token": "T" * 43, "expiresInSeconds": 60},
            headers={CONTROL_HEADER: self.secret, "Origin": "https://evil.example"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(data["error"]["code"], "ORIGIN_NOT_ALLOWED")

    def test_tailscale_users_are_separate_non_owner_users(self):
        alice = {"Host": "video-box.tailnet.ts.net", "Tailscale-User-Login": "alice@example.com", "Tailscale-User-Name": "Alice"}
        bob = {"Host": "video-box.tailnet.ts.net", "Tailscale-User-Login": "bob@example.com", "Tailscale-User-Name": "Bob"}
        status, _, a = self.request("GET", "/api/current-user", headers=alice)
        self.assertEqual(status, 200); self.assertTrue(a["authenticated"]); self.assertFalse(a["user"]["isOwner"])
        status, _, b = self.request("GET", "/api/current-user", headers=bob)
        self.assertEqual(status, 200); self.assertNotEqual(a["user"]["id"], b["user"]["id"])
        self.request("PUT", "/api/me/works/1/favorite", body={"favorite": True}, headers=alice)
        status, _, works_a = self.request("GET", "/api/me/favorite-works", headers=alice)
        status, _, works_b = self.request("GET", "/api/me/favorite-works", headers=bob)
        self.assertEqual(len(works_a["items"]), 1); self.assertEqual(works_b["items"], [])
        status, _, _ = self.request("POST", "/api/scan", headers=alice)
        self.assertEqual(status, 403)

    def test_pwa_shell_and_cache_policy(self):
        status, _, html = self.request("GET", "/")
        self.assertEqual(status, 200); self.assertIn("manifest.webmanifest", html); self.assertIn("serviceWorker.register", html)
        status, _, manifest = self.request("GET", "/manifest.webmanifest")
        self.assertEqual(status, 200); self.assertIn("シネマ蔵書館", manifest)
        status, _, sw = self.request("GET", "/service-worker.js")
        self.assertEqual(status, 200); self.assertIn("/api/", sw); self.assertIn("/video/", sw); self.assertIn("offline.html", sw)

    def test_server_rejects_non_loopback_bind(self):
        with self.assertRaises(ValueError):
            create_server(self.db, host="0.0.0.0", port=0)


if __name__ == "__main__":
    unittest.main()
