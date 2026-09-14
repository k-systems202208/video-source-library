from __future__ import annotations

import json
import os
import runpy
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
HOOK = ROOT / "windows-installer" / "build" / "runtime_no_console.py"
sys.path.insert(0, str(SRC))

from server import create_server


class GuiRuntimeTests(unittest.TestCase):
    def test_windowed_runtime_keeps_http_server_writable_without_stderr(self):
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        old_local_app_data = os.environ.get("LOCALAPPDATA")
        replacement_stdout = None
        replacement_stderr = None
        server = None
        thread = None

        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            os.environ["LOCALAPPDATA"] = str(temp)
            data_root = temp / "VideoLibrary"
            database_path = data_root / "library.db"

            try:
                # This reproduces PyInstaller console=False on Windows.
                sys.stdout = None
                sys.stderr = None
                runpy.run_path(str(HOOK), run_name="__video_library_runtime_hook_test__")
                replacement_stdout = sys.stdout
                replacement_stderr = sys.stderr

                server = create_server(
                    database_path,
                    host="127.0.0.1",
                    port=0,
                    data_root=data_root,
                )
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(
                    f"http://127.0.0.1:{server.server_port}/api/health",
                    timeout=5,
                ) as response:
                    status = response.status
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=5)

                sys.stdout = old_stdout
                sys.stderr = old_stderr
                if old_local_app_data is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = old_local_app_data

                for stream in {replacement_stdout, replacement_stderr}:
                    if stream not in {None, old_stdout, old_stderr}:
                        try:
                            stream.close()
                        except Exception:
                            pass

            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "ok")
            log_path = data_root / "Logs" / "server.log"
            self.assertTrue(log_path.is_file())
            self.assertIn("GET /api/health", log_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
