from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from database import connect, initialize_database, now_iso
from tmdb_cache import get_cached_json, put_cached_json
from tmdb_images import cached_person_image_path, download_tmdb_image

_PERSON_SPLIT_RE = re.compile(r"\s*(?:、|,|，|;|；|\||／|/|\r?\n)\s*")
_CREDITS_TTL_DAYS = 30
_PEOPLE_SYNC_VERSION = 2
_PEOPLE_SYNC_CACHE_KEY = "tmdb:people-sync-version"


def _clean_local_person_label(value: str | None) -> str:
    name = str(value or "").strip()
    name = re.sub(r"\s*(?:ほか|他)(?:[（(][^）)]*[）)])?$", "", name).strip()
    name = re.sub(r"[（(](?:各話ゲスト多数?|声)[）)]$", "", name).strip()
    return name


def split_local_people(value: str | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in _PERSON_SPLIT_RE.split(str(value or "")):
        name = _clean_local_person_label(raw)
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


def person_name_queries(local_name: str) -> list[str]:
    text = str(local_name or "").strip()
    values: list[str] = []
    seen: set[str] = set()

    def add(value: str | None) -> None:
        candidate = str(value or "").strip()
        key = normalize_person_name(candidate)
        if candidate and key and key not in seen:
            seen.add(key)
            values.append(candidate)

    add(text)
    add(re.sub(r"[（(][^）)]*[）)]", "", text).strip())
    for match in re.findall(r"[（(]([^）)]*)[）)]", text):
        alternate = str(match or "").strip()
        alternate = re.sub(r"^(?:現|旧|旧芸名|本名)\s*[・:：]\s*", "", alternate).strip()
        if alternate and alternate not in {"声", "各話ゲスト", "各話ゲスト多数"}:
            add(alternate)
    return values


def _person_search_cache_key(query: str) -> str:
    return f"tmdb:person-search:v1:{normalize_person_name(query)}"


def _cached_person_search(
    connection: sqlite3.Connection,
    client: Any,
    query: str,
) -> dict[str, Any]:
    key = _person_search_cache_key(query)
    cached = get_cached_json(connection, key)
    if isinstance(cached, dict):
        return cached
    search = getattr(client, "search_person", None)
    if not callable(search):
        return {}
    value = search(query, language="ja-JP")
    if not isinstance(value, dict):
        value = {}
    fetched = now_iso()
    expiry = (datetime.fromisoformat(fetched) + timedelta(days=_CREDITS_TTL_DAYS)).isoformat(timespec="seconds")
    put_cached_json(connection, key, value, fetched_at=fetched, expires_at=expiry)
    connection.commit()
    return value


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


def _cast_by_id(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    cast = payload.get("cast")
    if not isinstance(cast, list):
        return {}
    result: dict[int, dict[str, Any]] = {}
    for item in cast:
        if not isinstance(item, dict):
            continue
        try:
            person_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        if person_id > 0:
            result[person_id] = item
    return result


def _resolve_candidate(
    connection: sqlite3.Connection,
    client: Any,
    payload: dict[str, Any],
    index: dict[str, list[dict[str, Any]]],
    local_name: str,
) -> tuple[dict[str, Any] | None, str | None]:
    queries = person_name_queries(local_name)
    for query in queries:
        direct = _unique_candidate(index, query)
        if direct is not None:
            return direct, "EXACT"

    cast_items = _cast_by_id(payload)
    if not cast_items:
        return None, None

    matched: dict[int, tuple[dict[str, Any], dict[str, Any]]] = {}
    for query in queries:
        search_payload = _cached_person_search(connection, client, query)
        results = search_payload.get("results")
        if not isinstance(results, list):
            continue
        for result in results:
            if not isinstance(result, dict):
                continue
            try:
                person_id = int(result.get("id"))
            except (TypeError, ValueError):
                continue
            cast_item = cast_items.get(person_id)
            if cast_item is not None:
                matched[person_id] = (cast_item, result)

    if len(matched) != 1:
        return None, None

    cast_item, search_item = next(iter(matched.values()))
    resolved = dict(cast_item)
    if not resolved.get("profile_path") and search_item.get("profile_path"):
        resolved["profile_path"] = search_item.get("profile_path")
    if not resolved.get("name") and search_item.get("name"):
        resolved["name"] = search_item.get("name")
    if not resolved.get("original_name") and search_item.get("original_name"):
        resolved["original_name"] = search_item.get("original_name")
    return resolved, "CREDIT_CONSTRAINED_SEARCH"


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
    if not names:
        connection.execute(
            "DELETE FROM tmdb_work_people WHERE work_id=? AND role='CAST'",
            (int(work_id),),
        )
        connection.commit()
        return {"matched": 0, "profileCached": 0, "personIds": []}

    # Fetch first so a temporary TMDb/network failure never erases a previously
    # valid person mapping.
    payload = _cached_credits(connection, client, media_type, tmdb_id)
    index = _cast_index(payload)
    connection.execute(
        "DELETE FROM tmdb_work_people WHERE work_id=? AND role='CAST'",
        (int(work_id),),
    )
    matched_ids: list[int] = []
    cached_ids: list[int] = []
    matched_exact = 0
    matched_search = 0
    unmatched = 0
    stamp = now_iso()

    for local_order, local_name in enumerate(names):
        item, match_method = _resolve_candidate(connection, client, payload, index, local_name)
        if item is None:
            unmatched += 1
            continue
        if match_method == "EXACT":
            matched_exact += 1
        elif match_method == "CREDIT_CONSTRAINED_SEARCH":
            matched_search += 1
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
        "matchedExact": matched_exact,
        "matchedBySearch": matched_search,
        "unmatched": unmatched,
        "profileCached": len(set(cached_ids)),
        "personIds": sorted(set(matched_ids)),
    }


def people_sync_required(connection: sqlite3.Connection) -> bool:
    payload = get_cached_json(connection, _PEOPLE_SYNC_CACHE_KEY)
    if not isinstance(payload, dict):
        return True
    try:
        return int(payload.get("version") or 0) < _PEOPLE_SYNC_VERSION
    except (TypeError, ValueError):
        return True


def mark_people_sync_complete(connection: sqlite3.Connection) -> None:
    put_cached_json(
        connection,
        _PEOPLE_SYNC_CACHE_KEY,
        {"version": _PEOPLE_SYNC_VERSION},
        fetched_at=now_iso(),
        expires_at=None,
    )


def sync_tmdb_people_library(
    database_path: Path | str,
    image_root: Path | str,
    access_token: str,
    *,
    client: Any | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    image_downloader: Callable[..., Path] = download_tmdb_image,
) -> dict[str, Any]:
    from tmdb_client import TmdbClient

    token = str(access_token or "").strip()
    if not token:
        raise ValueError("TMDb API Read Access Token is not configured")
    tmdb = client or TmdbClient(token)
    matched_ids: set[int] = set()
    cached_ids: set[int] = set()
    failures = 0

    with connect(database_path) as connection:
        initialize_database(connection)
        works = connection.execute(
            """
            SELECT w.id,w.official_title,w.main_cast_or_voice_actors,
                   t.media_type,t.tmdb_id
            FROM works w
            JOIN tmdb_work_links t ON t.work_id=w.id
            WHERE t.match_status='MATCHED'
              AND t.tmdb_id IS NOT NULL
              AND TRIM(COALESCE(w.main_cast_or_voice_actors,''))<>''
            ORDER BY w.external_work_no
            """
        ).fetchall()
        total = len(works)
        for index, work in enumerate(works, start=1):
            try:
                result = sync_cast_people_for_work(
                    connection,
                    tmdb,
                    work_id=int(work["id"]),
                    media_type=str(work["media_type"]),
                    tmdb_id=int(work["tmdb_id"]),
                    local_cast=str(work["main_cast_or_voice_actors"] or ""),
                    image_root=image_root,
                    image_downloader=image_downloader,
                )
                matched_ids.update(int(value) for value in result.get("personIds") or [])
                for person_id in result.get("personIds") or []:
                    row = connection.execute(
                        "SELECT profile_path FROM tmdb_people WHERE tmdb_person_id=?",
                        (int(person_id),),
                    ).fetchone()
                    if row is not None and row["profile_path"]:
                        try:
                            if cached_person_image_path(
                                image_root, int(person_id), str(row["profile_path"])
                            ).is_file():
                                cached_ids.add(int(person_id))
                        except ValueError:
                            pass
            except Exception:
                failures += 1

            if progress_callback is not None:
                progress_callback(
                    {
                        "current": index,
                        "total": total,
                        "matchedPeople": len(matched_ids),
                        "profileCached": len(cached_ids),
                        "failures": failures,
                        "currentItem": str(work["official_title"]),
                    }
                )

        if failures == 0:
            mark_people_sync_complete(connection)
        connection.commit()

    return {
        "totalWorks": len(works),
        "matchedPeople": len(matched_ids),
        "profileCached": len(cached_ids),
        "failures": failures,
        "completed": failures == 0,
    }
