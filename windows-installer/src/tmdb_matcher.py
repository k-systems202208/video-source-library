from __future__ import annotations

import csv
import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable

from database import connect, initialize_database, now_iso
from tmdb_cache import get_cached_json, put_cached_json
from tmdb_client import TmdbClient, TmdbError

AUTO_MATCH_THRESHOLD = 0.92
AUTO_MATCH_MARGIN = 0.08
REVIEW_THRESHOLD = 0.75
SEARCH_CACHE_DAYS = 7
DETAIL_CACHE_DAYS = 30


def normalize_title(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return "".join(ch for ch in text if ch.isalnum())


def extract_year(value: str | None) -> int | None:
    match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", str(value or ""))
    return int(match.group(1)) if match else None


def _candidate_year(item: dict[str, Any], media_type: str) -> int | None:
    key = "release_date" if media_type == "movie" else "first_air_date"
    return extract_year(str(item.get(key) or ""))


def _candidate_titles(item: dict[str, Any], media_type: str) -> list[str]:
    if media_type == "movie":
        values = [item.get("title"), item.get("original_title")]
    else:
        values = [item.get("name"), item.get("original_name")]
    return [str(value) for value in values if str(value or "").strip()]


def preferred_media_types(category: str | None, media_file_count: int | None = None) -> tuple[list[str], str | None]:
    value = str(category or "").casefold()
    count = int(media_file_count or 0)
    if "映画" in value or "movie" in value:
        return ["movie"], "movie"
    if "ドラマ" in value or "tv" in value or "テレビ" in value:
        return ["tv"], "tv"
    if "アニメ" in value or "anime" in value:
        preferred = "tv" if count > 1 else None
        return ["tv", "movie"], preferred
    return ["movie", "tv"], None


def candidate_score(
    local_title: str,
    local_year: int | None,
    media_type: str,
    item: dict[str, Any],
    *,
    preferred_media_type: str | None = None,
) -> tuple[float, float]:
    source = normalize_title(local_title)
    ratios: list[float] = []
    for title in _candidate_titles(item, media_type):
        candidate = normalize_title(title)
        if not candidate or not source:
            continue
        ratios.append(1.0 if candidate == source else SequenceMatcher(None, source, candidate).ratio())
    title_ratio = max(ratios, default=0.0)
    score = title_ratio * 0.80

    year = _candidate_year(item, media_type)
    if local_year is not None and year is not None:
        delta = abs(local_year - year)
        if delta == 0:
            score += 0.14
        elif delta == 1:
            score += 0.07
        elif delta >= 3:
            score -= 0.08
    elif local_year is None or year is None:
        score += 0.03

    if preferred_media_type is not None and media_type == preferred_media_type:
        score += 0.06

    return max(0.0, min(1.0, score)), title_ratio


def _expires(days: int) -> str:
    return (datetime.now().astimezone() + timedelta(days=days)).isoformat(timespec="seconds")


def _cache_key(kind: str, *parts: Any) -> str:
    safe = [normalize_title(str(value))[:100] for value in parts]
    return "tmdb:" + kind + ":" + ":".join(safe)


def _search(
    connection: sqlite3.Connection,
    client: TmdbClient,
    media_type: str,
    query: str,
    year: int | None,
) -> dict[str, Any]:
    key = _cache_key("search", media_type, query, year or "")
    cached = get_cached_json(connection, key)
    if isinstance(cached, dict):
        return cached
    if media_type == "movie":
        payload = client.search_movie(query, year=year)
    else:
        payload = client.search_tv(query, first_air_date_year=year)
    put_cached_json(connection, key, payload, expires_at=_expires(SEARCH_CACHE_DAYS))
    return payload


def _details(
    connection: sqlite3.Connection,
    client: TmdbClient,
    media_type: str,
    tmdb_id: int,
) -> dict[str, Any]:
    key = _cache_key("details", media_type, tmdb_id)
    cached = get_cached_json(connection, key)
    if isinstance(cached, dict):
        return cached
    payload = client.movie_details(tmdb_id) if media_type == "movie" else client.tv_details(tmdb_id)
    put_cached_json(connection, key, payload, expires_at=_expires(DETAIL_CACHE_DAYS))
    return payload


def _display_title(item: dict[str, Any], media_type: str) -> str:
    return str(item.get("title") if media_type == "movie" else item.get("name") or "")


def _upsert_link(connection: sqlite3.Connection, work_id: int, result: dict[str, Any]) -> None:
    stamp = now_iso()
    connection.execute(
        """
        INSERT INTO tmdb_work_links(
            work_id,media_type,tmdb_id,match_status,confidence,matched_title,matched_year,
            poster_path,backdrop_path,overview,synced_at,created_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(work_id) DO UPDATE SET
            media_type=excluded.media_type,
            tmdb_id=excluded.tmdb_id,
            match_status=excluded.match_status,
            confidence=excluded.confidence,
            matched_title=excluded.matched_title,
            matched_year=excluded.matched_year,
            poster_path=excluded.poster_path,
            backdrop_path=excluded.backdrop_path,
            overview=excluded.overview,
            synced_at=excluded.synced_at,
            updated_at=excluded.updated_at
        """,
        (
            work_id,
            result.get("mediaType"),
            result.get("tmdbId"),
            result.get("status") or "UNMATCHED",
            result.get("confidence"),
            result.get("matchedTitle"),
            result.get("matchedYear"),
            result.get("posterPath"),
            result.get("backdropPath"),
            result.get("overview"),
            stamp,
            stamp,
            stamp,
        ),
    )


def match_work(
    connection: sqlite3.Connection,
    client: TmdbClient,
    work: sqlite3.Row | dict[str, Any],
) -> dict[str, Any]:
    row = dict(work)
    work_id = int(row["id"])
    title = str(row.get("official_title") or "").strip()
    source_title = str(row.get("source_title") or "").strip()
    year = extract_year(row.get("year_or_period"))
    search_types, preferred = preferred_media_types(row.get("category"), row.get("media_file_count"))

    candidates: list[dict[str, Any]] = []
    queries = [title]
    if source_title and normalize_title(source_title) != normalize_title(title):
        queries.append(source_title)

    for media_type in search_types:
        seen_ids: set[int] = set()
        for query in queries:
            if not query:
                continue
            payload = _search(connection, client, media_type, query, year)
            for item in list(payload.get("results") or [])[:20]:
                try:
                    tmdb_id = int(item.get("id"))
                except (TypeError, ValueError):
                    continue
                if tmdb_id in seen_ids:
                    continue
                seen_ids.add(tmdb_id)
                score, title_ratio = candidate_score(title, year, media_type, item, preferred_media_type=preferred)
                candidates.append(
                    {
                        "mediaType": media_type,
                        "tmdbId": tmdb_id,
                        "score": score,
                        "titleRatio": title_ratio,
                        "item": item,
                    }
                )
            if candidates:
                break

    candidates.sort(key=lambda value: (float(value["score"]), float(value["titleRatio"])), reverse=True)
    if not candidates:
        result = {
            "workId": work_id,
            "title": title,
            "status": "UNMATCHED",
            "confidence": None,
            "mediaType": None,
            "tmdbId": None,
            "candidateCount": 0,
        }
        _upsert_link(connection, work_id, result)
        connection.commit()
        return result

    top = candidates[0]
    second_score = float(candidates[1]["score"]) if len(candidates) > 1 else 0.0
    margin = float(top["score"]) - second_score
    auto_match = (
        float(top["score"]) >= AUTO_MATCH_THRESHOLD
        and float(top["titleRatio"]) >= 0.95
        and margin >= AUTO_MATCH_MARGIN
    )
    status = "MATCHED" if auto_match else ("REVIEW" if float(top["score"]) >= REVIEW_THRESHOLD else "CANDIDATE")
    item = dict(top["item"])
    media_type = str(top["mediaType"])
    matched_year = _candidate_year(item, media_type)
    payload = item
    if status == "MATCHED":
        payload = _details(connection, client, media_type, int(top["tmdbId"])) or item

    result = {
        "workId": work_id,
        "title": title,
        "status": status,
        "confidence": round(float(top["score"]), 4),
        "mediaType": media_type,
        "tmdbId": int(top["tmdbId"]),
        "matchedTitle": _display_title(payload, media_type) or _display_title(item, media_type),
        "matchedYear": str(_candidate_year(payload, media_type) or matched_year or "") or None,
        "posterPath": payload.get("poster_path") or item.get("poster_path"),
        "backdropPath": payload.get("backdrop_path") or item.get("backdrop_path"),
        "overview": str(payload.get("overview") or item.get("overview") or "").strip() or None,
        "candidateCount": len(candidates),
        "margin": round(margin, 4),
    }
    _upsert_link(connection, work_id, result)
    connection.commit()
    return result


def audit_tmdb_library(
    database_path: Path | str,
    access_token: str,
    output_dir: Path | str,
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    client: TmdbClient | None = None,
) -> dict[str, Any]:
    token = str(access_token or "").strip()
    if not token:
        raise ValueError("TMDb API Read Access Token is required")
    tmdb = client or TmdbClient(token)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    with connect(database_path) as connection:
        initialize_database(connection)
        works = connection.execute(
            """
            SELECT id,external_work_no,category,official_title,source_title,year_or_period,media_file_count
            FROM works ORDER BY external_work_no,id
            """
        ).fetchall()
        total = len(works)
        rows: list[dict[str, Any]] = []
        counts = {"MATCHED": 0, "REVIEW": 0, "CANDIDATE": 0, "UNMATCHED": 0, "ERROR": 0}

        for index, work in enumerate(works, start=1):
            try:
                result = match_work(connection, tmdb, work)
            except TmdbError as exc:
                result = {
                    "workId": int(work["id"]),
                    "title": str(work["official_title"]),
                    "status": "ERROR",
                    "confidence": None,
                    "mediaType": None,
                    "tmdbId": None,
                    "candidateCount": 0,
                    "error": str(exc),
                }
            status = str(result.get("status") or "ERROR")
            counts[status] = counts.get(status, 0) + 1
            record = {
                "externalWorkNo": int(work["external_work_no"]),
                "workId": int(work["id"]),
                "category": str(work["category"]),
                "title": str(work["official_title"]),
                "yearOrPeriod": work["year_or_period"],
                **result,
            }
            rows.append(record)
            if progress_callback is not None:
                progress_callback(
                    {
                        "current": index,
                        "total": total,
                        "matched": counts.get("MATCHED", 0),
                        "review": counts.get("REVIEW", 0),
                        "candidate": counts.get("CANDIDATE", 0),
                        "unmatched": counts.get("UNMATCHED", 0),
                        "errors": counts.get("ERROR", 0),
                        "currentItem": str(work["official_title"]),
                    }
                )

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = output / f"tmdb-match-audit-{stamp}.json"
    csv_path = output / f"tmdb-match-audit-{stamp}.csv"
    summary = {
        "total": len(rows),
        "matched": counts.get("MATCHED", 0),
        "review": counts.get("REVIEW", 0),
        "candidate": counts.get("CANDIDATE", 0),
        "unmatched": counts.get("UNMATCHED", 0),
        "errors": counts.get("ERROR", 0),
        "autoMatchThreshold": AUTO_MATCH_THRESHOLD,
        "autoMatchMargin": AUTO_MATCH_MARGIN,
    }
    json_path.write_text(
        json.dumps({"generatedAt": now_iso(), "summary": summary, "items": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    fields = [
        "externalWorkNo", "workId", "category", "title", "yearOrPeriod", "status", "confidence",
        "mediaType", "tmdbId", "matchedTitle", "matchedYear", "candidateCount", "margin", "posterPath",
        "backdropPath", "error",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return {"summary": summary, "jsonReport": str(json_path), "csvReport": str(csv_path)}
