from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from remote_access import (
    REMOTE_HTTPS_PORT,
    CommandResult,
    RemoteStatus,
    disable_remote_access,
    enable_remote_access,
    get_remote_status,
    parse_app_serve_url,
    parse_serve_url,
)


class RemoteAccessV079Tests(unittest.TestCase):
    def test_parser_keeps_ports_and_selects_video_8443(self):
        text = """
Available within your tailnet:
https://sample.ts.net
|-- / proxy http://127.0.0.1:8765
https://sample.ts.net:8443
|-- / proxy http://127.0.0.1:8876
"""
        self.assertEqual(parse_serve_url(text), "https://sample.ts.net")
        self.assertEqual(parse_app_serve_url(text), "https://sample.ts.net:8443")
        self.assertEqual(REMOTE_HTTPS_PORT, 8443)

    def test_status_does_not_treat_music_443_as_video_remote(self):
        serve = "https://sample.ts.net\n|-- / proxy http://127.0.0.1:8765\n"
        with patch("remote_access.find_tailscale_executable", return_value=Path("C:/Tailscale/tailscale.exe")), patch(
            "remote_access.run_tailscale",
            side_effect=[
                CommandResult(0, '{"BackendState":"Running"}'),
                CommandResult(0, serve),
            ],
        ):
            status = get_remote_status()
        self.assertTrue(status.logged_in)
        self.assertFalse(status.serve_active)
        self.assertEqual(status.serve_url, "")

    def test_status_returns_video_8443_when_music_and_video_coexist(self):
        serve = (
            "https://sample.ts.net\n|-- / proxy http://127.0.0.1:8765\n"
            "https://sample.ts.net:8443\n|-- / proxy http://127.0.0.1:8876\n"
        )
        with patch("remote_access.find_tailscale_executable", return_value=Path("C:/Tailscale/tailscale.exe")), patch(
            "remote_access.run_tailscale",
            side_effect=[
                CommandResult(0, '{"BackendState":"Running"}'),
                CommandResult(0, serve),
            ],
        ):
            status = get_remote_status()
        self.assertTrue(status.serve_active)
        self.assertEqual(status.serve_url, "https://sample.ts.net:8443/")

    def test_enable_uses_video_https_port_without_replacing_music_root(self):
        initial = RemoteStatus(True, True, "Running", False, "", "tailscale.exe")
        current = RemoteStatus(True, True, "Running", True, "https://sample.ts.net:8443/", "tailscale.exe")
        with patch("remote_access.get_remote_status", side_effect=[initial, current]), patch(
            "remote_access.run_tailscale",
            return_value=CommandResult(0, "ok"),
        ) as run:
            ok, url, _ = enable_remote_access(8876)
        self.assertTrue(ok)
        self.assertEqual(url, "https://sample.ts.net:8443/")
        run.assert_called_once_with(
            ["serve", "--yes", "--bg", "--https=8443", "8876"],
            timeout=30.0,
        )

    def test_disable_removes_only_video_https_endpoint(self):
        with patch("remote_access.run_tailscale", return_value=CommandResult(0, "")) as run:
            result = disable_remote_access()
        self.assertEqual(result.returncode, 0)
        run.assert_called_once_with(
            ["serve", "--yes", "--https=8443", "off"],
            timeout=20.0,
        )

    def test_launcher_has_external_url_button_and_open_handler(self):
        launcher = (SRC / "launcher.py").read_text(encoding="utf-8")
        self.assertIn('text="外部URLを開く"', launcher)
        self.assertIn("command=self.open_remote", launcher)
        self.assertIn("def open_remote(self)", launcher)
        self.assertIn("self.remote_url", launcher)


if __name__ == "__main__":
    unittest.main()
