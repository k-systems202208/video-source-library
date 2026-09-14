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
            "(w.official_title LIKE ? ESCAPE '\\' OR "
            "COALESCE(w.source_title, '') LIKE ? ESCAPE '\\' OR "
            "COALESCE(w.director_or_direction, '') LIKE ? ESCAPE '\\' OR "
            "COALESCE(w.main_cast_or_voice_actors, '') LIKE ? ESCAPE '\\')"
        )
        params.extend([pattern, pattern, pattern, pattern])
    if category and category.strip():
        clauses.append("w.category = ?")
        params.append(category.strip())
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), params


def _progress(watched: int, total: int, in_progress: int = 0) -> dict[str, Any]:
    return {
        "watched": watched,
        "total": total,
        "percent": int(round(watched * 100 / total)) if total else 0,
        "inProgress": bool(in_progress),
    }


def list_works(
    connection: sqlite3.Connection,
    *,
    user_id: int | None = None,
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
    total = int(connection.execute(f"SELECT COUNT(*) FROM works w{where_sql}", params).fetchone()[0])
    rows = connection.execute(
        f"""
        SELECT w.id,w.external_work_no,w.category,w.source_title,w.official_title,w.year_or_period,w.media_file_count,
          (SELECT COUNT(*) FROM videos v JOIN video_files vf ON vf.video_id=v.id WHERE v.work_id=w.id AND vf.is_available=1) available_count,
          COALESCE((SELECT favorite FROM user_work_state s WHERE s.user_id=? AND s.work_id=w.id),0) favorite,
          (SELECT COUNT(*) FROM videos v LEFT JOIN user_video_state s ON s.video_id=v.id AND s.user_id=? WHERE v.work_id=w.id AND v.content_type IN ('EPISODE','MOVIE') AND COALESCE(s.watched,0)=1) watched_count,
          (SELECT COUNT(*) FROM videos v WHERE v.work_id=w.id AND v.content_type IN ('EPISODE','MOVIE')) progress_total,
          (SELECT COUNT(*) FROM videos v JOIN user_video_state s ON s.video_id=v.id AND s.user_id=? WHERE v.work_id=w.id AND s.position_ms>0 AND s.watched=0) in_progress_count
        FROM works w {where_sql}
        ORDER BY {order_sql} LIMIT ? OFFSET ?
        """,
        [user_id, user_id, user_id, *params, limit_value, offset_value],
    ).fetchall()
    return {
        "total": total,
        "offset": offset_value,
        "limit": limit_value,
        "items": [
            {
                "id": int(r["id"]),
                "externalWorkNo": int(r["external_work_no"]),
                "category": r["category"],
                "sourceTitle": r["source_title"],
                "title": r["official_title"],
                "yearOrPeriod": r["year_or_period"],
                "videoCount": int(r["media_file_count"]),
                "availableVideoCount": int(r["available_count"]),
                "favorite": bool(r["favorite"]),
                "progress": _progress(int(r["watched_count"]), int(r["progress_total"]), int(r["in_progress_count"])),
            }
            for r in rows
        ],
    }


def get_work(connection: sqlite3.Connection, work_id: int, *, user_id: int | None = None) -> dict[str, Any] | None:
    r = connection.execute(
        """
        SELECT w.id,w.external_work_no,w.category,w.year_or_period,w.source_title,w.official_title,
               w.media_file_count,w.subtitle_file_count,w.media_format,w.director_or_direction,
               w.main_cast_or_voice_actors,w.verification_status,w.credits_verification_status,
               COALESCE(s.favorite,0) favorite
        FROM works w LEFT JOIN user_work_state s ON s.work_id=w.id AND s.user_id=? WHERE w.id=?
        """,
        (user_id, work_id),
    ).fetchone()
    if r is None:
        return None
    groups = connection.execute(
        """
        SELECT g.id,g.display_name,g.group_type,g.sort_order,COUNT(v.id) video_count,
               COALESCE(SUM(CASE WHEN f.is_available=1 THEN 1 ELSE 0 END),0) available_count,
               COALESCE(SUM(CASE WHEN s.watched=1 THEN 1 ELSE 0 END),0) watched_count
        FROM series_groups g
        LEFT JOIN videos v ON v.series_group_id=g.id
        LEFT JOIN video_files f ON f.video_id=v.id
        LEFT JOIN user_video_state s ON s.video_id=v.id AND s.user_id=?
        WHERE g.work_id=? GROUP BY g.id,g.display_name,g.group_type,g.sort_order ORDER BY g.sort_order,g.id
        """,
        (user_id, work_id),
    ).fetchall()
    p = connection.execute(
        """
        SELECT SUM(CASE WHEN COALESCE(s.watched,0)=1 THEN 1 ELSE 0 END) watched,
               COUNT(*) total,
               SUM(CASE WHEN COALESCE(s.position_ms,0)>0 AND COALESCE(s.watched,0)=0 THEN 1 ELSE 0 END) in_progress
        FROM videos v LEFT JOIN user_video_state s ON s.video_id=v.id AND s.user_id=?
        WHERE v.work_id=? AND v.content_type IN ('EPISODE','MOVIE')
        """,
        (user_id, work_id),
    ).fetchone()
    return {
        "id": int(r["id"]), "externalWorkNo": int(r["external_work_no"]), "category": r["category"],
        "sourceTitle": r["source_title"], "title": r["official_title"], "yearOrPeriod": r["year_or_period"],
        "videoCount": int(r["media_file_count"]), "subtitleFileCount": int(r["subtitle_file_count"]),
        "mediaFormat": r["media_format"], "director": r["director_or_direction"], "cast": r["main_cast_or_voice_actors"],
        "verificationStatus": r["verification_status"], "creditsVerificationStatus": r["credits_verification_status"],
        "favorite": bool(r["favorite"]),
        "progress": _progress(int(p["watched"] or 0), int(p["total"] or 0), int(p["in_progress"] or 0)),
        "groups": [
            {"id": int(g["id"]), "name": g["display_name"], "type": g["group_type"], "sortOrder": int(g["sort_order"]),
             "videoCount": int(g["video_count"]), "availableVideoCount": int(g["available_count"]), "watchedCount": int(g["watched_count"])}
            for g in groups
        ],
    }


def list_work_videos(connection: sqlite3.Connection, work_id: int, *, user_id: int | None = None, group_id: int | None = None) -> dict[str, Any] | None:
    work = connection.execute("SELECT id,official_title FROM works WHERE id=?", (work_id,)).fetchone()
    if work is None:
        return None
    params: list[Any] = [user_id, work_id]
    clause = ""
    selected = None
    if group_id is not None:
        g = connection.execute("SELECT id,display_name,group_type FROM series_groups WHERE id=? AND work_id=?", (group_id, work_id)).fetchone()
        if g is None:
            return None
        clause = " AND v.series_group_id=?"
        params.append(group_id)
        selected = {"id": int(g["id"]), "name": g["display_name"], "type": g["group_type"]}
    rows = connection.execute(
        f"""
        SELECT v.id,v.external_file_no,v.series_group_id,g.display_name group_name,g.group_type,v.episode_or_type,
               v.episode_number,v.episode_title,v.content_type,v.episode_sort_key,f.extension,f.duration_ms,
               f.playback_support,f.is_available,COALESCE(s.favorite,0) favorite,COALESCE(s.watched,0) watched,
               COALESCE(s.position_ms,0) position_ms,s.duration_ms state_duration_ms,COALESCE(s.play_count,0) play_count,s.last_played_at
        FROM videos v LEFT JOIN series_groups g ON g.id=v.series_group_id JOIN video_files f ON f.video_id=v.id
        LEFT JOIN user_video_state s ON s.video_id=v.id AND s.user_id=?
        WHERE v.work_id=?{clause} ORDER BY COALESCE(g.sort_order,0),v.episode_sort_key,v.id
        """,
        params,
    ).fetchall()
    return {"work": {"id": int(work["id"]), "title": work["official_title"]}, "group": selected, "items": [_video_summary(r) for r in rows]}


def _video_summary(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(r["id"]), "externalFileNo": int(r["external_file_no"]),
        "groupId": int(r["series_group_id"]) if r["series_group_id"] is not None else None,
        "groupName": r["group_name"], "groupType": r["group_type"], "episodeOrType": r["episode_or_type"],
        "episodeNumber": r["episode_number"], "episodeTitle": r["episode_title"], "contentType": r["content_type"],
        "file": {"extension": r["extension"], "durationMs": r["duration_ms"], "playbackSupport": r["playback_support"], "available": bool(r["is_available"])},
        "state": {"favorite": bool(r["favorite"]), "watched": bool(r["watched"]), "positionMs": int(r["position_ms"] or 0),
                  "durationMs": r["state_duration_ms"], "playCount": int(r["play_count"] or 0), "lastPlayedAt": r["last_played_at"]},
    }


def get_video(connection: sqlite3.Connection, video_id: int, *, user_id: int | None = None) -> dict[str, Any] | None:
    r = connection.execute(
        """
        SELECT v.id,v.external_file_no,v.work_id,w.official_title work_title,v.series_group_id,g.display_name group_name,
               g.group_type,v.episode_or_type,v.episode_number,v.episode_title,v.content_type,v.episode_sort_key,v.verification_status,
               f.extension,f.duration_ms,f.container_format,f.video_codec,f.audio_codec,f.width,f.height,f.playback_support,f.is_available,
               COALESCE(s.favorite,0) favorite,COALESCE(s.watched,0) watched,COALESCE(s.position_ms,0) position_ms,
               s.duration_ms state_duration_ms,COALESCE(s.play_count,0) play_count,s.last_played_at
        FROM videos v JOIN works w ON w.id=v.work_id LEFT JOIN series_groups g ON g.id=v.series_group_id
        JOIN video_files f ON f.video_id=v.id LEFT JOIN user_video_state s ON s.video_id=v.id AND s.user_id=? WHERE v.id=?
        """,
        (user_id, video_id),
    ).fetchone()
    if r is None:
        return None
    ids = [int(x["id"]) for x in connection.execute(
        "SELECT id FROM videos WHERE work_id=? AND ((series_group_id=?) OR (series_group_id IS NULL AND ? IS NULL)) ORDER BY episode_sort_key,id",
        (r["work_id"], r["series_group_id"], r["series_group_id"]),
    ).fetchall()]
    i = ids.index(video_id)
    return {
        "id": int(r["id"]), "externalFileNo": int(r["external_file_no"]), "work": {"id": int(r["work_id"]), "title": r["work_title"]},
        "group": {"id": int(r["series_group_id"]), "name": r["group_name"], "type": r["group_type"]} if r["series_group_id"] is not None else None,
        "episodeOrType": r["episode_or_type"], "episodeNumber": r["episode_number"], "episodeTitle": r["episode_title"],
        "contentType": r["content_type"], "verificationStatus": r["verification_status"],
        "file": {"extension": r["extension"], "durationMs": r["duration_ms"], "container": r["container_format"], "videoCodec": r["video_codec"],
                 "audioCodec": r["audio_codec"], "width": r["width"], "height": r["height"], "playbackSupport": r["playback_support"], "available": bool(r["is_available"])},
        "state": {"favorite": bool(r["favorite"]), "watched": bool(r["watched"]), "positionMs": int(r["position_ms"] or 0),
                  "durationMs": r["state_duration_ms"], "playCount": int(r["play_count"] or 0), "lastPlayedAt": r["last_played_at"]},
        "navigation": {"previousVideoId": ids[i-1] if i > 0 else None, "nextVideoId": ids[i+1] if i + 1 < len(ids) else None},
    }


def library_stats(connection: sqlite3.Connection) -> dict[str, Any]:
    t = connection.execute("SELECT (SELECT COUNT(*) FROM works) works,(SELECT COUNT(*) FROM videos) videos,(SELECT COUNT(*) FROM video_files WHERE is_available=1) available_videos").fetchone()
    cats = connection.execute("SELECT category,COUNT(*) work_count,COALESCE(SUM(media_file_count),0) video_count FROM works GROUP BY category ORDER BY category").fetchall()
    return {"works": int(t["works"]), "videos": int(t["videos"]), "availableVideos": int(t["available_videos"]),
            "categories": [{"name": r["category"], "workCount": int(r["work_count"]), "videoCount": int(r["video_count"])} for r in cats]}
