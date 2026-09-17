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

from server import CONTROL_HEADER, create_server
from test_scan_diagnostics import seed


class DiagnosticsHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db = root / "library.db"
        seed(self.db)
        self.secret = "x" * 48
        self.server = create_server(self.db, host="127.0.0.1", port=0, owner_control_secret=self.secret, data_root=root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temp.cleanup()

    def request(self, method: str, path: str, *, body: dict | None = None, headers: dict | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        raw = None if body is None else json.dumps(body).encode("utf-8")
        request_headers = {"Accept": "application/json", **(headers or {})}
        if raw is not None:
            request_headers["Content-Type"] = "application/json"
        conn.request(method, path, body=raw, headers=request_headers)
        response = conn.getresponse()
        payload = response.read()
        response_headers = dict(response.getheaders())
        status = response.status
        conn.close()
        if payload and response_headers.get("Content-Type", "").startswith("application/json"):
            return status, response_headers, json.loads(payload.decode("utf-8"))
        return status, response_headers, payload

    def owner_cookie(self) -> str:
        token = "T" * 43
        status, _, _ = self.request("POST", "/api/local-auth/token", body={"token": token}, headers={CONTROL_HEADER: self.secret})
        self.assertEqual(status, 201)
        status, headers, _ = self.request("GET", f"/api/local-auth/exchange?token={token}")
        self.assertEqual(status, 302)
        return headers["Set-Cookie"].split(";", 1)[0]

    def test_diagnostics_api_requires_owner(self):
        status, _, data = self.request("GET", "/api/admin/scan-diagnostics")
        self.assertEqual(status, 401)
        self.assertEqual(data["error"]["code"], "AUTH_REQUIRED")

        remote_user = {
            "Host": "video.tailnet.example",
            "Tailscale-User-Login": "member@example.com",
            "Tailscale-User-Name": "Member",
        }
        status, _, data = self.request("GET", "/api/admin/scan-diagnostics", headers=remote_user)
        self.assertEqual(status, 403)
        self.assertEqual(data["error"]["code"], "OWNER_REQUIRED")

    def test_owner_can_open_page_api_and_exports(self):
        status, _, html = self.request("GET", "/diagnostics.html")
        self.assertEqual(status, 200)
        self.assertIn("スキャン診断", html.decode("utf-8"))

        cookie = self.owner_cookie()
        headers = {"Cookie": cookie}
        status, _, data = self.request("GET", "/api/admin/scan-diagnostics", headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(data["summary"]["missing"], 1)

        status, csv_headers, csv_payload = self.request("GET", "/api/admin/scan-diagnostics.csv", headers=headers)
        self.assertEqual(status, 200)
        self.assertTrue(csv_headers["Content-Type"].startswith("text/csv"))
        self.assertTrue(csv_payload.startswith(b"\xef\xbb\xbf"))

        status, json_headers, json_payload = self.request("GET", "/api/admin/scan-diagnostics.json", headers=headers)
        self.assertEqual(status, 200)
        self.assertIn("attachment", json_headers["Content-Disposition"])
        self.assertEqual(json_payload["summary"]["newFiles"], 1)

    def test_main_page_does_not_link_to_diagnostics(self):
        status, _, html = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertNotIn("/diagnostics.html", html.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
