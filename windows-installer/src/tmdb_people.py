from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from database import now_iso
from tmdb_cache import get_cached_json, put_cached_json
from tmdb_images import cached_person_image_path, download_tmdb_image

_PERSON_SPLIT_RE = re.compile(r"\s*(?:、|,|，|;|；|\||\r?\n|\s+/\s+)\s*")
_CREDITS_TTL_DAYS = 30


def split_local_people(value: str | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in _PERSON_SPLIT_RE.split(str(value or "")):
        name = re.sub(r"\s*(?:ほか|他)$", "", raw.strip()).strip()
        if not name:
            continue
        key = normalize_person_name(name)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(name)
    return result


def normalize_person_name(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return re.sub(r"[\s\u3000]+", "", text)


def _credits_cache_key(media_type: str, tmdb_id: int) -> str:
    return f"tmdb:credits:v1:{media_type}:{int(tmdb_id)}:ja-JP"


def _cached_credits(
    connection: sqlite3.Connection,
    client: Any,
    media_type: str,
    tmdb_id: int,
) -> dict[str, Any]:
    key = _credits_cache_key(media_type, tmdb_id)
    cached = get_cached_json(connection, key)
    if isinstance(cached, dict):
        return cached

    if media_type == "movie":
        value = client.movie_credits(int(tmdb_id), language="ja-JP")
    elif media_type == "tv":
        value = client.tv_aggregate_credits(int(tmdb_id), language="ja-JP")
    else:
        return {}

    if not isinstance(value, dict):
        value = {}
    fetched = now_iso()
    expiry = (datetime.fromisoformat(fetched) + timedelta(days=_CREDITS_TTL_DAYS)).isoformat(timespec="seconds")
    put_cached_json(connection, key, value, fetched_at=fetched, expires_at=expiry)
    connection.commit()
    return value


def _character_text(item: dict[str, Any]) -> str:
    direct = str(item.get("character") or "").strip()
    if direct:
        return direct
    roles = item.get("roles")
    if not isinstance(roles, list):
        return ""
    values: list[str] = []
    for role in roles:
        if not isinstance(role, dict):
            continue
        character = str(role.get("character") or "").strip()
        if character and character not in values:
            values.append(character)
    return " / ".join(values[:4])


def _billing_order(item: dict[str, Any], fallback: int) -> int:
    try:
        return int(item.get("order"))
    except (TypeError, ValueError):
        pass
    roles = item.get("roles")
    if isinstance(roles, list):
        orders: list[int] = []
        for role in roles:
            if not isinstance(role, dict):
                continue
            try:
                orders.append(int(role.get("order")))
            except (TypeError, ValueError):
                continue
        if orders:
            return min(orders)
    return fallback


def _cast_index(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    cast = payload.get("cast")
    if not isinstance(cast, list):
        return {}
    index: dict[str, list[dict[str, Any]]] = {}
    for item in cast:
        if not isinstance(item, dict):
            continue
        try:
            person_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        if person_id <= 0:
            continue
        for field in ("name", "original_name"):
            key = normalize_person_name(item.get(field))
            if key:
                index.setdefault(key, []).append(item)
    return index


def _unique_candidate(index: dict[str, list[dict[str, Any]]], local_name: str) -> dict[str, Any] | None:
    candidates = index.get(normalize_person_name(local_name), [])
    by_id: dict[int, dict[str, Any]] = {}
    for item in candidates:
        try:
            by_id[int(item.get("id"))] = item
        except (TypeError, ValueError):
            continue
    if len(by_id) != 1:
        return None
    return next(iter(by_id.values()))


def _upsert_person(connection: sqlite3.Connection, item: dict[str, Any]) -> tuple[int, str | None, bool]:
    person_id = int(item["id"])
    display_name = str(item.get("name") or item.get("original_name") or person_id).strip()
    original_name = str(item.get("original_name") or "").strip() or None
    profile_path = str(item.get("profile_path") or "").strip() or None
    known_for = str(item.get("known_for_department") or "").strip() or None
    previous = connection.execute(
        "SELECT profile_path FROM tmdb_people WHERE tmdb_person_id=?",
        (person_id,),
    ).fetchone()
    profile_changed = previous is not None and str(previous["profile_path"] or "") != str(profile_path or "")
    stamp = now_iso()
    connection.execute(
        """
        INSERT INTO tmdb_people(
            tmdb_person_id,display_name,original_name,profile_path,known_for_department,
            synced_at,created_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(tmdb_person_id) DO UPDATE SET
            display_name=excluded.display_name,
            original_name=excluded.original_name,
            profile_path=excluded.profile_path,
            known_for_department=excluded.known_for_department,
            synced_at=excluded.synced_at,
            updated_at=excluded.updated_at
        """,
        (person_id, display_name, original_name, profile_path, known_for, stamp, stamp, stamp),
    )
    return person_id, profile_path, profile_changed


def sync_cast_people_for_work(
    connection: sqlite3.Connection,
    client: Any,
    *,
    work_id: int,
    media_type: str,
    tmdb_id: int,
    local_cast: str | None,
    image_root: Path | str,
    image_downloader: Callable[..., Path] = download_tmdb_image,
) -> dict[str, Any]:
    names = split_local_people(local_cast)
    connection.execute(
        "DELETE FROM tmdb_work_people WHERE work_id=? AND role='CAST'",
        (int(work_id),),
    )
    if not names:
        connection.commit()
        return {"matched": 0, "profileCached": 0, "personIds": []}

    payload = _cached_credits(connection, client, media_type, tmdb_id)
    index = _cast_index(payload)
    matched_ids: list[int] = []
    cached_ids: list[int] = []
    stamp = now_iso()

    for local_order, local_name in enumerate(names):
        item = _unique_candidate(index, local_name)
        if item is None:
            continue
        person_id, profile_path, profile_changed = _upsert_person(connection, item)
        character = _character_text(item) or None
        billing_order = _billing_order(item, local_order)
        connection.execute(
            """
            INSERT INTO tmdb_work_people(
                work_id,role,local_name,tmdb_person_id,character_text,billing_order,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(work_id,role,local_name) DO UPDATE SET
                tmdb_person_id=excluded.tmdb_person_id,
                character_text=excluded.character_text,
                billing_order=excluded.billing_order,
                updated_at=excluded.updated_at
            """,
            (int(work_id), "CAST", local_name, person_id, character, billing_order, stamp, stamp),
        )
        matched_ids.append(person_id)

        if profile_path:
            try:
                target = cached_person_image_path(image_root, person_id, profile_path)
                if profile_changed and target.is_file():
                    target.unlink()
                if not target.is_file():
                    image_downloader(profile_path, target, size="w185")
                if target.is_file():
                    cached_ids.append(person_id)
            except Exception:
                pass

    connection.commit()
    return {
        "matched": len(matched_ids),
        "profileCached": len(set(cached_ids)),
        "personIds": sorted(set(matched_ids)),
    }
