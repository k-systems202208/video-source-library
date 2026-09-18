from __future__ import annotations

import csv
import json
import re
import sqlite3
import unicodedata
from collections import Counter
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
        return {
            "matched": 0,
            "matchedExact": 0,
            "matchedBySearch": 0,
            "unmatched": 0,
            "profileCached": 0,
            "personIds": [],
        }

    # Resolve every candidate before replacing existing links.  This keeps the
    # previous mapping intact if TMDb credits/person-search has a temporary
    # network failure halfway through a work.
    payload = _cached_credits(connection, client, media_type, tmdb_id)
    index = _cast_index(payload)
    resolved_people: list[tuple[int, str, dict[str, Any], str | None]] = []
    matched_exact = 0
    matched_search = 0
    unmatched = 0

    for local_order, local_name in enumerate(names):
        item, match_method = _resolve_candidate(connection, client, payload, index, local_name)
        if item is None:
            unmatched += 1
            continue
        if match_method == "EXACT":
            matched_exact += 1
        elif match_method == "CREDIT_CONSTRAINED_SEARCH":
            matched_search += 1
        resolved_people.append((local_order, local_name, item, match_method))

    connection.execute(
        "DELETE FROM tmdb_work_people WHERE work_id=? AND role='CAST'",
        (int(work_id),),
    )
    matched_ids: list[int] = []
    cached_ids: list[int] = []
    stamp = now_iso()

    for local_order, local_name, item, _match_method in resolved_people:
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
    report_dir: Path | str | None = None,
) -> dict[str, Any]:
    from tmdb_client import TmdbClient

    token = str(access_token or "").strip()
    if not token:
        raise ValueError("TMDb API Read Access Token is not configured")
    tmdb = client or TmdbClient(token)
    matched_ids: set[int] = set()
    cached_ids: set[int] = set()
    failures = 0
    matched_by_search = 0

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
                matched_by_search += int(result.get("matchedBySearch") or 0)
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
                        "matchedBySearch": matched_by_search,
                        "failures": failures,
                        "currentItem": str(work["official_title"]),
                    }
                )

        if failures == 0:
            mark_people_sync_complete(connection)
        connection.commit()

    result = {
        "totalWorks": len(works),
        "matchedPeople": len(matched_ids),
        "profileCached": len(cached_ids),
        "matchedBySearch": matched_by_search,
        "failures": failures,
        "completed": failures == 0,
    }
    if report_dir is not None:
        result["peopleAudit"] = audit_tmdb_people_profiles(
            database_path,
            report_dir,
            token,
            client=tmdb,
        )
    return result


def _person_audit_reason(
    *,
    linked_ids: set[int],
    linked_profile_paths: dict[int, str | None],
    matched_work_count: int,
    direct_credit_ids: set[int],
    constrained_search_ids: set[int],
    search_result_ids: set[int],
) -> str:
    if len(linked_ids) > 1:
        return "AMBIGUOUS"
    if len(linked_ids) == 1:
        person_id = next(iter(linked_ids))
        return "PROFILE_READY" if linked_profile_paths.get(person_id) else "PERSON_NO_PROFILE"
    if matched_work_count == 0:
        return "NO_MATCHED_WORK"
    combined_credit_ids = direct_credit_ids | constrained_search_ids
    if len(combined_credit_ids) > 1:
        return "AMBIGUOUS"
    if len(combined_credit_ids) == 1:
        return "CREDIT_NAME_MISMATCH"
    if search_result_ids:
        return "PERSON_SEARCH_NOT_IN_CREDITS"
    return "CREDIT_PERSON_NOT_FOUND"


def _write_people_audit_report(
    report_dir: Path | str,
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> tuple[Path, Path]:
    destination = Path(report_dir)
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = destination / f"tmdb-people-audit-{stamp}.json"
    csv_path = destination / f"tmdb-people-audit-{stamp}.csv"
    json_path.write_text(
        json.dumps({"summary": summary, "items": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    fields = [
        "name",
        "workCount",
        "reason",
        "tmdbPersonIds",
        "profilePaths",
        "matchedWorkCount",
        "matchedWorks",
        "searchQueries",
        "directCreditIds",
        "constrainedSearchIds",
        "searchResultIds",
        "creditNameSample",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "name": row.get("name", ""),
                    "workCount": row.get("workCount", 0),
                    "reason": row.get("reason", ""),
                    "tmdbPersonIds": "|".join(str(v) for v in row.get("tmdbPersonIds", [])),
                    "profilePaths": "|".join(str(v) for v in row.get("profilePaths", [])),
                    "matchedWorkCount": row.get("matchedWorkCount", 0),
                    "matchedWorks": " | ".join(row.get("matchedWorks", [])),
                    "searchQueries": " | ".join(row.get("searchQueries", [])),
                    "directCreditIds": "|".join(str(v) for v in row.get("directCreditIds", [])),
                    "constrainedSearchIds": "|".join(str(v) for v in row.get("constrainedSearchIds", [])),
                    "searchResultIds": "|".join(str(v) for v in row.get("searchResultIds", [])),
                    "creditNameSample": " | ".join(row.get("creditNameSample", [])),
                }
            )
    return json_path, csv_path


def audit_tmdb_people_profiles(
    database_path: Path | str,
    report_dir: Path | str,
    access_token: str,
    *,
    client: Any | None = None,
) -> dict[str, Any]:
    from tmdb_client import TmdbClient

    token = str(access_token or "").strip()
    if not token:
        raise ValueError("TMDb API Read Access Token is not configured")
    tmdb = client or TmdbClient(token)
    rows: list[dict[str, Any]] = []

    with connect(database_path) as connection:
        initialize_database(connection)
        work_rows = connection.execute(
            """
            SELECT
                w.id,w.official_title,w.main_cast_or_voice_actors,
                t.match_status,t.media_type,t.tmdb_id
            FROM works w
            LEFT JOIN tmdb_work_links t ON t.work_id=w.id
            WHERE TRIM(COALESCE(w.main_cast_or_voice_actors,''))<>''
            ORDER BY w.external_work_no
            """
        ).fetchall()

        occurrences: dict[str, list[sqlite3.Row]] = {}
        for work in work_rows:
            for local_name in split_local_people(work["main_cast_or_voice_actors"]):
                occurrences.setdefault(local_name, []).append(work)

        all_links = connection.execute(
            """
            SELECT wp.local_name,wp.tmdb_person_id,p.profile_path
            FROM tmdb_work_people wp
            JOIN tmdb_people p ON p.tmdb_person_id=wp.tmdb_person_id
            WHERE wp.role='CAST'
            """
        ).fetchall()
        links_by_name: dict[str, dict[int, str | None]] = {}
        for link in all_links:
            links_by_name.setdefault(str(link["local_name"]), {})[
                int(link["tmdb_person_id"])
            ] = str(link["profile_path"]) if link["profile_path"] else None

        for local_name, person_works in occurrences.items():
            linked_profiles = links_by_name.get(local_name, {})
            linked_ids = set(linked_profiles)
            matched_works = [
                work
                for work in person_works
                if str(work["match_status"] or "") == "MATCHED" and work["tmdb_id"] is not None
            ]
            queries = person_name_queries(local_name)
            direct_ids: set[int] = set()
            constrained_ids: set[int] = set()
            search_ids: set[int] = set()
            credit_names: list[str] = []
            matched_work_labels: list[str] = []

            if not linked_ids:
                for work in matched_works:
                    media_type = str(work["media_type"] or "")
                    tmdb_id = int(work["tmdb_id"])
                    matched_work_labels.append(
                        f"{work['official_title']} [{media_type}:{tmdb_id}]"
                    )
                    payload = _cached_credits(connection, tmdb, media_type, tmdb_id)
                    index = _cast_index(payload)
                    cast_by_id = _cast_by_id(payload)
                    for cast_item in cast_by_id.values():
                        for field in ("name", "original_name"):
                            value = str(cast_item.get(field) or "").strip()
                            if value and value not in credit_names:
                                credit_names.append(value)
                    for query in queries:
                        for item in index.get(normalize_person_name(query), []):
                            try:
                                direct_ids.add(int(item.get("id")))
                            except (TypeError, ValueError):
                                continue
                        search_payload = _cached_person_search(connection, tmdb, query)
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
                            if person_id <= 0:
                                continue
                            search_ids.add(person_id)
                            if person_id in cast_by_id:
                                constrained_ids.add(person_id)
            else:
                matched_work_labels = [
                    f"{work['official_title']} [{work['media_type']}:{work['tmdb_id']}]"
                    for work in matched_works
                ]

            reason = _person_audit_reason(
                linked_ids=linked_ids,
                linked_profile_paths=linked_profiles,
                matched_work_count=len(matched_works),
                direct_credit_ids=direct_ids,
                constrained_search_ids=constrained_ids,
                search_result_ids=search_ids,
            )
            rows.append(
                {
                    "name": local_name,
                    "workCount": len(person_works),
                    "reason": reason,
                    "tmdbPersonIds": sorted(linked_ids),
                    "profilePaths": sorted(
                        {path for path in linked_profiles.values() if path}
                    ),
                    "matchedWorkCount": len(matched_works),
                    "matchedWorks": matched_work_labels,
                    "searchQueries": queries,
                    "directCreditIds": sorted(direct_ids),
                    "constrainedSearchIds": sorted(constrained_ids),
                    "searchResultIds": sorted(search_ids),
                    "creditNameSample": credit_names[:40],
                }
            )

    reason_counts = Counter(str(row["reason"]) for row in rows)
    summary = {
        "totalPeople": len(rows),
        "profileReady": reason_counts.get("PROFILE_READY", 0),
        "personNoProfile": reason_counts.get("PERSON_NO_PROFILE", 0),
        "noMatchedWork": reason_counts.get("NO_MATCHED_WORK", 0),
        "creditNameMismatch": reason_counts.get("CREDIT_NAME_MISMATCH", 0),
        "personSearchNotInCredits": reason_counts.get("PERSON_SEARCH_NOT_IN_CREDITS", 0),
        "creditPersonNotFound": reason_counts.get("CREDIT_PERSON_NOT_FOUND", 0),
        "ambiguous": reason_counts.get("AMBIGUOUS", 0),
        "reasons": dict(sorted(reason_counts.items())),
    }
    json_path, csv_path = _write_people_audit_report(report_dir, rows, summary)
    return {
        "summary": summary,
        "jsonReport": str(json_path),
        "csvReport": str(csv_path),
    }
