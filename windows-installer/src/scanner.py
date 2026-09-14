from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path, PurePosixPath
from typing import Any

from database import initialize_database, now_iso

SUPPORTED_VIDEO_EXTENSIONS = {
    ".mkv",
    ".mp4",
    ".avi",
    ".webm",
    ".mpg",
    ".flv",
    ".m4v",
    ".mov",
    ".wmv",
}
DIRECT_CONTAINER_EXTENSIONS = {".mp4", ".m4v", ".webm"}

MIME_TYPES = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".mov": "video/quicktime",
    ".mpg": "video/mpeg",
    ".flv": "video/x-flv",
    ".wmv": "video/x-ms-wmv",
}


def normalize_relative_path(value: str | Path) -> str:
    text = str(value).replace("\\", "/").strip()
    path = PurePosixPath(text)
    parts = [part for part in path.parts if part not in ("", ".")]
    if not parts or path.is_absolute() or any(part == ".." for part in parts):
        raise ValueError("relative path is outside the video root")
    if ":" in parts[0]:
        raise ValueError("drive-qualified paths are not allowed")
    return "/".join(parts)


def _key(value: str | Path) -> str:
    return normalize_relative_path(value).casefold()


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def safe_video_path(video_root: Path | str, relative_path: str | Path) -> Path:
    root = Path(video_root).expanduser().resolve()
    normalized = normalize_relative_path(relative_path)
    candidate = root.joinpath(*normalized.split("/")).resolve(strict=False)
    if not _is_within(root, candidate):
        raise ValueError("resolved path is outside the video root")
    return candidate


def playback_support_for_extension(extension: str) -> str:
    ext = extension.casefold()
    return "DIRECT" if ext in DIRECT_CONTAINER_EXTENSIONS else "UNKNOWN"


def mime_type_for_extension(extension: str) -> str:
    return MIME_TYPES.get(extension.casefold(), "application/octet-stream")


def _insert_scan_error(
    connection: sqlite3.Connection,
    scan_run_id: int,
    *,
    relative_path: str | None,
    error_type: str,
    message: str,
    stamp: str,
) -> None:
    connection.execute(
        """
        INSERT INTO scan_errors(
            scan_run_id, relative_path, error_type, message, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (scan_run_id, relative_path, error_type, message[:1000], stamp),
    )


def scan_library(
    connection: sqlite3.Connection,
    video_root: Path | str,
) -> dict[str, Any]:
    initialize_database(connection)
    root = Path(video_root).expanduser()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError("動画フォルダーが見つかりません。")
    root = root.resolve()

    started = now_iso()
    started_perf = time.monotonic()
    cursor = connection.execute(
        """
        INSERT INTO scan_runs(started_at, status, created_at)
        VALUES (?, 'RUNNING', ?)
        """,
        (started, started),
    )
    scan_run_id = int(cursor.lastrowid)
    connection.commit()

    try:
        rows = connection.execute(
            "SELECT id, video_id, relative_path FROM video_files ORDER BY id"
        ).fetchall()
        expected: dict[str, sqlite3.Row] = {}
        errors = 0
        for row in rows:
            try:
                key = _key(row["relative_path"])
            except ValueError as exc:
                errors += 1
                _insert_scan_error(
                    connection,
                    scan_run_id,
                    relative_path=row["relative_path"],
                    error_type="INVALID_RELATIVE_PATH",
                    message=str(exc),
                    stamp=started,
                )
                continue
            if key in expected:
                errors += 1
                _insert_scan_error(
                    connection,
                    scan_run_id,
                    relative_path=row["relative_path"],
                    error_type="DUPLICATE_NORMALIZED_PATH",
                    message="正規化後の相対パスが重複しています。",
                    stamp=started,
                )
                continue
            expected[key] = row

        matched_ids: set[int] = set()
        files_found = 0
        files_matched = 0
        files_new = 0

        for directory, dirnames, filenames in os.walk(root, followlinks=False):
            directory_path = Path(directory)
            dirnames[:] = [
                name for name in dirnames
                if not (directory_path / name).is_symlink()
            ]
            for filename in filenames:
                path = directory_path / filename
                extension = path.suffix.casefold()
                if extension not in SUPPORTED_VIDEO_EXTENSIONS:
                    continue
                files_found += 1

                try:
                    resolved = path.resolve(strict=True)
                    if not _is_within(root, resolved):
                        raise ValueError("symlink resolves outside video root")
                    relative = normalize_relative_path(path.relative_to(root))
                    stat = resolved.stat()
                except (OSError, ValueError) as exc:
                    errors += 1
                    rel_for_error: str | None
                    try:
                        rel_for_error = normalize_relative_path(path.relative_to(root))
                    except Exception:
                        rel_for_error = None
                    _insert_scan_error(
                        connection,
                        scan_run_id,
                        relative_path=rel_for_error,
                        error_type="FILE_SCAN_ERROR",
                        message=str(exc),
                        stamp=started,
                    )
                    continue

                expected_row = expected.get(relative.casefold())
                if expected_row is None:
                    files_new += 1
                    connection.execute(
                        """
                        INSERT INTO scan_discoveries(
                            scan_run_id, relative_path, extension,
                            file_size, modified_time_ns, status, created_at
                        ) VALUES (?, ?, ?, ?, ?, 'NEW_FILE', ?)
                        """,
                        (
                            scan_run_id,
                            relative,
                            extension.lstrip(".").upper(),
                            int(stat.st_size),
                            int(stat.st_mtime_ns),
                            started,
                        ),
                    )
                    continue

                video_file_id = int(expected_row["id"])
                matched_ids.add(video_file_id)
                files_matched += 1
                connection.execute(
                    """
                    UPDATE video_files
                    SET file_size = ?,
                        modified_time_ns = ?,
                        playback_support = ?,
                        is_available = 1,
                        scan_status = 'MATCHED',
                        last_scanned_at = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        int(stat.st_size),
                        int(stat.st_mtime_ns),
                        playback_support_for_extension(extension),
                        started,
                        started,
                        video_file_id,
                    ),
                )

        missing_ids = [
            int(row["id"])
            for row in rows
            if int(row["id"]) not in matched_ids
        ]
        if missing_ids:
            placeholders = ",".join("?" for _ in missing_ids)
            connection.execute(
                f"""
                UPDATE video_files
                SET is_available = 0,
                    scan_status = 'MISSING',
                    last_scanned_at = ?,
                    updated_at = ?
                WHERE id IN ({placeholders})
                """,
                [started, started, *missing_ids],
            )

        files_missing = len(missing_ids)
        completed = now_iso()
        duration_ms = int((time.monotonic() - started_perf) * 1000)
        connection.execute(
            """
            UPDATE scan_runs
            SET completed_at = ?,
                status = 'SUCCESS',
                files_found = ?,
                files_matched = ?,
                files_missing = ?,
                files_new = ?,
                errors = ?,
                duration_ms = ?
            WHERE id = ?
            """,
            (
                completed,
                files_found,
                files_matched,
                files_missing,
                files_new,
                errors,
                duration_ms,
                scan_run_id,
            ),
        )
        connection.commit()
        return {
            "runId": scan_run_id,
            "status": "SUCCESS",
            "filesFound": files_found,
            "filesMatched": files_matched,
            "filesMissing": files_missing,
            "filesNew": files_new,
            "errors": errors,
            "durationMs": duration_ms,
        }
    except Exception as exc:
        connection.rollback()
        completed = now_iso()
        duration_ms = int((time.monotonic() - started_perf) * 1000)
        connection.execute(
            """
            UPDATE scan_runs
            SET completed_at = ?,
                status = 'FAILED',
                errors = errors + 1,
                duration_ms = ?
            WHERE id = ?
            """,
            (completed, duration_ms, scan_run_id),
        )
        _insert_scan_error(
            connection,
            scan_run_id,
            relative_path=None,
            error_type="SCAN_FAILED",
            message=str(exc),
            stamp=completed,
        )
        connection.commit()
        raise


def latest_scan_status(connection: sqlite3.Connection) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT id, started_at, completed_at, status,
               files_found, files_matched, files_missing, files_new,
               errors, duration_ms
        FROM scan_runs
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return {"running": False, "latest": None}

    return {
        "running": row["status"] == "RUNNING",
        "latest": {
            "runId": int(row["id"]),
            "startedAt": row["started_at"],
            "completedAt": row["completed_at"],
            "status": row["status"],
            "filesFound": int(row["files_found"]),
            "filesMatched": int(row["files_matched"]),
            "filesMissing": int(row["files_missing"]),
            "filesNew": int(row["files_new"]),
            "errors": int(row["errors"]),
            "durationMs": row["duration_ms"],
        },
    }


def resolve_video_file(
    connection: sqlite3.Connection,
    video_root: Path | str,
    video_id: int,
) -> tuple[Path, str] | None:
    row = connection.execute(
        """
        SELECT vf.relative_path, vf.extension, vf.is_available
        FROM video_files vf
        WHERE vf.video_id = ?
        """,
        (video_id,),
    ).fetchone()
    if row is None or not bool(row["is_available"]):
        return None
    try:
        path = safe_video_path(video_root, row["relative_path"])
    except ValueError:
        return None
    if not path.exists() or not path.is_file():
        return None
    root = Path(video_root).expanduser().resolve()
    resolved = path.resolve(strict=True)
    if not _is_within(root, resolved):
        return None
    return resolved, str(row["extension"])
