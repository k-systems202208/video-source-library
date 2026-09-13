from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from database import connect, initialize_database, now_iso, quick_check, foreign_key_error_count

SUPPORTED_METADATA_SCHEMA = "1.0"


class MetadataValidationError(ValueError):
    pass


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_episode_number(value: Any) -> float | None:
    text = _as_text(value)
    if not text:
        return None
    patterns = (
        r"第\s*([0-9]+(?:\.[0-9]+)?)\s*話",
        r"第\s*([0-9]+(?:\.[0-9]+)?)\s*回",
        r"#\s*([0-9]+(?:\.[0-9]+)?)",
        r"Episode\s*([0-9]+(?:\.[0-9]+)?)",
        r"EP\s*([0-9]+(?:\.[0-9]+)?)",
        r"KARTE[:：]\s*([0-9]+(?:\.[0-9]+)?)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def _content_type(episode_or_type: Any, episode_title: Any, series_name: Any) -> str:
    text = " ".join(filter(None, map(_as_text, (episode_or_type, episode_title, series_name)))).casefold()
    if "fan" in text or "ファン" in text:
        return "FAN_EDIT"
    if "trailer" in text or "予告" in text:
        return "TRAILER"
    if "making" in text or "メイキング" in text:
        return "MAKING"
    if "interview" in text or "インタビュー" in text:
        return "INTERVIEW"
    if "総集編" in text or "recap" in text:
        return "RECAP"
    if "コメディスペシャル" in text:
        return "COMEDY_SPECIAL"
    if "oad" in text:
        return "OAD"
    if "ova" in text:
        return "OVA"
    if "劇場版" in text or re.search(r"(^|\s)映画($|\s)", text):
        return "MOVIE"
    if "特典" in text or "bonus" in text or "extra" in text:
        return "EXTRA"
    if "スペシャル" in text or "special" in text or "特別編" in text:
        return "SPECIAL"
    if _parse_episode_number(episode_or_type) is not None:
        return "EPISODE"
    if any(token in text for token in ("最終話", "最終回", "last karte")):
        return "EPISODE"
    return "UNKNOWN"


def _group_type(display_name: str, content_types: set[str]) -> str:
    text = display_name.casefold()
    if "oad" in text:
        return "OAD"
    if "ova" in text:
        return "OVA"
    if "劇場版" in text or "movie" in text:
        return "MOVIE"
    if "特典" in text or "extra" in text or "bonus" in text:
        return "EXTRA"
    if "スペシャル" in text or "special" in text:
        return "SPECIAL"
    if content_types and content_types <= {"MOVIE"}:
        return "MOVIE"
    if content_types and content_types <= {"OVA"}:
        return "OVA"
    if content_types and content_types <= {"OAD"}:
        return "OAD"
    return "SERIES"


def validate_metadata(payload: dict[str, Any]) -> None:
    if str(payload.get("schema_version")) != SUPPORTED_METADATA_SCHEMA:
        raise MetadataValidationError(
            f"Unsupported metadata schema: {payload.get('schema_version')!r}"
        )
    works = payload.get("works")
    if not isinstance(works, list):
        raise MetadataValidationError("works must be an array")

    work_nos: list[int] = []
    file_nos: list[int] = []
    relative_paths: set[str] = set()
    for work in works:
        if not isinstance(work, dict):
            raise MetadataValidationError("work entry must be an object")
        work_no = work.get("work_no")
        if not isinstance(work_no, int):
            raise MetadataValidationError("work_no must be an integer")
        if not _as_text(work.get("official_japanese_title")):
            raise MetadataValidationError(f"work {work_no}: official title is required")
        work_nos.append(work_no)

        files = work.get("files")
        if not isinstance(files, list):
            raise MetadataValidationError(f"work {work_no}: files must be an array")
        expected = int(work.get("media_file_count") or 0)
        if expected != len(files):
            raise MetadataValidationError(
                f"work {work_no}: media_file_count={expected}, files={len(files)}"
            )
        for file_entry in files:
            file_no = file_entry.get("file_no")
            if not isinstance(file_no, int):
                raise MetadataValidationError(f"work {work_no}: file_no must be an integer")
            relative_path = _as_text(file_entry.get("relative_path"))
            if not relative_path:
                raise MetadataValidationError(f"file {file_no}: relative_path is required")
            if relative_path in relative_paths:
                raise MetadataValidationError(f"duplicate relative_path: {relative_path}")
            relative_paths.add(relative_path)
            file_nos.append(file_no)

    if len(work_nos) != len(set(work_nos)):
        raise MetadataValidationError("duplicate work_no")
    if len(file_nos) != len(set(file_nos)):
        raise MetadataValidationError("duplicate file_no")

    summary = payload.get("summary") or {}
    expected_works = summary.get("work_count")
    expected_files = summary.get("media_file_count")
    if expected_works is not None and int(expected_works) != len(work_nos):
        raise MetadataValidationError("summary.work_count mismatch")
    if expected_files is not None and int(expected_files) != len(file_nos):
        raise MetadataValidationError("summary.media_file_count mismatch")


def load_metadata(path: Path | str) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    validate_metadata(payload)
    return payload


def _upsert_work(connection: sqlite3.Connection, work: dict[str, Any], stamp: str) -> int:
    verification = work.get("work_verification") or {}
    credits = work.get("credits") or {}
    connection.execute(
        """
        INSERT INTO works (
            external_work_no, category, year_or_period, source_title, official_title,
            media_file_count, subtitle_file_count, subfolder_count, media_format,
            source_folder, relative_path, director_or_direction, main_cast_or_voice_actors,
            verification_method, verification_note, verification_url, verification_status,
            credits_verification_note, credits_verification_url, credits_verification_status,
            created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(external_work_no) DO UPDATE SET
            category=excluded.category,
            year_or_period=excluded.year_or_period,
            source_title=excluded.source_title,
            official_title=excluded.official_title,
            media_file_count=excluded.media_file_count,
            subtitle_file_count=excluded.subtitle_file_count,
            subfolder_count=excluded.subfolder_count,
            media_format=excluded.media_format,
            source_folder=excluded.source_folder,
            relative_path=excluded.relative_path,
            director_or_direction=excluded.director_or_direction,
            main_cast_or_voice_actors=excluded.main_cast_or_voice_actors,
            verification_method=excluded.verification_method,
            verification_note=excluded.verification_note,
            verification_url=excluded.verification_url,
            verification_status=excluded.verification_status,
            credits_verification_note=excluded.credits_verification_note,
            credits_verification_url=excluded.credits_verification_url,
            credits_verification_status=excluded.credits_verification_status,
            updated_at=excluded.updated_at
        """,
        (
            work["work_no"],
            _as_text(work.get("category")) or "未分類",
            _as_text(work.get("year_or_period")),
            _as_text(work.get("source_title")),
            _as_text(work.get("official_japanese_title")) or "(untitled)",
            int(work.get("media_file_count") or 0),
            int(work.get("subtitle_file_count") or 0),
            int(work.get("subfolder_count") or 0),
            _as_text(work.get("media_format")),
            _as_text(work.get("source_folder")),
            _as_text(work.get("relative_path")),
            _as_text(credits.get("director_or_direction")),
            _as_text(credits.get("main_cast_or_voice_actors")),
            _as_text(verification.get("method")),
            _as_text(verification.get("note")),
            _as_text(verification.get("url")),
            "確認済" if verification.get("url") else None,
            _as_text(credits.get("verification_note")),
            _as_text(credits.get("verification_url")),
            _as_text(credits.get("verification_status")),
            stamp,
            stamp,
        ),
    )
    row = connection.execute(
        "SELECT id FROM works WHERE external_work_no = ?", (work["work_no"],)
    ).fetchone()
    return int(row["id"])


def _upsert_group(
    connection: sqlite3.Connection,
    work_id: int,
    display_name: str,
    group_type: str,
    sort_order: int,
    stamp: str,
) -> int:
    connection.execute(
        """
        INSERT INTO series_groups (
            work_id, display_name, group_type, sort_order, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(work_id, display_name) DO UPDATE SET
            group_type=excluded.group_type,
            sort_order=excluded.sort_order,
            updated_at=excluded.updated_at
        """,
        (work_id, display_name, group_type, sort_order, stamp, stamp),
    )
    row = connection.execute(
        "SELECT id FROM series_groups WHERE work_id = ? AND display_name = ?",
        (work_id, display_name),
    ).fetchone()
    return int(row["id"])


def import_metadata(connection: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, int]:
    validate_metadata(payload)
    initialize_database(connection)
    stamp = now_iso()

    source = payload.get("source") or {}
    summary = payload.get("summary") or {}
    imported_works = 0
    imported_videos = 0
    imported_groups = 0

    connection.execute("BEGIN IMMEDIATE")
    try:
        for work in payload["works"]:
            work_id = _upsert_work(connection, work, stamp)
            imported_works += 1

            files = work["files"]
            group_order: list[str] = []
            content_types_by_group: dict[str, set[str]] = {}
            for entry in files:
                group_name = _as_text(entry.get("series_or_season")) or _as_text(work.get("official_japanese_title")) or "その他"
                if group_name not in content_types_by_group:
                    group_order.append(group_name)
                    content_types_by_group[group_name] = set()
                content_types_by_group[group_name].add(
                    _content_type(entry.get("episode_or_type"), entry.get("episode_title"), group_name)
                )

            group_ids: dict[str, int] = {}
            for index, group_name in enumerate(group_order, start=1):
                group_ids[group_name] = _upsert_group(
                    connection,
                    work_id,
                    group_name,
                    _group_type(group_name, content_types_by_group[group_name]),
                    index,
                    stamp,
                )
                imported_groups += 1

            per_group_order: dict[str, int] = {}
            for entry in files:
                group_name = _as_text(entry.get("series_or_season")) or _as_text(work.get("official_japanese_title")) or "その他"
                per_group_order[group_name] = per_group_order.get(group_name, 0) + 1
                group_position = per_group_order[group_name]
                episode_no = _parse_episode_number(entry.get("episode_or_type"))
                if episode_no is None:
                    sort_key = f"{group_position:06d}"
                else:
                    sort_key = f"{episode_no:012.3f}-{group_position:06d}"
                verification = entry.get("verification") or {}
                content_type = _content_type(
                    entry.get("episode_or_type"), entry.get("episode_title"), group_name
                )

                connection.execute(
                    """
                    INSERT INTO videos (
                        work_id, series_group_id, external_file_no, official_title,
                        episode_or_type, episode_number, episode_sort_key, episode_title,
                        content_type, verification_url, verification_status, verification_note,
                        created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(external_file_no) DO UPDATE SET
                        work_id=excluded.work_id,
                        series_group_id=excluded.series_group_id,
                        official_title=excluded.official_title,
                        episode_or_type=excluded.episode_or_type,
                        episode_number=excluded.episode_number,
                        episode_sort_key=excluded.episode_sort_key,
                        episode_title=excluded.episode_title,
                        content_type=excluded.content_type,
                        verification_url=excluded.verification_url,
                        verification_status=excluded.verification_status,
                        verification_note=excluded.verification_note,
                        updated_at=excluded.updated_at
                    """,
                    (
                        work_id,
                        group_ids[group_name],
                        entry["file_no"],
                        _as_text(entry.get("official_japanese_title")),
                        _as_text(entry.get("episode_or_type")),
                        episode_no,
                        sort_key,
                        _as_text(entry.get("episode_title")),
                        content_type,
                        _as_text(verification.get("url")),
                        _as_text(verification.get("status")),
                        _as_text(verification.get("note")),
                        stamp,
                        stamp,
                    ),
                )
                video_row = connection.execute(
                    "SELECT id FROM videos WHERE external_file_no = ?", (entry["file_no"],)
                ).fetchone()
                video_id = int(video_row["id"])
                connection.execute(
                    """
                    INSERT INTO video_files (
                        video_id, source_subfolder, filename, relative_path, extension,
                        playback_support, is_available, scan_status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'UNKNOWN', 0, 'NOT_SCANNED', ?, ?)
                    ON CONFLICT(video_id) DO UPDATE SET
                        source_subfolder=excluded.source_subfolder,
                        filename=excluded.filename,
                        relative_path=excluded.relative_path,
                        extension=excluded.extension,
                        updated_at=excluded.updated_at
                    """,
                    (
                        video_id,
                        _as_text(entry.get("subfolder")),
                        _as_text(entry.get("filename")) or "(unknown)",
                        _as_text(entry.get("relative_path")) or "",
                        _as_text(entry.get("extension")) or "UNKNOWN",
                        stamp,
                        stamp,
                    ),
                )
                imported_videos += 1

        connection.execute(
            """
            INSERT INTO metadata_imports (
                schema_version, source_file, source_version, generated_at,
                work_count, media_file_count, imported_at, status, message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'SUCCESS', ?)
            """,
            (
                str(payload.get("schema_version")),
                _as_text(source.get("file")),
                _as_text(source.get("source_version")),
                _as_text(payload.get("generated_at")),
                int(summary.get("work_count") or imported_works),
                int(summary.get("media_file_count") or imported_videos),
                stamp,
                f"Imported {imported_works} works / {imported_videos} videos",
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise

    if quick_check(connection).casefold() != "ok":
        raise RuntimeError("SQLite quick_check failed after metadata import")
    if foreign_key_error_count(connection) != 0:
        raise RuntimeError("Foreign key errors found after metadata import")

    return {
        "works": imported_works,
        "groups": imported_groups,
        "videos": imported_videos,
    }


def import_file(metadata_path: Path | str, database_path: Path | str) -> dict[str, int]:
    payload = load_metadata(metadata_path)
    with connect(database_path) as connection:
        return import_metadata(connection, payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import video_library.json into SQLite schema 1")
    parser.add_argument("metadata", type=Path)
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    result = import_file(args.metadata, args.database)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
