from __future__ import annotations

import argparse
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from app_config import configured_video_root, default_config_path
from database import SCHEMA_VERSION, connect, initialize_database, quick_check
from library_service import get_video, get_work, library_stats, list_work_videos, list_works
from scanner import (
    latest_scan_status,
    mime_type_for_extension,
    resolve_video_file,
    scan_library,
)

APP_NAME = "VideoLibrary"
API_VERSION = 1
CHUNK_SIZE = 1024 * 1024


class RangeNotSatisfiable(ValueError):
    pass


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


def parse_range_header(header: str | None, size: int) -> tuple[int, int] | None:
    if header is None:
        return None
    if size <= 0:
        raise RangeNotSatisfiable("empty resource")
    text = header.strip()
    if not text.startswith("bytes="):
        raise RangeNotSatisfiable("unsupported range unit")
    spec = text[6:].strip()
    if not spec or "," in spec:
        raise RangeNotSatisfiable("multiple or empty ranges are not supported")
    if "-" not in spec:
        raise RangeNotSatisfiable("invalid byte range")
    start_text, end_text = spec.split("-", 1)

    try:
        if start_text == "":
            suffix = int(end_text)
            if suffix <= 0:
                raise RangeNotSatisfiable("invalid suffix range")
            start = max(0, size - suffix)
            end = size - 1
        else:
            start = int(start_text)
            if start < 0 or start >= size:
                raise RangeNotSatisfiable("range starts beyond resource")
            if end_text == "":
                end = size - 1
            else:
                end = int(end_text)
                if end < start:
                    raise RangeNotSatisfiable("range end precedes start")
                end = min(end, size - 1)
    except ValueError as exc:
        if isinstance(exc, RangeNotSatisfiable):
            raise
        raise RangeNotSatisfiable("invalid byte range") from exc
    return start, end


def make_handler(
    database_path: Path | str,
    html_path: Path | str,
    *,
    video_root: Path | str | None = None,
) -> type[BaseHTTPRequestHandler]:
    db_path = Path(database_path)
    ui_path = Path(html_path)
    root_path = Path(video_root).expanduser() if video_root is not None else None
    scan_lock = threading.Lock()

    class VideoLibraryHandler(BaseHTTPRequestHandler):
        server_version = "VideoLibrary/0.2"

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

        def _serve_video(self, video_id: int, *, head_only: bool = False) -> None:
            if root_path is None:
                self._error(409, "VIDEO_ROOT_NOT_CONFIGURED", "動画フォルダーが設定されていません。")
                return

            with connect(db_path) as connection:
                resolved = resolve_video_file(connection, root_path, video_id)
            if resolved is None:
                self._error(404, "VIDEO_FILE_NOT_FOUND", "動画ファイルが見つかりません。")
                return

            path, extension = resolved
            try:
                size = path.stat().st_size
                byte_range = parse_range_header(self.headers.get("Range"), size)
            except RangeNotSatisfiable:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{path.stat().st_size}")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", "0")
                self._common_headers()
                self.end_headers()
                return
            except OSError:
                self._error(404, "VIDEO_FILE_NOT_FOUND", "動画ファイルが見つかりません。")
                return

            if byte_range is None:
                status = 200
                start, end = 0, size - 1
            else:
                status = 206
                start, end = byte_range

            length = max(0, end - start + 1)
            self.send_response(status)
            self.send_header("Content-Type", mime_type_for_extension("." + extension.lstrip(".")))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self._common_headers()
            self.end_headers()

            if head_only or length == 0:
                return

            try:
                with path.open("rb") as handle:
                    handle.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = handle.read(min(CHUNK_SIZE, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                return

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            path = parsed.path
            query = parse_qs(parsed.query, keep_blank_values=True)

            if path in ("/", "/index.html"):
                self._html()
                return

            stream_match = re.fullmatch(r"/video/(\d+)", path)
            if stream_match:
                self._serve_video(int(stream_match.group(1)))
                return

            try:
                with connect(db_path) as connection:
                    if path == "/api/health":
                        self._json(200,{"status":"ok","application":APP_NAME,"apiVersion":API_VERSION,"schemaVersion":SCHEMA_VERSION,"database":db_path.name,"quickCheck":quick_check(connection),"videoRootConfigured":root_path is not None})
                        return
                    if path == "/api/stats":
                        self._json(200, library_stats(connection)); return
                    if path == "/api/scan/status":
                        result = latest_scan_status(connection); result["videoRootConfigured"] = root_path is not None; self._json(200, result); return
                    if path == "/api/works":
                        self._json(200,list_works(connection,q=_first(query,"q"),category=_first(query,"category"),sort=_first(query,"sort") or "title",limit=_first(query,"limit"),offset=_first(query,"offset"))); return
                    work_videos_match = re.fullmatch(r"/api/works/(\d+)/videos", path)
                    if work_videos_match:
                        work_id=int(work_videos_match.group(1)); group_id=_int_query(query,"groupId"); result=list_work_videos(connection,work_id,group_id=group_id)
                        if result is None:self._error(404,"WORK_OR_GROUP_NOT_FOUND","作品またはグループが見つかりません。")
                        else:self._json(200,result)
                        return
                    work_match = re.fullmatch(r"/api/works/(\d+)", path)
                    if work_match:
                        result=get_work(connection,int(work_match.group(1)))
                        if result is None:self._error(404,"WORK_NOT_FOUND","作品が見つかりません。")
                        else:self._json(200,result)
                        return
                    video_match = re.fullmatch(r"/api/videos/(\d+)", path)
                    if video_match:
                        result=get_video(connection,int(video_match.group(1)))
                        if result is None:self._error(404,"VIDEO_NOT_FOUND","動画が見つかりません。")
                        else:self._json(200,result)
                        return
            except ValueError as exc:
                self._error(400,"INVALID_QUERY",str(exc)); return
            except Exception:
                self._error(500,"INTERNAL_ERROR","サーバー内部でエラーが発生しました。"); return
            self._error(404,"NOT_FOUND","指定されたリソースが見つかりません。")

        def do_HEAD(self) -> None:
            path=urlsplit(self.path).path; stream_match=re.fullmatch(r"/video/(\d+)",path)
            if stream_match:self._serve_video(int(stream_match.group(1)),head_only=True); return
            self.send_response(405); self.send_header("Allow","GET, POST"); self.send_header("Content-Length","0"); self._common_headers(); self.end_headers()

        def do_POST(self) -> None:
            path=urlsplit(self.path).path
            if path!="/api/scan":self._error(404,"NOT_FOUND","指定されたリソースが見つかりません。"); return
            if root_path is None:self._error(409,"VIDEO_ROOT_NOT_CONFIGURED","動画フォルダーが設定されていません。"); return
            if not scan_lock.acquire(blocking=False):self._error(409,"SCAN_ALREADY_RUNNING","ライブラリスキャンは既に実行中です。"); return
            try:
                with connect(db_path) as connection:result=scan_library(connection,root_path)
                self._json(200,result)
            except FileNotFoundError as exc:self._error(400,"VIDEO_ROOT_NOT_FOUND",str(exc))
            except Exception:self._error(500,"SCAN_FAILED","ライブラリスキャンに失敗しました。")
            finally:scan_lock.release()

    return VideoLibraryHandler


def create_server(database_path:Path|str,*,host:str="127.0.0.1",port:int=8765,html_path:Path|str|None=None,video_root:Path|str|None=None,config_path:Path|str|None=None)->ThreadingHTTPServer:
    db_path=Path(database_path)
    with connect(db_path) as connection:initialize_database(connection)
    resolved_root=configured_video_root(config_path=config_path,override=video_root)
    handler=make_handler(db_path,html_path or default_html_path(),video_root=resolved_root)
    return ThreadingHTTPServer((host,port),handler)


def main()->int:
    parser=argparse.ArgumentParser(description="自宅動画ライブラリ Web server"); parser.add_argument("--database",type=Path,default=default_database_path()); parser.add_argument("--host",default="127.0.0.1"); parser.add_argument("--port",type=int,default=8765); parser.add_argument("--config",type=Path,default=default_config_path()); parser.add_argument("--video-root",type=Path); args=parser.parse_args()
    server=create_server(args.database,host=args.host,port=args.port,video_root=args.video_root,config_path=args.config); print(f"Video Library: http://{args.host}:{server.server_port}/")
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
    return 0


if __name__=="__main__":raise SystemExit(main())
