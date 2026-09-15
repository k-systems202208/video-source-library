from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from database import now_iso


def get_cached_json(connection: sqlite3.Connection, cache_key: str, *, now: str | None = None) -> Any | None:
    row = connection.execute(
        "SELECT payload_json, expires_at FROM tmdb_api_cache WHERE cache_key=?",
        (str(cache_key),),
    ).fetchone()
    if row is None:
        return None
    expires_at = row["expires_at"]
    if expires_at:
        current = datetime.fromisoformat(now or now_iso())
        expiry = datetime.fromisoformat(str(expires_at))
        if expiry <= current:
            return None
    return json.loads(str(row["payload_json"]))


def put_cached_json(
    connection: sqlite3.Connection,
    cache_key: str,
    payload: Any,
    *,
    fetched_at: str | None = None,
    expires_at: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO tmdb_api_cache(cache_key, payload_json, fetched_at, expires_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(cache_key) DO UPDATE SET
            payload_json=excluded.payload_json,
            fetched_at=excluded.fetched_at,
            expires_at=excluded.expires_at
        """,
        (str(cache_key), json.dumps(payload, ensure_ascii=False, separators=(",", ":")), fetched_at or now_iso(), expires_at),
    )


def delete_cached_json(connection: sqlite3.Connection, cache_key: str) -> None:
    connection.execute("DELETE FROM tmdb_api_cache WHERE cache_key=?", (str(cache_key),))
