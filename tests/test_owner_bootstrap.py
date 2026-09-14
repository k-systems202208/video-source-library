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

    def test_launcher_url_needs_no_token_registration_http(self):
        secret = "control-" + "x" * 40
        url = request_local_owner_browser_url("http://127.0.0.1:8765/", secret)
        parsed = urlsplit(url)
        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.hostname, "127.0.0.1")
        self.assertEqual(parsed.path, "/api/local-auth/exchange")
        token = parse_qs(parsed.query)["token"][0]
        self.assertTrue(LocalOwnerAuth(secret).consume_one_time_token(token))

    def test_signed_launcher_token_exchanges_on_secure_server(self):
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
                exchange_url = request_local_owner_browser_url(base, secret)
                parsed = urlsplit(exchange_url)
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                connection.request("GET", parsed.path + "?" + parsed.query)
                response = connection.getresponse()
                response.read()
                headers = dict(response.getheaders())
                self.assertEqual(response.status, 302)
                self.assertIn("video_library_owner_session=", headers.get("Set-Cookie", ""))
                connection.close()

                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                connection.request("GET", parsed.path + "?" + parsed.query)
                replay = connection.getresponse()
                replay.read()
                self.assertEqual(replay.status, 401)
                connection.close()
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
