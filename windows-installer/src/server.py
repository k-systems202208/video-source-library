from __future__ import annotations

import argparse
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from database import SCHEMA_VERSION, connect, initialize_database, quick_check
from library_service import get_video, get_work, library_stats, list_work_videos, list_works

APP_NAME = "VideoLibrary"
API_VERSION = 1


def default_database_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "VideoLibrary" / "library.db"
    return Path.home() / ".video-library" / "library.db"


def default_html_path() -> Path:
    return Path(__file__).with_name("video-library.html")


def _first(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    return values[0] if values else None


def _int_query(query: dict[str, list[str]], name: str) -> int | None:
    value = _first(query, name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def make_handler(database_path: Path | str, html_path: Path | str) -> type[BaseHTTPRequestHandler]:
    db_path = Path(database_path)
    ui_path = Path(html_path)

    class VideoLibraryHandler(BaseHTTPRequestHandler):
        server_version = "VideoLibrary/0.1"

        def log_message(self, format: str, *args: Any) -> None:
            super().log_message(format, *args)

        def _common_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")

        def _json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._common_headers()
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, code: str, message: str) -> None:
            self._json(status, {"error": {"code": code, "message": message}})

        def _html(self) -> None:
            if not ui_path.exists():
                self._error(500, "UI_NOT_FOUND", "Web UIが見つかりません。")
                return
            body = ui_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._common_headers()
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            parsed = urlsplit(self.path)
            path = parsed.path
            query = parse_qs(parsed.query, keep_blank_values=True)

            if path in ("/", "/index.html"):
                self._html()
                return

            try:
                with connect(db_path) as connection:
                    if path == "/api/health":
                        self._json(
                            200,
                            {
                                "status": "ok",
                                "application": APP_NAME,
                                "apiVersion": API_VERSION,
                                "schemaVersion": SCHEMA_VERSION,
                                "database": db_path.name,
                                "quickCheck": quick_check(connection),
                            },
                        )
                        return

                    if path == "/api/stats":
                        self._json(200, library_stats(connection))
                        return

                    if path == "/api/works":
                        self._json(
                            200,
                            list_works(
                                connection,
                                q=_first(query, "q"),
                                category=_first(query, "category"),
                                sort=_first(query, "sort") or "title",
                                limit=_first(query, "limit"),
                                offset=_first(query, "offset"),
                            ),
                        )
                        return

                    work_videos_match = re.fullmatch(r"/api/works/(\d+)/videos", path)
                    if work_videos_match:
                        work_id = int(work_videos_match.group(1))
                        group_id = _int_query(query, "groupId")
                        result = list_work_videos(connection, work_id, group_id=group_id)
                        if result is None:
                            self._error(404, "WORK_OR_GROUP_NOT_FOUND", "作品またはグループが見つかりません。")
                        else:
                            self._json(200, result)
                        return

                    work_match = re.fullmatch(r"/api/works/(\d+)", path)
                    if work_match:
                        result = get_work(connection, int(work_match.group(1)))
                        if result is None:
                            self._error(404, "WORK_NOT_FOUND", "作品が見つかりません。")
                        else:
                            self._json(200, result)
                        return

                    video_match = re.fullmatch(r"/api/videos/(\d+)", path)
                    if video_match:
                        result = get_video(connection, int(video_match.group(1)))
                        if result is None:
                            self._error(404, "VIDEO_NOT_FOUND", "動画が見つかりません。")
                        else:
                            self._json(200, result)
                        return
            except ValueError as exc:
                self._error(400, "INVALID_QUERY", str(exc))
                return
            except Exception:
                self._error(500, "INTERNAL_ERROR", "サーバー内部でエラーが発生しました。")
                return

            self._error(404, "NOT_FOUND", "指定されたリソースが見つかりません。")

    return VideoLibraryHandler


def create_server(
    database_path: Path | str,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    html_path: Path | str | None = None,
) -> ThreadingHTTPServer:
    db_path = Path(database_path)
    with connect(db_path) as connection:
        initialize_database(connection)
    handler = make_handler(db_path, html_path or default_html_path())
    return ThreadingHTTPServer((host, port), handler)


def main() -> int:
    parser = argparse.ArgumentParser(description="自宅動画ライブラリ Web server")
    parser.add_argument("--database", type=Path, default=default_database_path())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server = create_server(args.database, host=args.host, port=args.port)
    print(f"Video Library: http://{args.host}:{server.server_port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
