from __future__ import annotations

import sqlite3
import unicodedata
from typing import Any, Iterable


def list_work_visibility(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id,external_work_no,category,official_title,year_or_period,is_visible
        FROM works
        ORDER BY category COLLATE NOCASE, official_title COLLATE NOCASE, id
        """
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "externalWorkNo": int(row["external_work_no"]),
            "category": str(row["category"] or ""),
            "title": str(row["official_title"] or ""),
            "yearOrPeriod": str(row["year_or_period"] or ""),
            "visible": bool(row["is_visible"]),
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
) -> dict[str, int]:
    selected = sorted({int(value) for value in visible_work_ids if int(value) > 0})
    existing = {
        int(row["id"])
        for row in connection.execute("SELECT id FROM works").fetchall()
    }
    unknown = [work_id for work_id in selected if work_id not in existing]
    if unknown:
        raise LookupError("WORK_NOT_FOUND")

    try:
        connection.execute("BEGIN")
        connection.execute("UPDATE works SET is_visible=0")
        if selected:
            placeholders = ",".join("?" for _ in selected)
            connection.execute(
                f"UPDATE works SET is_visible=1 WHERE id IN ({placeholders})",
                selected,
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise

    return {
        "total": len(existing),
        "visible": len(selected),
        "hidden": len(existing) - len(selected),
    }
