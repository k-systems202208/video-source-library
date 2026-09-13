from __future__ import annotations

import sqlite3
from typing import Any

DEFAULT_LIMIT = 60
MAX_LIMIT = 200


def _bounded_limit(value: int | str | None) -> int:
    try:
        parsed = int(value if value is not None else DEFAULT_LIMIT)
    except (TypeError, ValueError):
        parsed = DEFAULT_LIMIT
    return max(1, min(parsed, MAX_LIMIT))


def _bounded_offset(value: int | str | None) -> int:
    try:
        parsed = int(value if value is not None else 0)
    except (TypeError, ValueError):
        parsed = 0
    return max(0, parsed)


def _like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _work_filters(q: str | None, category: str | None) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if q and q.strip():
        pattern = _like_pattern(q.strip())
        clauses.append(
            "(" 
            "w.official_title LIKE ? ESCAPE '\\' OR "
            "COALESCE(w.source_title, '') LIKE ? ESCAPE '\\' OR "
            "COALESCE(w.director_or_direction, '') LIKE ? ESCAPE '\\' OR "
            "COALESCE(w.main_cast_or_voice_actors, '') LIKE ? ESCAPE '\\'"
            ")"
        )
        params.extend([pattern, pattern, pattern, pattern])
    if category and category.strip():
        clauses.append("w.category = ?")
        params.append(category.strip())
    if not clauses:
        return "", params
    return " WHERE " + " AND ".join(clauses), params


def list_works(
    connection: sqlite3.Connection,
    *,
    q: str | None = None,
    category: str | None = None,
    sort: str | None = "title",
    limit: int | str | None = DEFAULT_LIMIT,
    offset: int | str | None = 0,
) -> dict[str, Any]:
    limit_value = _bounded_limit(limit)
    offset_value = _bounded_offset(offset)
    where_sql, params = _work_filters(q, category)

    order_sql = {
        "title": "w.official_title COLLATE NOCASE, w.external_work_no",
        "year": "COALESCE(w.year_or_period, ''), w.official_title COLLATE NOCASE",
        "added": "w.external_work_no DESC",
    }.get(str(sort or "title"), "w.official_title COLLATE NOCASE, w.external_work_no")

    total_row = connection.execute(
        f"SELECT COUNT(*) AS count FROM works w{where_sql}", params
    ).fetchone()
    total = int(total_row["count"] if total_row else 0)

    rows = connection.execute(
        f"""
        SELECT
            w.id,
            w.external_work_no,
            w.category,
            w.source_title,
            w.official_title,
            w.year_or_period,
            w.media_file_count,
            (
                SELECT COUNT(*)
                FROM videos v
                JOIN video_files vf ON vf.video_id = v.id
                WHERE v.work_id = w.id AND vf.is_available = 1
            ) AS available_video_count
        FROM works w
        {where_sql}
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?
        """,
        [*params, limit_value, offset_value],
    ).fetchall()

    return {
        "total": total,
        "offset": offset_value,
        "limit": limit_value,
        "items": [
            {
                "id": int(row["id"]),
                "externalWorkNo": int(row["external_work_no"]),
                "category": row["category"],
                "sourceTitle": row["source_title"],
                "title": row["official_title"],
                "yearOrPeriod": row["year_or_period"],
                "videoCount": int(row["media_file_count"]),
                "availableVideoCount": int(row["available_video_count"]),
            }
            for row in rows
        ],
    }


def get_work(connection: sqlite3.Connection, work_id: int) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT
            id, external_work_no, category, year_or_period, source_title, official_title,
            media_file_count, subtitle_file_count, media_format,
            director_or_direction, main_cast_or_voice_actors,
            verification_status, credits_verification_status
        FROM works
        WHERE id = ?
        """,
        (work_id,),
    ).fetchone()
    if row is None:
        return None

    group_rows = connection.execute(
        """
        SELECT
            sg.id,
            sg.display_name,
            sg.group_type,
            sg.sort_order,
            COUNT(v.id) AS video_count,
            COALESCE(SUM(CASE WHEN vf.is_available = 1 THEN 1 ELSE 0 END), 0) AS available_video_count
        FROM series_groups sg
        LEFT JOIN videos v ON v.series_group_id = sg.id
        LEFT JOIN video_files vf ON vf.video_id = v.id
        WHERE sg.work_id = ?
        GROUP BY sg.id, sg.display_name, sg.group_type, sg.sort_order
        ORDER BY sg.sort_order, sg.id
        """,
        (work_id,),
    ).fetchall()

    return {
        "id": int(row["id"]),
        "externalWorkNo": int(row["external_work_no"]),
        "category": row["category"],
        "sourceTitle": row["source_title"],
        "title": row["official_title"],
        "yearOrPeriod": row["year_or_period"],
        "videoCount": int(row["media_file_count"]),
        "subtitleFileCount": int(row["subtitle_file_count"]),
        "mediaFormat": row["media_format"],
        "director": row["director_or_direction"],
        "cast": row["main_cast_or_voice_actors"],
        "verificationStatus": row["verification_status"],
        "creditsVerificationStatus": row["credits_verification_status"],
        "groups": [
            {
                "id": int(group["id"]),
                "name": group["display_name"],
                "type": group["group_type"],
                "sortOrder": int(group["sort_order"]),
                "videoCount": int(group["video_count"]),
                "availableVideoCount": int(group["available_video_count"]),
            }
            for group in group_rows
        ],
    }


def list_work_videos(
    connection: sqlite3.Connection,
    work_id: int,
    *,
    group_id: int | None = None,
) -> dict[str, Any] | None:
    work_row = connection.execute(
        "SELECT id, official_title FROM works WHERE id = ?", (work_id,)
    ).fetchone()
    if work_row is None:
        return None

    params: list[Any] = [work_id]
    group_clause = ""
    selected_group: dict[str, Any] | None = None
    if group_id is not None:
        group_row = connection.execute(
            """
            SELECT id, display_name, group_type
            FROM series_groups
            WHERE id = ? AND work_id = ?
            """,
            (group_id, work_id),
        ).fetchone()
        if group_row is None:
            return None
        group_clause = " AND v.series_group_id = ?"
        params.append(group_id)
        selected_group = {
            "id": int(group_row["id"]),
            "name": group_row["display_name"],
            "type": group_row["group_type"],
        }

    rows = connection.execute(
        f"""
        SELECT
            v.id,
            v.external_file_no,
            v.series_group_id,
            sg.display_name AS group_name,
            sg.group_type,
            v.episode_or_type,
            v.episode_number,
            v.episode_title,
            v.content_type,
            v.episode_sort_key,
            vf.extension,
            vf.duration_ms,
            vf.playback_support,
            vf.is_available
        FROM videos v
        LEFT JOIN series_groups sg ON sg.id = v.series_group_id
        JOIN video_files vf ON vf.video_id = v.id
        WHERE v.work_id = ?{group_clause}
        ORDER BY COALESCE(sg.sort_order, 0), v.episode_sort_key, v.id
        """,
        params,
    ).fetchall()

    return {
        "work": {"id": int(work_row["id"]), "title": work_row["official_title"]},
        "group": selected_group,
        "items": [_video_summary(row) for row in rows],
    }


def _video_summary(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "externalFileNo": int(row["external_file_no"]),
        "groupId": int(row["series_group_id"]) if row["series_group_id"] is not None else None,
        "groupName": row["group_name"],
        "groupType": row["group_type"],
        "episodeOrType": row["episode_or_type"],
        "episodeNumber": row["episode_number"],
        "episodeTitle": row["episode_title"],
        "contentType": row["content_type"],
        "file": {
            "extension": row["extension"],
            "durationMs": row["duration_ms"],
            "playbackSupport": row["playback_support"],
            "available": bool(row["is_available"]),
        },
    }


def get_video(connection: sqlite3.Connection, video_id: int) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT
            v.id,
            v.external_file_no,
            v.work_id,
            w.official_title AS work_title,
            v.series_group_id,
            sg.display_name AS group_name,
            sg.group_type,
            v.episode_or_type,
            v.episode_number,
            v.episode_title,
            v.content_type,
            v.episode_sort_key,
            v.verification_status,
            vf.extension,
            vf.duration_ms,
            vf.container_format,
            vf.video_codec,
            vf.audio_codec,
            vf.width,
            vf.height,
            vf.playback_support,
            vf.is_available
        FROM videos v
        JOIN works w ON w.id = v.work_id
        LEFT JOIN series_groups sg ON sg.id = v.series_group_id
        JOIN video_files vf ON vf.video_id = v.id
        WHERE v.id = ?
        """,
        (video_id,),
    ).fetchone()
    if row is None:
        return None

    ordered_ids = [
        int(item["id"])
        for item in connection.execute(
            """
            SELECT id
            FROM videos
            WHERE work_id = ? AND (
                (series_group_id = ?) OR (series_group_id IS NULL AND ? IS NULL)
            )
            ORDER BY episode_sort_key, id
            """,
            (row["work_id"], row["series_group_id"], row["series_group_id"]),
        ).fetchall()
    ]
    index = ordered_ids.index(video_id)
    previous_id = ordered_ids[index - 1] if index > 0 else None
    next_id = ordered_ids[index + 1] if index + 1 < len(ordered_ids) else None

    return {
        "id": int(row["id"]),
        "externalFileNo": int(row["external_file_no"]),
        "work": {"id": int(row["work_id"]), "title": row["work_title"]},
        "group": (
            {
                "id": int(row["series_group_id"]),
                "name": row["group_name"],
                "type": row["group_type"],
            }
            if row["series_group_id"] is not None
            else None
        ),
        "episodeOrType": row["episode_or_type"],
        "episodeNumber": row["episode_number"],
        "episodeTitle": row["episode_title"],
        "contentType": row["content_type"],
        "verificationStatus": row["verification_status"],
        "file": {
            "extension": row["extension"],
            "durationMs": row["duration_ms"],
            "container": row["container_format"],
            "videoCodec": row["video_codec"],
            "audioCodec": row["audio_codec"],
            "width": row["width"],
            "height": row["height"],
            "playbackSupport": row["playback_support"],
            "available": bool(row["is_available"]),
        },
        "navigation": {"previousVideoId": previous_id, "nextVideoId": next_id},
    }


def library_stats(connection: sqlite3.Connection) -> dict[str, Any]:
    totals = connection.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM works) AS works,
            (SELECT COUNT(*) FROM videos) AS videos,
            (SELECT COUNT(*) FROM video_files WHERE is_available = 1) AS available_videos
        """
    ).fetchone()
    categories = connection.execute(
        """
        SELECT category, COUNT(*) AS work_count, COALESCE(SUM(media_file_count), 0) AS video_count
        FROM works
        GROUP BY category
        ORDER BY category
        """
    ).fetchall()
    return {
        "works": int(totals["works"]),
        "videos": int(totals["videos"]),
        "availableVideos": int(totals["available_videos"]),
        "categories": [
            {
                "name": row["category"],
                "workCount": int(row["work_count"]),
                "videoCount": int(row["video_count"]),
            }
            for row in categories
        ],
    }
