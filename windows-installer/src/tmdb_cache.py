from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from database import now_iso


# 2026-09-17: image-cache repair v3 succeeded for the other reported titles,
# but the PRICELESS workId cache survived on one real library.  Keep the public
# cache key used by tmdb_sync stable while moving only its physical marker to a
# new generation.  Existing installations therefore run the small, targeted
# _STALE_IMAGE_REPAIR_WORKS migration one more time, then persist the new marker
# and return to the normal no-op path on subsequent syncs.
_CACHE_STORAGE_KEY_OVERRIDES = {
    "tmdb:image-cache-repair-version": "tmdb:image-cache-repair-version:gen2",
}


def _storage_key(cache_key: str) -> str:
    key = str(cache_key)
    return _CACHE_STORAGE_KEY_OVERRIDES.get(key, key)


def get_cached_json(connection: sqlite3.Connection, cache_key: str, *, now: str | None = None) -> Any | None:
    row = connection.execute(
        "SELECT payload_json, expires_at FROM tmdb_api_cache WHERE cache_key=?",
        (_storage_key(cache_key),),
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
        (_storage_key(cache_key), json.dumps(payload, ensure_ascii=False, separators=(",", ":")), fetched_at or now_iso(), expires_at),
    )


def delete_cached_json(connection: sqlite3.Connection, cache_key: str) -> None:
    connection.execute("DELETE FROM tmdb_api_cache WHERE cache_key=?", (_storage_key(cache_key),))
