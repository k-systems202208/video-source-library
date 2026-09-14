from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

import server as server_module
from metadata_importer import import_file
from sample_metadata import build_metadata


class ScanStatusLiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.db_path = base / "library.db"
        self.video_root = base / "videos"
        self.video_root.mkdir()
        metadata_path = base / "fixture.json"
        metadata_path.write_text(
            json.dumps(build_metadata(work_count=6, video_count=6), ensure_ascii=False),
            encoding="utf-8",
        )
        import_file(metadata_path, self.db_path)
        self.server = server_module.create_server(
            self.db_path,
            host="127.0.0.1",
            port=0,
            video_root=self.video_root,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def test_running_status_does_not_open_sqlite_connection(self):
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        original_scan = server_module.scan_library
        original_connect = server_module.connect

        def fake_scan(connection, video_root, *, ffprobe_path=None, progress_callback=None):
            if progress_callback is not None:
                progress_callback({
                    "phase": "SCANNING",
                    "message": "動画ファイルを走査中",
                    "current": 123,
                    "total": 4869,
                    "filesFound": 123,
                    "filesMatched": 120,
                    "filesNew": 3,
                    "currentItem": "Drama/sample-0123.mkv",
                })
            started.set()
            release.wait(timeout=5)
            finished.set()
            return {
                "status": "SUCCESS",
                "filesFound": 123,
                "filesMatched": 120,
                "filesMissing": 0,
                "filesNew": 3,
                "filesProbed": 0,
                "subtitlesFound": 0,
                "subtitlesMatched": 0,
                "subtitlesUnmatched": 0,
                "probeErrors": 0,
                "errors": 0,
            }

        server_module.scan_library = fake_scan
        try:
            request = Request(f"{self.base_url}/api/scan", data=b"", method="POST")
            with urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 202)
            self.assertTrue(started.wait(timeout=2))

            def fail_connect(*args, **kwargs):
                raise AssertionError("live scan status must not open SQLite")

            server_module.connect = fail_connect
            before = time.monotonic()
            with urlopen(f"{self.base_url}/api/scan/status", timeout=1) as response:
                self.assertEqual(response.status, 200)
                payload = json.loads(response.read().decode("utf-8"))
            elapsed = time.monotonic() - before

            self.assertLess(elapsed, 0.8)
            self.assertTrue(payload["running"])
            self.assertEqual(payload["progress"]["phase"], "SCANNING")
            self.assertEqual(payload["progress"]["current"], 123)
            self.assertEqual(payload["progress"]["total"], 4869)
            self.assertEqual(payload["progress"]["currentItem"], "Drama/sample-0123.mkv")
        finally:
            server_module.connect = original_connect
            release.set()
            finished.wait(timeout=2)
            server_module.scan_library = original_scan


if __name__ == "__main__":
    unittest.main()
