from __future__ import annotations

import sqlite3
import unicodedata
from typing import Any, Iterable

from database import now_iso


def effective_visibility_sql(work_alias: str = "w") -> str:
    alias = str(work_alias or "w")
    return (
        "COALESCE(("
        "SELECT uv.is_visible FROM user_work_visibility uv "
        f"WHERE uv.user_id=? AND uv.work_id={alias}.id"
        f"), {alias}.is_visible)"
    )


def is_work_visible(
    connection: sqlite3.Connection,
    work_id: int,
    user_id: int | None,
) -> bool:
    row = connection.execute(
        f"""
        SELECT {effective_visibility_sql("w")} AS visible
        FROM works w
        WHERE w.id=?
        """,
        (user_id, int(work_id)),
    ).fetchone()
    return bool(row["visible"]) if row is not None else False


def is_video_visible(
    connection: sqlite3.Connection,
    video_id: int,
    user_id: int | None,
) -> bool:
    row = connection.execute(
        f"""
        SELECT {effective_visibility_sql("w")} AS visible
        FROM videos v
        JOIN works w ON w.id=v.work_id
        WHERE v.id=?
        """,
        (user_id, int(video_id)),
    ).fetchone()
    return bool(row["visible"]) if row is not None else False


def is_subtitle_visible(
    connection: sqlite3.Connection,
    subtitle_id: int,
    user_id: int | None,
) -> bool:
    row = connection.execute(
        f"""
        SELECT {effective_visibility_sql("w")} AS visible
        FROM subtitles st
        JOIN videos v ON v.id=st.video_id
        JOIN works w ON w.id=v.work_id
        WHERE st.id=?
        """,
        (user_id, int(subtitle_id)),
    ).fetchone()
    return bool(row["visible"]) if row is not None else False


def is_person_visible(
    connection: sqlite3.Connection,
    person_id: int,
    user_id: int | None,
) -> bool:
    row = connection.execute(
        f"""
        SELECT 1
        FROM tmdb_work_people wp
        JOIN works w ON w.id=wp.work_id
        WHERE wp.tmdb_person_id=?
          AND {effective_visibility_sql("w")}=1
        LIMIT 1
        """,
        (int(person_id), user_id),
    ).fetchone()
    return row is not None


def list_visibility_targets(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            u.id,
            u.display_name,
            u.last_seen_at,
            ui.subject,
            EXISTS(
                SELECT 1
                FROM user_work_visibility uv
                WHERE uv.user_id=u.id
            ) AS customized
        FROM users u
        JOIN user_identities ui ON ui.user_id=u.id
        WHERE ui.provider='tailscale' AND u.is_active=1
        ORDER BY
            CASE WHEN u.last_seen_at IS NULL THEN 1 ELSE 0 END,
            u.last_seen_at DESC,
            u.display_name COLLATE NOCASE,
            u.id
        """
    ).fetchall()
    result: list[dict[str, Any]] = [
        {
            "userId": None,
            "key": "common",
            "displayName": "共通設定",
            "subject": "",
            "label": "共通設定（ローカル／未個別設定ユーザー）",
            "customized": True,
        }
    ]
    for row in rows:
        display_name = str(row["display_name"] or row["subject"] or "Tailscale利用者")
        subject = str(row["subject"] or "")
        label = f"{display_name} ({subject})" if subject and subject != display_name else display_name
        result.append(
            {
                "userId": int(row["id"]),
                "key": f"tailscale:{int(row['id'])}",
                "displayName": display_name,
                "subject": subject,
                "label": label,
                "customized": bool(row["customized"]),
            }
        )
    return result


def _tailscale_user_exists(connection: sqlite3.Connection, user_id: int) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM users u
        JOIN user_identities ui ON ui.user_id=u.id
        WHERE u.id=? AND u.is_active=1 AND ui.provider='tailscale'
        LIMIT 1
        """,
        (int(user_id),),
    ).fetchone()
    return row is not None


def has_user_visibility_overrides(
    connection: sqlite3.Connection,
    user_id: int,
) -> bool:
    row = connection.execute(
        "SELECT 1 FROM user_work_visibility WHERE user_id=? LIMIT 1",
        (int(user_id),),
    ).fetchone()
    return row is not None


def list_work_visibility(
    connection: sqlite3.Connection,
    *,
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            w.id,
            w.external_work_no,
            w.category,
            w.official_title,
            w.year_or_period,
            w.is_visible AS common_visible,
            uv.is_visible AS user_visible,
            COALESCE(uv.is_visible, w.is_visible) AS effective_visible
        FROM works w
        LEFT JOIN user_work_visibility uv
          ON uv.user_id=? AND uv.work_id=w.id
        ORDER BY w.category COLLATE NOCASE, w.official_title COLLATE NOCASE, w.id
        """,
        (user_id,),
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "externalWorkNo": int(row["external_work_no"]),
            "category": str(row["category"] or ""),
            "title": str(row["official_title"] or ""),
            "yearOrPeriod": str(row["year_or_period"] or ""),
            "visible": bool(row["effective_visible"]),
            "commonVisible": bool(row["common_visible"]),
            "inherited": row["user_visible"] is None,
        }
        for row in rows
    ]


def _normalize_filter_text(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()


def filter_work_visibility(
    items: Iterable[dict[str, Any]],
    query: str | None,
) -> list[dict[str, Any]]:
    key = _normalize_filter_text(query)
    rows = list(items)
    if not key:
        return rows
    return [
        item
        for item in rows
        if key in _normalize_filter_text(item.get("title"))
    ]


def replace_visible_work_ids(
    connection: sqlite3.Connection,
    visible_work_ids: Iterable[int],
    *,
    user_id: int | None = None,
) -> dict[str, int | bool | None]:
    selected = sorted({int(value) for value in visible_work_ids if int(value) > 0})
    existing_rows = connection.execute("SELECT id FROM works ORDER BY id").fetchall()
    existing = [int(row["id"]) for row in existing_rows]
    existing_set = set(existing)
    unknown = [work_id for work_id in selected if work_id not in existing_set]
    if unknown:
        raise LookupError("WORK_NOT_FOUND")
    if user_id is not None and not _tailscale_user_exists(connection, int(user_id)):
        raise LookupError("TAILSCALE_USER_NOT_FOUND")

    stamp = now_iso()
    selected_set = set(selected)
    try:
        connection.execute("BEGIN")
        if user_id is None:
            connection.execute("UPDATE works SET is_visible=0, updated_at=?", (stamp,))
            if selected:
                placeholders = ",".join("?" for _ in selected)
                connection.execute(
                    f"UPDATE works SET is_visible=1, updated_at=? WHERE id IN ({placeholders})",
                    [stamp, *selected],
                )
        else:
            uid = int(user_id)
            connection.execute(
                "DELETE FROM user_work_visibility WHERE user_id=?",
                (uid,),
            )
            connection.executemany(
                """
                INSERT INTO user_work_visibility(
                    user_id,work_id,is_visible,created_at,updated_at
                ) VALUES(?,?,?,?,?)
                """,
                [
                    (uid, work_id, 1 if work_id in selected_set else 0, stamp, stamp)
                    for work_id in existing
                ],
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise

    return {
        "total": len(existing),
        "visible": len(selected),
        "hidden": len(existing) - len(selected),
        "userId": int(user_id) if user_id is not None else None,
        "customized": user_id is not None,
    }


def reset_user_visibility(
    connection: sqlite3.Connection,
    user_id: int,
) -> dict[str, int | bool]:
    uid = int(user_id)
    if not _tailscale_user_exists(connection, uid):
        raise LookupError("TAILSCALE_USER_NOT_FOUND")
    cursor = connection.execute(
        "DELETE FROM user_work_visibility WHERE user_id=?",
        (uid,),
    )
    connection.commit()
    return {
        "userId": uid,
        "reset": True,
        "deleted": max(0, int(cursor.rowcount or 0)),
    }
