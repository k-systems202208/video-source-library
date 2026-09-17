from __future__ import annotations

import argparse
import json
import os
import re
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from app_config import configured_video_root, default_config_path
from app_version import APP_VERSION
from backup_restore import cancel_restore, create_manual_backup, list_backups, pending_restore, restore_status, schedule_restore
from database import SCHEMA_VERSION, connect, initialize_database, quick_check
from identity_service import local_owner_user, resolve_tailscale_user
from library_service import get_video, get_work, library_stats, list_work_videos, list_works
from local_auth import LocalOwnerAuth, cookie_value, session_cookie_header
from matroska_audio import apply_patch_to_chunk, preferred_japanese_audio_patch
from playback_compat import prepare_browser_playback
from scan_diagnostics import diagnostics_csv_bytes, diagnostics_json_bytes, scan_diagnostics
from scan_progress import ScanProgressStore
from scan_runner import scan_library
from subtitle_stream import resolve_subtitle_file, subtitle_file_to_webvtt
from scanner import latest_scan_status, mime_type_for_extension, resolve_video_file
from tailscale_identity import parse_tailscale_identity
from tmdb_images import resolve_cached_tmdb_image
from user_state import (
    PlaybackSessionStore,
    continue_watching,
    current_user,
    favorite_videos,
    favorite_works,
    history,
    next_up,
    recent_works,
    record_progress,
    set_video_favorite,
    set_watched,
    set_work_favorite,
    start_playback,
)

APP_NAME = "VideoLibrary"
API_VERSION = 1
CHUNK_SIZE = 1024 * 1024
MAX_JSON_BODY = 64 * 1024
CONTROL_HEADER = "X-Video-Library-Control-Secret"
STATIC_FILES = {
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json; charset=utf-8"),
    "/service-worker.js": ("service-worker.js", "text/javascript; charset=utf-8"),
    "/offline.html": ("offline.html", "text/html; charset=utf-8"),
    "/diagnostics.html": ("diagnostics.html", "text/html; charset=utf-8"),
    "/icon.svg": ("icon.svg", "image/svg+xml"),
    "/cinema-header.svg": ("cinema-header.svg", "image/svg+xml"),
    "/cinema-sidebar.svg": ("cinema-sidebar.svg", "image/svg+xml"),
    "/cinema-footer.svg": ("cinema-footer.svg", "image/svg+xml"),
}


class RangeNotSatisfiable(ValueError):
    pass


def default_database_path() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    return Path(local) / "VideoLibrary" / "library.db" if local else Path.home() / ".video-library" / "library.db"


def default_html_path() -> Path:
    return Path(__file__).with_name("video-library.html")


def default_data_root() -> Path:
    return default_database_path().parent


def _first(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    return values[0] if values else None


def _int_query(query: dict[str, list[str]], name: str) -> int | None:
    value = _first(query, name)
    if value in (None, ""):
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
    if not spec or "," in spec or "-" not in spec:
        raise RangeNotSatisfiable("invalid byte range")
    start_text, end_text = spec.split("-", 1)
    try:
        if start_text == "":
            suffix = int(end_text)
            if suffix <= 0:
                raise RangeNotSatisfiable("invalid suffix range")
            return max(0, size - suffix), size - 1
        start = int(start_text)
        if start < 0 or start >= size:
            raise RangeNotSatisfiable("range starts beyond resource")
        end = size - 1 if end_text == "" else int(end_text)
        if end < start:
            raise RangeNotSatisfiable("range end precedes start")
        return start, min(end, size - 1)
    except ValueError as exc:
        if isinstance(exc, RangeNotSatisfiable):
            raise
        raise RangeNotSatisfiable("invalid byte range") from exc


def make_handler(database_path: Path | str, html_path: Path | str, *, video_root: Path | str | None = None,
                 owner_auth: LocalOwnerAuth | None = None, data_root: Path | str | None = None) -> type[BaseHTTPRequestHandler]:
    db_path = Path(database_path)
    ui_path = Path(html_path)
    static_root = ui_path.parent
    root_path = Path(video_root).expanduser() if video_root is not None else None
    app_data_root = Path(data_root) if data_root is not None else db_path.parent
    backup_dir = app_data_root / "Backups"
    scan_lock = threading.Lock()
    scan_progress = ScanProgressStore()
    playback_sessions = PlaybackSessionStore()

    class Handler(BaseHTTPRequestHandler):
        server_version = f"VideoLibrary/{APP_VERSION}"

        def _common(self, *, cache: str = "no-store") -> None:
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("X-Frame-Options", "SAMEORIGIN")

        def _json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._common()
            self.end_headers()
            self.wfile.write(body)

        def _download(self, body: bytes, content_type: str, filename: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(body)))
            self._common()
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, code: str, message: str) -> None:
            self._json(status, {"error": {"code": code, "message": message}})

        def _redirect(self, location: str, *, cookie: str | None = None) -> None:
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", location)
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.send_header("Content-Length", "0")
            self._common()
            self.end_headers()

        def _html(self) -> None:
            if not ui_path.exists():
                self._error(500, "UI_NOT_FOUND", "Web UIが見つかりません。")
                return
            text = ui_path.read_text(encoding="utf-8")
            if "manifest.webmanifest" not in text:
                text = text.replace("</head>", '<link rel="manifest" href="/manifest.webmanifest"><link rel="icon" href="/icon.svg"></head>')
            if "diagnostics.html" not in text:
                text = text.replace(
                    '<button class="ghost" id="scanButton">再スキャン</button>',
                    '<a class="ghost" style="text-decoration:none" href="/diagnostics.html">診断</a><button class="ghost" id="scanButton">再スキャン</button>',
                )
            if "serviceWorker.register" not in text:
                text = text.replace("</body>", "<script>if('serviceWorker' in navigator){window.addEventListener('load',()=>navigator.serviceWorker.register('/service-worker.js').catch(()=>{}));}</script></body>")
            body = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._common()
            self.end_headers()
            self.wfile.write(body)

        def _static(self, path: str) -> bool:
            item = STATIC_FILES.get(path)
            if not item:
                return False
            filename, content_type = item
            target = static_root / filename
            if not target.is_file():
                self._error(404, "NOT_FOUND", "指定されたリソースが見つかりません。")
                return True
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self._common(cache="public, max-age=300")
            self.end_headers()
            self.wfile.write(body)
            return True

        def _body(self) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("invalid Content-Length") from exc
            if length < 0 or length > MAX_JSON_BODY:
                raise ValueError("request body is too large")
            if length == 0:
                return {}
            try:
                value = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception as exc:
                raise ValueError("invalid JSON body") from exc
            if not isinstance(value, dict):
                raise ValueError("JSON body must be an object")
            return value

        def _origin_ok(self) -> bool:
            origin = self.headers.get("Origin")
            if not origin:
                return True
            parsed = urlsplit(origin)
            return bool(self.headers.get("Host") and parsed.netloc == self.headers.get("Host") and parsed.scheme in {"http", "https"})

        def _loopback_peer(self) -> bool:
            return str(self.client_address[0]) in {"127.0.0.1", "::1"}

        def _request_user(self, connection) -> dict[str, Any] | None:
            if owner_auth is None:
                return local_owner_user(connection)
            session = cookie_value(self.headers.get("Cookie"))
            if session and owner_auth.validate_session(session):
                return local_owner_user(connection)
            host = str(self.headers.get("Host") or "").split(":", 1)[0].casefold()
            if self._loopback_peer() and host not in {"127.0.0.1", "localhost", "[::1]"}:
                identity = parse_tailscale_identity(self.headers)
                if identity is not None:
                    return resolve_tailscale_user(connection, identity)
            return None

        def _require_user(self, connection) -> dict[str, Any] | None:
            user = self._request_user(connection)
            if user is None:
                self._error(401, "AUTH_REQUIRED", "利用者認証が必要です。")
            return user

        def _require_owner(self, connection) -> dict[str, Any] | None:
            user = self._require_user(connection)
            if user is not None and not bool(user.get("isOwner")):
                self._error(403, "OWNER_REQUIRED", "オーナー権限が必要です。")
                return None
            return user

        def _serve_video(self, video_id: int, *, head: bool = False) -> None:
            if root_path is None:
                self._error(409, "VIDEO_ROOT_NOT_CONFIGURED", "動画フォルダーが設定されていません。")
                return
            with connect(db_path) as connection:
                resolved = resolve_video_file(connection, root_path, video_id)
                video = get_video(connection, video_id)
            if resolved is None:
                self._error(404, "VIDEO_FILE_NOT_FOUND", "動画ファイルが見つかりません。")
                return
            path, extension = resolved
            file_info = (video or {}).get("file") or {}
            try:
                prepared = prepare_browser_playback(
                    path,
                    "." + extension.lstrip("."),
                    file_info.get("videoCodec"),
                    file_info.get("audioCodec"),
                    app_data_root / "PlaybackCache",
                )
            except RuntimeError as exc:
                self._error(503, "PLAYBACK_PREPARATION_FAILED", f"再生用動画の準備に失敗しました。 {exc}")
                return
            path = prepared.path
            extension = path.suffix
            audio_patch = (
                preferred_japanese_audio_patch(path)
                if not prepared.transcoded and extension.casefold() in {".mkv", ".webm"}
                else None
            )
            try:
                size = path.stat().st_size
                byte_range = parse_range_header(self.headers.get("Range"), size)
            except RangeNotSatisfiable:
                self.send_response(416); self.send_header("Content-Range", f"bytes */{path.stat().st_size}")
                self.send_header("Accept-Ranges", "bytes"); self.send_header("Content-Length", "0"); self._common(); self.end_headers(); return
            except OSError:
                self._error(404, "VIDEO_FILE_NOT_FOUND", "動画ファイルが見つかりません。"); return
            status = 200 if byte_range is None else 206
            start, end = (0, size - 1) if byte_range is None else byte_range
            length = end - start + 1
            self.send_response(status)
            self.send_header("Content-Type", prepared.content_type)
            self.send_header("X-Video-Library-Playback", "transcoded" if prepared.transcoded else "direct")
            if prepared.audio_language:
                self.send_header("X-Video-Library-Audio-Language", prepared.audio_language)
            self.send_header("Accept-Ranges", "bytes"); self.send_header("Content-Length", str(length))
            if audio_patch is not None:
                self.send_header("X-Video-Library-Audio-Preference", "ja")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self._common(); self.end_headers()
            if head:
                return
            try:
                with path.open("rb") as handle:
                    handle.seek(start); remaining = length
                    while remaining > 0:
                        chunk_start = handle.tell()
                        chunk = handle.read(min(CHUNK_SIZE, remaining))
                        if not chunk:
                            break
                        chunk = apply_patch_to_chunk(chunk, chunk_start, audio_patch)
                        self.wfile.write(chunk); remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _serve_subtitle(self, subtitle_id: int, *, head: bool = False) -> None:
            if root_path is None:
                self._error(409, "VIDEO_ROOT_NOT_CONFIGURED", "動画フォルダーが設定されていません。")
                return
            with connect(db_path) as connection:
                resolved = resolve_subtitle_file(connection, root_path, subtitle_id)
            if resolved is None:
                self._error(404, "SUBTITLE_FILE_NOT_FOUND", "字幕ファイルが見つかりません。")
                return
            subtitle_path, extension = resolved
            try:
                body = subtitle_file_to_webvtt(subtitle_path, extension)
            except OSError:
                self._error(404, "SUBTITLE_FILE_NOT_FOUND", "字幕ファイルが見つかりません。")
                return
            except ValueError:
                self._error(415, "SUBTITLE_FORMAT_UNSUPPORTED", "この字幕形式は再生できません。")
                return
            except Exception:
                self._error(500, "SUBTITLE_CONVERSION_FAILED", "字幕の変換に失敗しました。")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/vtt; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._common(cache="no-store")
            self.end_headers()
            if not head:
                self.wfile.write(body)

        def _serve_tmdb_image(self, kind: str, work_id: int, *, head: bool = False) -> None:
            with connect(db_path) as connection:
                resolved = resolve_cached_tmdb_image(connection, app_data_root / "TMDbImages", work_id, kind)
            if resolved is None:
                self._error(404, "TMDB_IMAGE_NOT_FOUND", "TMDb画像が見つかりません。")
                return
            image_path, content_type = resolved
            try:
                size = image_path.stat().st_size
            except OSError:
                self._error(404, "TMDB_IMAGE_NOT_FOUND", "TMDb画像が見つかりません。")
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            self._common(cache="public, max-age=3600")
            self.end_headers()
            if not head:
                try:
                    self.wfile.write(image_path.read_bytes())
                except (BrokenPipeError, ConnectionResetError):
                    pass

        def do_GET(self) -> None:
            parsed = urlsplit(self.path); path = parsed.path; query = parse_qs(parsed.query, keep_blank_values=True)
            if path in ("/", "/index.html"):
                self._html(); return
            if self._static(path):
                return
            if path == "/api/local-auth/exchange":
                if owner_auth is None or not self._loopback_peer():
                    self._error(404, "NOT_FOUND", "指定されたリソースが見つかりません。"); return
                token = _first(query, "token") or ""
                if not owner_auth.consume_one_time_token(token):
                    self._error(401, "INVALID_OWNER_TOKEN", "オーナートークンが無効または期限切れです。"); return
                issue = owner_auth.issue_session()
                self._redirect("/", cookie=session_cookie_header(issue)); return
            subtitle = re.fullmatch(r"/subtitle/(\d+)\.vtt", path)
            if subtitle:
                self._serve_subtitle(int(subtitle.group(1))); return
            tmdb_image = re.fullmatch(r"/tmdb-image/(poster|backdrop)/(\d+)", path)
            if tmdb_image:
                self._serve_tmdb_image(tmdb_image.group(1), int(tmdb_image.group(2))); return
            stream = re.fullmatch(r"/video/(\d+)", path)
            if stream:
                self._serve_video(int(stream.group(1))); return

            if path == "/api/scan/status":
                live = scan_progress.snapshot()
                if live["startedAt"] is not None and live["running"]:
                    self._json(200, {
                        "running": True,
                        "latest": None,
                        "videoRootConfigured": root_path is not None,
                        "progress": live,
                    })
                    return

            try:
                with connect(db_path) as connection:
                    user = self._request_user(connection); user_id = int(user["id"]) if user else None
                    if path == "/api/health":
                        self._json(200, {"status": "ok", "application": APP_NAME, "version": APP_VERSION, "apiVersion": API_VERSION,
                                         "schemaVersion": SCHEMA_VERSION, "database": db_path.name, "quickCheck": quick_check(connection),
                                         "videoRootConfigured": root_path is not None}); return
                    if path == "/api/current-user":
                        self._json(200, {"authenticated": user is not None, "user": user}); return
                    if path == "/api/stats": self._json(200, library_stats(connection)); return
                    if path == "/api/scan/status":
                        value = latest_scan_status(connection)
                        live = scan_progress.snapshot()
                        value["videoRootConfigured"] = root_path is not None
                        value["progress"] = live if live["startedAt"] is not None else None
                        if live["startedAt"] is not None:
                            value["running"] = bool(live["running"])
                        self._json(200, value); return
                    if path in {"/api/admin/scan-diagnostics", "/api/admin/scan-diagnostics.json", "/api/admin/scan-diagnostics.csv"}:
                        if self._require_owner(connection) is None: return
                        value = scan_diagnostics(connection, run_id=_int_query(query, "runId"))
                        if path.endswith(".json"):
                            self._download(diagnostics_json_bytes(value), "application/json; charset=utf-8", "scan-diagnostics.json"); return
                        if path.endswith(".csv"):
                            self._download(diagnostics_csv_bytes(value), "text/csv; charset=utf-8", "scan-diagnostics.csv"); return
                        self._json(200, value); return
                    if path == "/api/works":
                        self._json(200, list_works(connection, user_id=user_id, q=_first(query, "q"), category=_first(query, "category"),
                                                   sort=_first(query, "sort") or "title", limit=_first(query, "limit"), offset=_first(query, "offset"))); return
                    if path.startswith("/api/me/"):
                        user = self._require_user(connection)
                        if user is None: return
                        uid = int(user["id"])
                        if path == "/api/me/favorite-works": self._json(200, favorite_works(connection, uid)); return
                        if path == "/api/me/favorite-videos": self._json(200, favorite_videos(connection, uid)); return
                        if path == "/api/me/continue-watching": self._json(200, continue_watching(connection, uid)); return
                        if path == "/api/me/next-up": self._json(200, next_up(connection, uid)); return
                        if path == "/api/me/recent-works": self._json(200, recent_works(connection, uid)); return
                        if path == "/api/me/history": self._json(200, history(connection, uid, limit=_int_query(query, "limit") or 100, offset=_int_query(query, "offset") or 0)); return
                    if path == "/api/backups":
                        if self._require_owner(connection) is None: return
                        self._json(200, {"items": list_backups(backup_dir), "pendingRestore": pending_restore(app_data_root), "restoreStatus": restore_status(app_data_root)}); return
                    work_videos = re.fullmatch(r"/api/works/(\d+)/videos", path)
                    if work_videos:
                        value = list_work_videos(connection, int(work_videos.group(1)), user_id=user_id, group_id=_int_query(query, "groupId"))
                        self._json(200, value) if value is not None else self._error(404, "WORK_OR_GROUP_NOT_FOUND", "作品またはグループが見つかりません。"); return
                    work = re.fullmatch(r"/api/works/(\d+)", path)
                    if work:
                        value = get_work(connection, int(work.group(1)), user_id=user_id)
                        self._json(200, value) if value is not None else self._error(404, "WORK_NOT_FOUND", "作品が見つかりません。"); return
                    video = re.fullmatch(r"/api/videos/(\d+)", path)
                    if video:
                        value = get_video(connection, int(video.group(1)), user_id=user_id)
                        self._json(200, value) if value is not None else self._error(404, "VIDEO_NOT_FOUND", "動画が見つかりません。"); return
            except LookupError as exc:
                if str(exc) == "SCAN_RUN_NOT_FOUND":
                    self._error(404, "SCAN_RUN_NOT_FOUND", "指定されたスキャン結果が見つかりません。"); return
                self._error(404, "NOT_FOUND", "指定されたデータが見つかりません。"); return
            except ValueError as exc:
                self._error(400, "INVALID_QUERY", str(exc)); return
            except Exception:
                self._error(500, "INTERNAL_ERROR", "サーバー内部でエラーが発生しました。"); return
            self._error(404, "NOT_FOUND", "指定されたリソースが見つかりません。")

        def do_HEAD(self) -> None:
            subtitle = re.fullmatch(r"/subtitle/(\d+)\.vtt", urlsplit(self.path).path)
            if subtitle:
                self._serve_subtitle(int(subtitle.group(1)), head=True); return
            tmdb_image = re.fullmatch(r"/tmdb-image/(poster|backdrop)/(\d+)", urlsplit(self.path).path)
            if tmdb_image:
                self._serve_tmdb_image(tmdb_image.group(1), int(tmdb_image.group(2)), head=True); return
            stream = re.fullmatch(r"/video/(\d+)", urlsplit(self.path).path)
            if stream:
                self._serve_video(int(stream.group(1)), head=True); return
            self.send_response(405); self.send_header("Allow", "GET, POST, PUT"); self.send_header("Content-Length", "0"); self._common(); self.end_headers()

        def do_PUT(self) -> None:
            if not self._origin_ok():
                self._error(403, "ORIGIN_NOT_ALLOWED", "このOriginからの状態変更は許可されていません。"); return
            path = urlsplit(self.path).path
            try:
                payload = self._body()
                with connect(db_path) as connection:
                    user = self._require_user(connection)
                    if user is None: return
                    uid = int(user["id"])
                    match = re.fullmatch(r"/api/me/works/(\d+)/favorite", path)
                    if match:
                        if not isinstance(payload.get("favorite"), bool): raise ValueError("favorite must be boolean")
                        self._json(200, set_work_favorite(connection, uid, int(match.group(1)), payload["favorite"])); return
                    match = re.fullmatch(r"/api/me/videos/(\d+)/favorite", path)
                    if match:
                        if not isinstance(payload.get("favorite"), bool): raise ValueError("favorite must be boolean")
                        self._json(200, set_video_favorite(connection, uid, int(match.group(1)), payload["favorite"])); return
                    match = re.fullmatch(r"/api/me/videos/(\d+)/watched", path)
                    if match:
                        if not isinstance(payload.get("watched"), bool): raise ValueError("watched must be boolean")
                        self._json(200, set_watched(connection, uid, int(match.group(1)), payload["watched"])); return
            except LookupError as exc:
                code = str(exc); self._error(404, code, "作品が見つかりません。" if code == "WORK_NOT_FOUND" else "動画が見つかりません。"); return
            except ValueError as exc:
                self._error(400, "INVALID_REQUEST", str(exc)); return
            except Exception:
                self._error(500, "INTERNAL_ERROR", "状態更新に失敗しました。"); return
            self._error(404, "NOT_FOUND", "指定されたリソースが見つかりません。")

        def do_POST(self) -> None:
            if not self._origin_ok():
                self._error(403, "ORIGIN_NOT_ALLOWED", "このOriginからの状態変更は許可されていません。"); return
            path = urlsplit(self.path).path
            if path == "/api/local-auth/token":
                if owner_auth is None or not self._loopback_peer() or not owner_auth.control_secret_matches(self.headers.get(CONTROL_HEADER, "")):
                    self._error(404, "NOT_FOUND", "指定されたリソースが見つかりません。"); return
                try:
                    payload = self._body(); token = str(payload.get("token") or ""); ttl = int(payload.get("expiresInSeconds") or 60)
                    actual = owner_auth.register_one_time_token(token, ttl_seconds=ttl)
                    self._json(201, {"registered": True, "expiresInSeconds": actual}); return
                except (ValueError, TypeError) as exc:
                    self._error(400, "INVALID_REQUEST", str(exc)); return
            if path == "/api/scan":
                with connect(db_path) as connection:
                    if self._require_owner(connection) is None: return
                if root_path is None:
                    self._error(409, "VIDEO_ROOT_NOT_CONFIGURED", "動画フォルダーが設定されていません。")
                    return
                if not scan_lock.acquire(blocking=False):
                    self._error(409, "SCAN_ALREADY_RUNNING", "ライブラリスキャンは既に実行中です."); return

                scan_progress.start()

                def scan_worker() -> None:
                    try:
                        with connect(db_path) as scan_connection:
                            result = scan_library(
                                scan_connection,
                                root_path,
                                progress_callback=scan_progress.update,
                            )
                        scan_progress.complete(result)
                    except Exception as exc:
                        scan_progress.fail(str(exc))
                    finally:
                        scan_lock.release()

                threading.Thread(
                    target=scan_worker,
                    name="VideoLibraryScan",
                    daemon=True,
                ).start()
                self._json(202, {"accepted": True, "status": "RUNNING", "progress": scan_progress.snapshot()})
                return
            if path.startswith("/api/backups/"):
                try:
                    with connect(db_path) as connection:
                        if self._require_owner(connection) is None: return
                    if path == "/api/backups/create":
                        self._json(201, create_manual_backup(database_path=db_path, backup_dir=backup_dir)); return
                    if path == "/api/backups/restore":
                        payload = self._body(); name = str(payload.get("backupName") or "")
                        self._json(202, schedule_restore(name, data_root=app_data_root, backup_dir=backup_dir)); return
                    if path == "/api/backups/restore/cancel":
                        self._json(200, {"cancelled": cancel_restore(app_data_root)}); return
                except (ValueError, FileNotFoundError) as exc:
                    self._error(400, "BACKUP_ERROR", str(exc)); return
                except Exception:
                    self._error(500, "BACKUP_ERROR", "バックアップ操作に失敗しました."); return
            try:
                match = re.fullmatch(r"/api/me/videos/(\d+)/playback/(start|progress)", path)
                if match:
                    video_id = int(match.group(1)); action = match.group(2)
                    with connect(db_path) as connection:
                        user = self._require_user(connection)
                        if user is None: return
                        uid = int(user["id"])
                        if action == "start":
                            resume = start_playback(connection, uid, video_id)
                            session_id = playback_sessions.start(uid, video_id)
                            self._json(200, {"videoId": video_id, "playSessionId": session_id, "resume": resume}); return
                    payload = self._body(); session_id = payload.get("playSessionId"); position = payload.get("positionMs")
                    duration = payload.get("durationMs"); event = payload.get("event", "timeupdate")
                    if not isinstance(session_id, str) or not session_id: raise ValueError("playSessionId is required")
                    if not isinstance(position, int) or isinstance(position, bool): raise ValueError("positionMs must be an integer")
                    if duration is not None and (not isinstance(duration, int) or isinstance(duration, bool)): raise ValueError("durationMs must be an integer or null")
                    if event not in {"timeupdate", "pause", "ended", "pagehide", "visibilitychange"}: raise ValueError("invalid playback event")
                    increment = playback_sessions.progress(session_id, uid, video_id, position, duration)
                    with connect(db_path) as connection:
                        state = record_progress(connection, uid, video_id, position_ms=position, duration_ms=duration, event=event, increment_play_count=increment)
                    self._json(200, {"videoId": video_id, "state": state}); return
            except LookupError:
                self._error(404, "VIDEO_NOT_FOUND", "動画が見つかりません."); return
            except ValueError as exc:
                self._error(400, "INVALID_REQUEST", str(exc)); return
            except Exception:
                self._error(500, "INTERNAL_ERROR", "再生状態の更新に失敗しました."); return
            self._error(404, "NOT_FOUND", "指定されたリソースが見つかりません.")

    return Handler


def create_server(database_path: Path | str, *, host: str = "127.0.0.1", port: int = 8876,
                  html_path: Path | str | None = None, video_root: Path | str | None = None,
                  config_path: Path | str | None = None, owner_control_secret: str | None = None,
                  data_root: Path | str | None = None) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Video Library server must bind to localhost")
    db_path = Path(database_path)
    with connect(db_path) as connection:
        initialize_database(connection)
        local_owner_user(connection)
    root = configured_video_root(config_path=config_path, override=video_root)
    auth = LocalOwnerAuth(owner_control_secret) if owner_control_secret else None
    handler = make_handler(db_path, html_path or default_html_path(), video_root=root, owner_auth=auth, data_root=data_root or db_path.parent)
    return ThreadingHTTPServer((host, port), handler)


def main() -> int:
    parser = argparse.ArgumentParser(description="自宅動画ライブラリ Web server")
    parser.add_argument("--database", type=Path, default=default_database_path())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8876)
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--video-root", type=Path)
    args = parser.parse_args()
    server = create_server(args.database, host=args.host, port=args.port, video_root=args.video_root, config_path=args.config)
    print(f"Video Library: http://{args.host}:{server.server_port}/")
    print("NOTE: direct server mode is localhost developer mode. Use launcher.py for owner-cookie authentication.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())