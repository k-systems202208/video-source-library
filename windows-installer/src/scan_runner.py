from __future__ import annotations

import os
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from database import now_iso
from scanner import SUPPORTED_VIDEO_EXTENSIONS, normalize_relative_path, scan_library as _scan_library
from subtitle_tools import UNSUPPORTED_SUBTITLE_EXTENSIONS

ProgressCallback = Callable[[dict[str, Any]], None]


def _relaxed_text(value: str | Path) -> str:
    """Normalize path text while preserving '?' as a one-character wildcard marker."""
    normalized = normalize_relative_path(value).casefold()
    decomposed = unicodedata.normalize("NFKD", normalized)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def relaxed_path_matches(expected_path: str | Path, actual_path: str | Path) -> bool:
    """Match a metadata path containing '?' against an actual Unicode path.

    Windows does not allow '?' in a real filename, so a '?' that survived in the
    audited metadata can safely be treated as exactly one unknown filename
    character. All other characters must match after Unicode NFKD normalization
    and removal of combining marks. Path separators must still match exactly.
    """
    expected = _relaxed_text(expected_path)
    actual = _relaxed_text(actual_path)
    if len(expected) != len(actual):
        return False
    for expected_char, actual_char in zip(expected, actual):
        if expected_char == actual_char:
            continue
        if expected_char == "?" and actual_char != "/":
            continue
        return False
    return True


def _actual_video_paths(video_root: Path) -> list[str]:
    paths: list[str] = []
    for directory, dirnames, filenames in os.walk(video_root, followlinks=False):
        directory_path = Path(directory)
        dirnames[:] = [name for name in dirnames if not (directory_path / name).is_symlink()]
        for filename in filenames:
            path = directory_path / filename
            if path.suffix.casefold() not in SUPPORTED_VIDEO_EXTENSIONS:
                continue
            try:
                relative = normalize_relative_path(path.relative_to(video_root))
            except ValueError:
                continue
            paths.append(relative)
    return paths


def repair_unique_metadata_paths(connection, video_root: Path | str) -> dict[str, Any]:
    """Repair metadata paths containing '?' only when the mapping is one-to-one.

    The physical files are never renamed or moved. Only the SQLite catalog path,
    filename and extension are corrected to the actual filesystem spelling.
    Ambiguous candidates are deliberately left untouched for diagnostics.
    """
    root = Path(video_root).expanduser()
    if not root.exists() or not root.is_dir():
        return {"checked": 0, "repaired": 0, "ambiguous": 0, "items": []}
    root = root.resolve()

    suspect_rows = connection.execute(
        """
        SELECT id, video_id, relative_path
        FROM video_files
        WHERE instr(relative_path, '?') > 0
        ORDER BY id
        """
    ).fetchall()
    if not suspect_rows:
        return {"checked": 0, "repaired": 0, "ambiguous": 0, "items": []}

    all_rows = connection.execute("SELECT id, relative_path FROM video_files ORDER BY id").fetchall()
    suspect_ids = {int(row["id"]) for row in suspect_rows}
    registered_exact = {
        normalize_relative_path(row["relative_path"]).casefold()
        for row in all_rows
        if int(row["id"]) not in suspect_ids
    }

    actual_paths = [
        relative
        for relative in _actual_video_paths(root)
        if relative.casefold() not in registered_exact
    ]

    matches_by_row: dict[int, list[str]] = {}
    rows_by_actual: dict[str, list[int]] = {}
    for row in suspect_rows:
        row_id = int(row["id"])
        expected_path = str(row["relative_path"])
        candidates = [
            actual_path
            for actual_path in actual_paths
            if relaxed_path_matches(expected_path, actual_path)
        ]
        matches_by_row[row_id] = candidates
        for actual_path in candidates:
            rows_by_actual.setdefault(actual_path.casefold(), []).append(row_id)

    repaired_items: list[dict[str, Any]] = []
    ambiguous = 0
    stamp = now_iso()
    for row in suspect_rows:
        row_id = int(row["id"])
        candidates = matches_by_row[row_id]
        if len(candidates) != 1:
            if len(candidates) > 1:
                ambiguous += 1
            continue
        actual_path = candidates[0]
        if len(rows_by_actual.get(actual_path.casefold(), [])) != 1:
            ambiguous += 1
            continue

        actual = PurePosixPath(actual_path)
        connection.execute(
            """
            UPDATE video_files
            SET filename=?, relative_path=?, extension=?, updated_at=?
            WHERE id=?
            """,
            (actual.name, actual_path, actual.suffix.lstrip(".").upper(), stamp, row_id),
        )
        repaired_items.append(
            {
                "videoFileId": row_id,
                "videoId": int(row["video_id"]),
                "from": str(row["relative_path"]),
                "to": actual_path,
            }
        )

    if repaired_items:
        connection.commit()

    return {
        "checked": len(suspect_rows),
        "repaired": len(repaired_items),
        "ambiguous": ambiguous,
        "items": repaired_items,
    }


def record_unsupported_subtitles(connection, video_root: Path | str, scan_run_id: int) -> int:
    """Record subtitle formats known to exist but not supported by the web player.

    The files are not inserted into the normal subtitles table and therefore do
    not change subtitles_found/matched/unmatched. They are diagnostics only.
    """
    root = Path(video_root).expanduser().resolve()
    count = 0
    stamp = now_iso()
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        dirnames[:] = [name for name in dirnames if not (directory_path / name).is_symlink()]
        for filename in filenames:
            path = directory_path / filename
            extension = path.suffix.casefold()
            if extension not in UNSUPPORTED_SUBTITLE_EXTENSIONS:
                continue
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(root)
                relative = normalize_relative_path(path.relative_to(root))
                stat = resolved.stat()
            except (OSError, ValueError):
                continue
            connection.execute(
                """
                INSERT INTO scan_discoveries(
                    scan_run_id, relative_path, extension,
                    file_size, modified_time_ns, status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'UNSUPPORTED_SUBTITLE', ?)
                """,
                (
                    scan_run_id,
                    relative,
                    extension.lstrip(".").upper(),
                    int(stat.st_size),
                    int(stat.st_mtime_ns),
                    stamp,
                ),
            )
            count += 1
    if count:
        connection.commit()
    return count


def scan_library(
    connection,
    video_root: Path | str,
    *,
    ffprobe_path: Path | str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    repair = repair_unique_metadata_paths(connection, video_root)
    if repair["checked"] and progress_callback is not None:
        try:
            progress_callback(
                {
                    "phase": "PREPARING",
                    "message": f"文字化けパスを確認中（修復 {repair['repaired']}件）",
                    "current": repair["checked"],
                    "total": repair["checked"],
                    "pathsRepaired": repair["repaired"],
                }
            )
        except Exception:
            pass

    result = _scan_library(
        connection,
        video_root,
        ffprobe_path=ffprobe_path,
        progress_callback=progress_callback,
    )
    result["pathsRepaired"] = int(repair["repaired"])
    result["pathRepairAmbiguous"] = int(repair["ambiguous"])
    result["unsupportedSubtitles"] = record_unsupported_subtitles(
        connection,
        video_root,
        int(result["runId"]),
    )
    return result
