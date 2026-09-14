from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_local_owner(connection: sqlite3.Connection) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT u.id, u.display_name, u.is_owner, u.is_active
        FROM user_identities ui
        JOIN users u ON u.id = ui.user_id
        WHERE ui.provider = 'local_owner' AND ui.subject = 'local'
        LIMIT 1
        """
    ).fetchone()
    stamp = now_iso()
    if row is None:
        owner = connection.execute(
            "SELECT id, display_name, is_owner, is_active FROM users WHERE is_owner = 1 LIMIT 1"
        ).fetchone()
        if owner is None:
            connection.execute(
                """
                INSERT INTO users(display_name, is_owner, is_active, created_at, updated_at, last_seen_at)
                VALUES ('Owner', 1, 1, ?, ?, ?)
                """,
                (stamp, stamp, stamp),
            )
            user_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        else:
            user_id = int(owner["id"])
        connection.execute(
            """
            INSERT OR IGNORE INTO user_identities(
                user_id, provider, subject, created_at, updated_at
            ) VALUES (?, 'local_owner', 'local', ?, ?)
            """,
            (user_id, stamp, stamp),
        )
        connection.commit()
        row = connection.execute(
            "SELECT id, display_name, is_owner, is_active FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    connection.execute(
        "UPDATE users SET last_seen_at = ?, updated_at = ? WHERE id = ?",
        (stamp, stamp, int(row["id"])),
    )
    connection.commit()
    return {
        "id": int(row["id"]),
        "displayName": row["display_name"],
        "isOwner": bool(row["is_owner"]),
        "isActive": bool(row["is_active"]),
    }


def current_user(connection: sqlite3.Connection, user_id: int) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT id, display_name, is_owner, is_active, last_seen_at FROM users WHERE id = ? AND is_active = 1",
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "displayName": row["display_name"],
        "isOwner": bool(row["is_owner"]),
        "isActive": bool(row["is_active"]),
        "lastSeenAt": row["last_seen_at"],
    }


def _require_work(connection: sqlite3.Connection, work_id: int) -> None:
    if connection.execute("SELECT 1 FROM works WHERE id = ?", (work_id,)).fetchone() is None:
        raise LookupError("WORK_NOT_FOUND")


def _require_video(connection: sqlite3.Connection, video_id: int) -> None:
    if connection.execute("SELECT 1 FROM videos WHERE id = ?", (video_id,)).fetchone() is None:
        raise LookupError("VIDEO_NOT_FOUND")


def set_work_favorite(connection: sqlite3.Connection, user_id: int, work_id: int, favorite: bool) -> dict[str, Any]:
    _require_work(connection, work_id)
    stamp = now_iso()
    connection.execute(
        """
        INSERT INTO user_work_state(user_id, work_id, favorite, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, work_id) DO UPDATE SET
            favorite = excluded.favorite,
            updated_at = excluded.updated_at
        """,
        (user_id, work_id, int(favorite), stamp, stamp),
    )
    connection.commit()
    return {"workId": work_id, "favorite": bool(favorite)}


def favorite_works(connection: sqlite3.Connection, user_id: int, *, limit: int = 100) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT w.id, w.external_work_no, w.category, w.official_title, w.year_or_period
        FROM user_work_state uws
        JOIN works w ON w.id = uws.work_id
        WHERE uws.user_id = ? AND uws.favorite = 1
        ORDER BY w.official_title COLLATE NOCASE
        LIMIT ?
        """,
        (user_id, max(1, min(int(limit), 200))),
    ).fetchall()
    return {"items": [{"id": int(row["id"]), "externalWorkNo": int(row["external_work_no"]), "category": row["category"], "title": row["official_title"], "yearOrPeriod": row["year_or_period"]} for row in rows]}


def set_video_favorite(connection: sqlite3.Connection, user_id: int, video_id: int, favorite: bool) -> dict[str, Any]:
    _require_video(connection, video_id)
    stamp = now_iso()
    connection.execute(
        """
        INSERT INTO user_video_state(
            user_id, video_id, favorite, watched, play_count, position_ms,
            created_at, updated_at
        ) VALUES (?, ?, ?, 0, 0, 0, ?, ?)
        ON CONFLICT(user_id, video_id) DO UPDATE SET
            favorite = excluded.favorite,
            updated_at = excluded.updated_at
        """,
        (user_id, video_id, int(favorite), stamp, stamp),
    )
    connection.commit()
    return {"videoId": video_id, "favorite": bool(favorite)}


def favorite_videos(connection: sqlite3.Connection, user_id: int, *, limit: int = 100) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT v.id, v.external_file_no, v.episode_or_type, v.episode_title,
               w.id AS work_id, w.official_title AS work_title,
               sg.display_name AS group_name
        FROM user_video_state uvs
        JOIN videos v ON v.id = uvs.video_id
        JOIN works w ON w.id = v.work_id
        LEFT JOIN series_groups sg ON sg.id = v.series_group_id
        WHERE uvs.user_id = ? AND uvs.favorite = 1
        ORDER BY w.official_title COLLATE NOCASE, v.episode_sort_key, v.id
        LIMIT ?
        """,
        (user_id, max(1, min(int(limit), 200))),
    ).fetchall()
    return {"items": [{"id": int(row["id"]), "externalFileNo": int(row["external_file_no"]), "workId": int(row["work_id"]), "workTitle": row["work_title"], "groupName": row["group_name"], "episodeOrType": row["episode_or_type"], "episodeTitle": row["episode_title"]} for row in rows]}


def set_watched(connection: sqlite3.Connection, user_id: int, video_id: int, watched: bool) -> dict[str, Any]:
    _require_video(connection, video_id)
    stamp = now_iso()
    connection.execute(
        """
        INSERT INTO user_video_state(
            user_id, video_id, favorite, watched, watched_override,
            play_count, position_ms, completed_at, created_at, updated_at
        ) VALUES (?, ?, 0, ?, ?, 0, 0, ?, ?, ?)
        ON CONFLICT(user_id, video_id) DO UPDATE SET
            watched = excluded.watched,
            watched_override = excluded.watched_override,
            completed_at = excluded.completed_at,
            updated_at = excluded.updated_at
        """,
        (user_id, video_id, int(watched), int(watched), stamp if watched else None, stamp, stamp),
    )
    connection.commit()
    return {"videoId": video_id, "watched": bool(watched)}


def start_playback(connection: sqlite3.Connection, user_id: int, video_id: int) -> dict[str, Any]:
    _require_video(connection, video_id)
    stamp = now_iso()
    existing = connection.execute(
        """
        SELECT position_ms, duration_ms, watched, watched_override, play_count
        FROM user_video_state WHERE user_id = ? AND video_id = ?
        """,
        (user_id, video_id),
    ).fetchone()
    if existing is None:
        connection.execute(
            """
            INSERT INTO user_video_state(
                user_id, video_id, favorite, watched, watched_override,
                play_count, position_ms, last_played_at, created_at, updated_at
            ) VALUES (?, ?, 0, 0, NULL, 0, 0, ?, ?, ?)
            """,
            (user_id, video_id, stamp, stamp, stamp),
        )
        state = {"positionMs": 0, "durationMs": None, "watched": False, "playCount": 0}
    else:
        if existing["watched_override"] == 0:
            connection.execute("UPDATE user_video_state SET watched_override = NULL WHERE user_id = ? AND video_id = ?", (user_id, video_id))
        connection.execute("UPDATE user_video_state SET last_played_at = ?, updated_at = ? WHERE user_id = ? AND video_id = ?", (stamp, stamp, user_id, video_id))
        state = {"positionMs": int(existing["position_ms"] or 0), "durationMs": existing["duration_ms"], "watched": bool(existing["watched"]), "playCount": int(existing["play_count"] or 0)}
    connection.commit()
    return state


def _auto_watched(position_ms: int, duration_ms: int | None, event: str) -> bool:
    if event == "ended":
        return True
    if not duration_ms or duration_ms <= 0:
        return False
    return position_ms >= int(duration_ms * 0.90)


def _play_count_threshold(duration_ms: int | None) -> int:
    if not duration_ms or duration_ms <= 0:
        return 30_000
    return int(max(5_000, min(30_000, duration_ms * 0.05)))


def record_progress(connection: sqlite3.Connection, user_id: int, video_id: int, *, position_ms: int, duration_ms: int | None, event: str, increment_play_count: bool = False) -> dict[str, Any]:
    _require_video(connection, video_id)
    if position_ms < 0:
        raise ValueError("positionMs must be >= 0")
    if duration_ms is not None and duration_ms < 0:
        raise ValueError("durationMs must be >= 0")
    if duration_ms and position_ms > duration_ms:
        position_ms = duration_ms
    stamp = now_iso()
    row = connection.execute("SELECT favorite, watched, watched_override, play_count FROM user_video_state WHERE user_id = ? AND video_id = ?", (user_id, video_id)).fetchone()
    favorite = int(row["favorite"]) if row else 0
    watched = int(row["watched"]) if row else 0
    watched_override = row["watched_override"] if row else None
    play_count = int(row["play_count"]) if row else 0
    if watched_override is None and _auto_watched(position_ms, duration_ms, event):
        watched = 1
    completed_at = stamp if watched else None
    if increment_play_count:
        play_count += 1
    connection.execute(
        """
        INSERT INTO user_video_state(
            user_id, video_id, favorite, watched, watched_override, play_count,
            position_ms, duration_ms, last_played_at, completed_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, video_id) DO UPDATE SET
            favorite = excluded.favorite,
            watched = excluded.watched,
            watched_override = excluded.watched_override,
            play_count = excluded.play_count,
            position_ms = excluded.position_ms,
            duration_ms = excluded.duration_ms,
            last_played_at = excluded.last_played_at,
            completed_at = excluded.completed_at,
            updated_at = excluded.updated_at
        """,
        (user_id, video_id, favorite, watched, watched_override, play_count, position_ms, duration_ms, stamp, completed_at, stamp, stamp),
    )
    connection.commit()
    return {"videoId": video_id, "positionMs": position_ms, "durationMs": duration_ms, "watched": bool(watched), "playCount": play_count}


@dataclass
class _PlaybackSession:
    user_id: int
    video_id: int
    counted: bool = False


class PlaybackSessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, _PlaybackSession] = {}

    def start(self, user_id: int, video_id: int) -> str:
        session_id = uuid.uuid4().hex
        self._sessions[session_id] = _PlaybackSession(user_id=user_id, video_id=video_id)
        if len(self._sessions) > 10_000:
            for key in list(self._sessions)[:2_000]:
                self._sessions.pop(key, None)
        return session_id

    def progress(self, session_id: str, user_id: int, video_id: int, position_ms: int, duration_ms: int | None) -> bool:
        session = self._sessions.get(session_id)
        if session is None or session.user_id != user_id or session.video_id != video_id:
            raise ValueError("invalid playSessionId")
        if not session.counted and position_ms >= _play_count_threshold(duration_ms):
            session.counted = True
            return True
        return False


def continue_watching(connection: sqlite3.Connection, user_id: int, *, limit: int = 30) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT v.id AS video_id, v.episode_or_type, v.episode_title, v.content_type,
               w.id AS work_id, w.official_title AS work_title,
               sg.display_name AS group_name,
               uvs.position_ms, uvs.duration_ms, uvs.last_played_at
        FROM user_video_state uvs
        JOIN videos v ON v.id = uvs.video_id
        JOIN works w ON w.id = v.work_id
        LEFT JOIN series_groups sg ON sg.id = v.series_group_id
        JOIN video_files vf ON vf.video_id = v.id
        WHERE uvs.user_id = ? AND uvs.position_ms > 0 AND uvs.watched = 0 AND vf.is_available = 1
        ORDER BY uvs.last_played_at DESC LIMIT ?
        """,
        (user_id, max(1, min(int(limit), 100))),
    ).fetchall()
    items = []
    for row in rows:
        duration = row["duration_ms"]
        position = int(row["position_ms"] or 0)
        percent = int(round(position * 100 / int(duration))) if duration and int(duration) > 0 else None
        items.append({"videoId": int(row["video_id"]), "workId": int(row["work_id"]), "workTitle": row["work_title"], "groupName": row["group_name"], "episodeOrType": row["episode_or_type"], "episodeTitle": row["episode_title"], "contentType": row["content_type"], "positionMs": position, "durationMs": duration, "percent": percent, "lastPlayedAt": row["last_played_at"]})
    return {"items": items}


def history(connection: sqlite3.Connection, user_id: int, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT v.id AS video_id, v.episode_or_type, v.episode_title,
               w.id AS work_id, w.official_title AS work_title,
               sg.display_name AS group_name,
               uvs.position_ms, uvs.duration_ms, uvs.watched,
               uvs.play_count, uvs.last_played_at
        FROM user_video_state uvs
        JOIN videos v ON v.id = uvs.video_id
        JOIN works w ON w.id = v.work_id
        LEFT JOIN series_groups sg ON sg.id = v.series_group_id
        WHERE uvs.user_id = ? AND uvs.last_played_at IS NOT NULL
        ORDER BY uvs.last_played_at DESC LIMIT ? OFFSET ?
        """,
        (user_id, max(1, min(int(limit), 200)), max(0, int(offset))),
    ).fetchall()
    return {"items": [{"videoId": int(row["video_id"]), "workId": int(row["work_id"]), "workTitle": row["work_title"], "groupName": row["group_name"], "episodeOrType": row["episode_or_type"], "episodeTitle": row["episode_title"], "positionMs": int(row["position_ms"] or 0), "durationMs": row["duration_ms"], "watched": bool(row["watched"]), "playCount": int(row["play_count"] or 0), "lastPlayedAt": row["last_played_at"]} for row in rows]}


def recent_works(connection: sqlite3.Connection, user_id: int, *, limit: int = 20) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT w.id, w.official_title, w.category, MAX(uvs.last_played_at) AS last_played_at
        FROM user_video_state uvs
        JOIN videos v ON v.id = uvs.video_id
        JOIN works w ON w.id = v.work_id
        WHERE uvs.user_id = ? AND uvs.last_played_at IS NOT NULL
        GROUP BY w.id, w.official_title, w.category
        ORDER BY last_played_at DESC LIMIT ?
        """,
        (user_id, max(1, min(int(limit), 100))),
    ).fetchall()
    return {"items": [{"id": int(row["id"]), "title": row["official_title"], "category": row["category"], "lastPlayedAt": row["last_played_at"]} for row in rows]}


def next_up(connection: sqlite3.Connection, user_id: int, *, limit: int = 20) -> dict[str, Any]:
    recent = connection.execute(
        """
        SELECT v.work_id, v.series_group_id, MAX(uvs.last_played_at) AS last_played_at
        FROM user_video_state uvs
        JOIN videos v ON v.id = uvs.video_id
        WHERE uvs.user_id = ? AND uvs.last_played_at IS NOT NULL AND v.content_type = 'EPISODE'
        GROUP BY v.work_id, v.series_group_id
        ORDER BY last_played_at DESC LIMIT 100
        """,
        (user_id,),
    ).fetchall()
    result = []
    for key in recent:
        current = connection.execute(
            """
            SELECT v.id, v.episode_sort_key
            FROM user_video_state uvs JOIN videos v ON v.id = uvs.video_id
            WHERE uvs.user_id = ? AND v.work_id = ?
              AND ((v.series_group_id = ?) OR (v.series_group_id IS NULL AND ? IS NULL))
              AND v.content_type = 'EPISODE' AND uvs.last_played_at IS NOT NULL
            ORDER BY uvs.last_played_at DESC LIMIT 1
            """,
            (user_id, key["work_id"], key["series_group_id"], key["series_group_id"]),
        ).fetchone()
        if current is None:
            continue
        candidate = connection.execute(
            """
            SELECT v.id, v.episode_or_type, v.episode_title,
                   w.id AS work_id, w.official_title AS work_title,
                   sg.display_name AS group_name
            FROM videos v
            JOIN works w ON w.id = v.work_id
            LEFT JOIN series_groups sg ON sg.id = v.series_group_id
            JOIN video_files vf ON vf.video_id = v.id
            LEFT JOIN user_video_state next_state ON next_state.video_id = v.id AND next_state.user_id = ?
            WHERE v.work_id = ?
              AND ((v.series_group_id = ?) OR (v.series_group_id IS NULL AND ? IS NULL))
              AND v.content_type = 'EPISODE' AND v.episode_sort_key > ?
              AND vf.is_available = 1 AND COALESCE(next_state.watched, 0) = 0
            ORDER BY v.episode_sort_key, v.id LIMIT 1
            """,
            (user_id, key["work_id"], key["series_group_id"], key["series_group_id"], current["episode_sort_key"]),
        ).fetchone()
        if candidate is not None:
            result.append({"videoId": int(candidate["id"]), "workId": int(candidate["work_id"]), "workTitle": candidate["work_title"], "groupName": candidate["group_name"], "episodeOrType": candidate["episode_or_type"], "episodeTitle": candidate["episode_title"]})
            if len(result) >= limit:
                break
    return {"items": result}
