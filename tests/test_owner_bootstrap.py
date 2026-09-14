from __future__ import annotations

import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SRC)); sys.path.insert(0, str(TESTS))

from launcher import request_local_owner_browser_url
from local_auth import LocalOwnerAuth, create_bootstrap_token
from metadata_importer import import_file
from sample_metadata import build_metadata
from server import create_server


class OwnerBootstrapTests(unittest.TestCase):
    def test_signed_bootstrap_token_is_one_time(self):
        secret = "control-" + "x" * 40
        token = create_bootstrap_token(secret)
        auth = LocalOwnerAuth(secret)
        self.assertTrue(auth.consume_one_time_token(token))
        self.assertFalse(auth.consume_one_time_token(token))

    def test_launcher_keeps_token_out_of_initial_http_request(self):
        secret = "control-" + "x" * 40
        url = request_local_owner_browser_url("http://127.0.0.1:8765/", secret)
        parsed = urlsplit(url)
        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.hostname, "127.0.0.1")
        self.assertEqual(parsed.path, "/offline.html")
        self.assertEqual(parse_qs(parsed.query), {"owner-bootstrap": ["1"]})
        self.assertNotIn("token", parsed.query)
        fragment = parse_qs(parsed.fragment)
        self.assertIn("token", fragment)
        token = fragment["token"][0]
        self.assertTrue(LocalOwnerAuth(secret).consume_one_time_token(token))

    def test_fragment_bootstrap_page_then_secure_exchange(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = root / "library.db"
            metadata = root / "fixture.json"
            metadata.write_text(json.dumps(build_metadata(work_count=5, video_count=5), ensure_ascii=False), encoding="utf-8")
            import_file(metadata, db)
            secret = "control-" + "y" * 40
            server = create_server(db, host="127.0.0.1", port=0, owner_control_secret=secret, data_root=root)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}/"
                browser_url = request_local_owner_browser_url(base, secret)
                parsed = urlsplit(browser_url)

                # URL fragments are browser-only and therefore absent from the
                # initial HTTP request seen by the server or URL scanners.
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                initial_path = parsed.path + ("?" + parsed.query if parsed.query else "")
                self.assertNotIn("token=", initial_path)
                connection.request("GET", initial_path)
                response = connection.getresponse()
                page = response.read().decode("utf-8")
                self.assertEqual(response.status, 200)
                self.assertIn("location.hash", page)
                self.assertIn("/api/local-auth/exchange?token=", page)
                connection.close()

                # Simulate the bootstrap page JavaScript exchanging the token
                # from location.hash after the page has loaded in the browser.
                token = parse_qs(parsed.fragment)["token"][0]
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                connection.request("GET", "/api/local-auth/exchange?token=" + token)
                exchange = connection.getresponse()
                exchange.read()
                headers = dict(exchange.getheaders())
                self.assertEqual(exchange.status, 302)
                self.assertIn("video_library_owner_session=", headers.get("Set-Cookie", ""))
                connection.close()

                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                connection.request("GET", "/api/local-auth/exchange?token=" + token)
                replay = connection.getresponse()
                replay.read()
                self.assertEqual(replay.status, 401)
                connection.close()
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
