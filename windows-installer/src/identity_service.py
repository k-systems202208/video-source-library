from __future__ import annotations

import sqlite3
from typing import Any

from tailscale_identity import TailscaleIdentity
from user_state import current_user, ensure_local_owner, now_iso


def local_owner_user(connection: sqlite3.Connection) -> dict[str, Any]:
    owner = ensure_local_owner(connection)
    return current_user(connection, int(owner["id"])) or owner


def resolve_tailscale_user(connection: sqlite3.Connection, identity: TailscaleIdentity) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT u.id, u.display_name, u.is_owner, u.is_active
        FROM user_identities ui
        JOIN users u ON u.id = ui.user_id
        WHERE ui.provider = 'tailscale' AND ui.subject = ?
        LIMIT 1
        """,
        (identity.subject,),
    ).fetchone()
    stamp = now_iso()
    if row is None:
        connection.execute(
            """
            INSERT INTO users(display_name, is_owner, is_active, created_at, updated_at, last_seen_at)
            VALUES (?, 0, 1, ?, ?, ?)
            """,
            (identity.display_name, stamp, stamp, stamp),
        )
        user_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.execute(
            """
            INSERT INTO user_identities(user_id, provider, subject, created_at, updated_at)
            VALUES (?, 'tailscale', ?, ?, ?)
            """,
            (user_id, identity.subject, stamp, stamp),
        )
        connection.commit()
    else:
        if not bool(row["is_active"]):
            return None
        user_id = int(row["id"])
        connection.execute(
            "UPDATE users SET display_name = ?, last_seen_at = ?, updated_at = ? WHERE id = ?",
            (identity.display_name, stamp, stamp, user_id),
        )
        connection.commit()
    return current_user(connection, user_id)
