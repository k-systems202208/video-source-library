from __future__ import annotations

import os
import sys
from pathlib import Path


def _open_server_log():
    try:
        local = os.environ.get("LOCALAPPDATA")
        root = Path(local).expanduser() / "VideoLibrary" if local else Path.home() / ".video-library"
        log_dir = root / "Logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return (log_dir / "server.log").open("a", encoding="utf-8", buffering=1)
    except Exception:
        return open(os.devnull, "w", encoding="utf-8")


# PyInstaller windowed applications may start with stdout/stderr set to None.
# BaseHTTPRequestHandler writes access logs to stderr from send_response();
# without a stream that raises before HTTP headers are sent and Chrome reports
# ERR_EMPTY_RESPONSE. Keep a real writable stream for the whole process.
if sys.stderr is None:
    sys.stderr = _open_server_log()
if sys.stdout is None:
    sys.stdout = _open_server_log()
