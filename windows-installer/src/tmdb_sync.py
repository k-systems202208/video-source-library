from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Iterable

from database import connect, now_iso
from tmdb_cache import get_cached_json, put_cached_json
from tmdb_client import TmdbClient
from tmdb_images import cached_image_path, download_tmdb_image

_MATCHED = "MATCHED"
_REVIEW = "REVIEW"
_UNMATCHED = "UNMATCHED"
_MATCHER_VERSION = 2
_MATCHER_VERSION_CACHE_KEY = "tmdb:matcher-version"


@dataclass(frozen=True)
class Candidate:
    media_type: str
    tmdb_id: int
    title: str
    year: str
    poster_path: str | None
    backdrop_path: str | None
    overview: str
    title_similarity: float
    year_similarity: float
    confidence: float


def _normalize_title(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return "".join(ch for ch in text if ch.isalnum())


def _extract_year(value: str | None) -> int | None:
    match = re.search(r"(?:19|20)\d{2}", str(value or ""))
    return int(match.group(0)) if match else None


def _candidate_year(payload: dict[str, Any], media_type: str) -> int | None:
    field = "release_date" if media_type == "movie" else "first_air_date"
    return _extract_year(str(payload.get(field) or ""))


def _candidate_titles(payload: dict[str, Any], media_type: str) -> list[str]:
    names = (
        [payload.get("title"), payload.get("original_title")]
        if media_type == "movie"
        else [payload.get("name"), payload.get("original_name")]
    )
    return [str(value).strip() for value in names if str(value or "").strip()]


def _media_types_for(category: str | None) -> tuple[str, ...]:
    text = str(category or "")
    has_movie = "映画" in text
    has_tv = "ドラマ" in text or "テレビ" in text
    if has_movie and has_tv:
        return ("movie", "tv")
    if has_movie:
        return ("movie",)
    if has_tv:
        return ("tv",)
    return ("movie", "tv")


def _stored_matcher_version(connection: sqlite3.Connection) -> int:
    payload = get_cached_json(connection, _MATCHER_VERSION_CACHE_KEY)
    if not isinstance(payload, dict):
        return 0
    try:
        return int(payload.get("version") or 0)
    except (TypeError, ValueError):
        return 0


def _store_matcher_version(connection: sqlite3.Connection) -> None:
    put_cached_json(
        connection,
        _MATCHER_VERSION_CACHE_KEY,
        {"version": _MATCHER_VERSION},
        fetched_at=now_iso(),
        expires_at=None,
    )


def _year_similarity(local_year: int | None, candidate_year: int | None) -> float:
    if local_year is None or candidate_year is None:
        return 0.5
    difference = abs(local_year - candidate_year)
    if difference == 0:
        return 1.0
    if difference == 1:
        return 0.65
    return 0.0


def _candidate_from_result(
    work: sqlite3.Row | dict[str, Any],
    media_type: str,
    payload: dict[str, Any],
) -> Candidate | None:
    try:
        tmdb_id = int(payload.get("id"))
    except (TypeError, ValueError):
        return None
    local_titles = [
        str(work["official_title"] or "").strip(),
        str(work["source_title"] or "").strip(),
    ]
    local_titles = [value for value in local_titles if value]
    candidate_titles = _candidate_titles(payload, media_type)
    if not local_titles or not candidate_titles:
        return None
    similarity = max(
        SequenceMatcher(None, _normalize_title(local), _normalize_title(remote)).ratio()
        for local in local_titles
        for remote in candidate_titles
        if _normalize_title(local) and _normalize_title(remote)
    )
    local_year = _extract_year(str(work["year_or_period"] or ""))
    remote_year = _candidate_year(payload, media_type)
    year_score = _year_similarity(local_year, remote_year)
    image_bonus = 1.0 if payload.get("poster_path") else 0.0
    confidence = min(1.0, 0.80 * similarity + 0.15 * year_score + 0.05 * image_bonus)
    return Candidate(
        media_type=media_type,
        tmdb_id=tmdb_id,
        title=candidate_titles[0],
        year=str(remote_year or ""),
        poster_path=str(payload.get("poster_path")) if payload.get("poster_path") else None,
        backdrop_path=str(payload.get("backdrop_path")) if payload.get("backdrop_path") else None,
        overview=str(payload.get("overview") or "").strip(),
        title_similarity=similarity,
        year_similarity=year_score,
        confidence=confidence,
    )


def choose_candidate(
    work: sqlite3.Row | dict[str, Any],
    candidates: Iterable[Candidate],
) -> tuple[str, Candidate | None, str]:
    ranked = sorted(candidates, key=lambda item: (item.confidence, item.title_similarity), reverse=True)
    if not ranked:
        return _UNMATCHED, None, "NO_CANDIDATE"
    top = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    margin = top.confidence - second.confidence if second else 1.0
    local_year = _extract_year(str(work["year_or_period"] or ""))
    exact_year = top.year_similarity >= 0.65 if local_year is not None else False
    title_is_strong = top.title_similarity >= 0.96
    unambiguous = second is None or margin >= 0.08
    exact_title_without_year = local_year is None and top.title_similarity >= 0.995 and (second is None or margin >= 0.18)
    if top.confidence >= 0.92 and title_is_strong and unambiguous and (exact_year or exact_title_without_year):
        return _MATCHED, top, "AUTO_HIGH_CONFIDENCE"
    if top.confidence >= 0.70:
        return _REVIEW, top, "REVIEW_REQUIRED"
    return _UNMATCHED, top, "LOW_CONFIDENCE"


def _search_cache_key(media_type: str, query: str, year: int | None, language: str) -> str:
    raw = json.dumps(
        {"type": media_type, "query": query, "year": year, "language": language},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "tmdb:search:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cached_search(
    connection: sqlite3.Connection,
    client: TmdbClient,
    media_type: str,
    query: str,
    year: int | None,
    *,
    language: str = "ja-JP",
) -> dict[str, Any]:
    key = _search_cache_key(media_type, query, year, language)
    cached = get_cached_json(connection, key)
    if isinstance(cached, dict):
        return cached
    if media_type == "movie":
        value = client.search_movie(query, year=year, language=language)
    else:
        value = client.search_tv(query, first_air_date_year=year, language=language)
    fetched = now_iso()
    expiry = (datetime.fromisoformat(fetched) + timedelta(days=30)).isoformat(timespec="seconds")
    put_cached_json(connection, key, value, fetched_at=fetched, expires_at=expiry)
    connection.commit()
    return value


def _collect_candidates(
    connection: sqlite3.Connection,
    client: TmdbClient,
    work: sqlite3.Row,
) -> list[Candidate]:
    queries = [str(work["official_title"] or "").strip()]
    source = str(work["source_title"] or "").strip()
    if source and _normalize_title(source) != _normalize_title(queries[0]):
        queries.append(source)
    year = _extract_year(str(work["year_or_period"] or ""))
    found: dict[tuple[str, int], Candidate] = {}
    for media_type in _media_types_for(str(work["category"] or "")):
        for query_index, query in enumerate(queries):
            if not query:
                continue
            payload = _cached_search(connection, client, media_type, query, year)
            results = payload.get("results") if isinstance(payload, dict) else None
            if isinstance(results, list):
                for item in results[:20]:
                    if not isinstance(item, dict):
                        continue
                    candidate = _candidate_from_result(work, media_type, item)
                    if candidate is None:
                        continue
                    key = (candidate.media_type, candidate.tmdb_id)
                    previous = found.get(key)
                    if previous is None or candidate.confidence > previous.confidence:
                        found[key] = candidate
            if query_index == 0 and found and max(item.title_similarity for item in found.values()) >= 0.90:
                break
    return list(found.values())


def _upsert_link(
    connection: sqlite3.Connection,
    work_id: int,
    status: str,
    candidate: Candidate | None,
) -> None:
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
            int(work_id),
            candidate.media_type if candidate else None,
            candidate.tmdb_id if candidate else None,
            status,
            round(candidate.confidence, 6) if candidate else None,
            candidate.title if candidate else None,
            candidate.year if candidate else None,
            candidate.poster_path if candidate else None,
            candidate.backdrop_path if candidate else None,
            candidate.overview if candidate else None,
            stamp,
            stamp,
            stamp,
        ),
    )


def _cache_candidate_images(
    work_id: int,
    candidate: Candidate,
    image_root: Path,
    *,
    image_downloader: Callable[..., Path],
) -> tuple[bool, bool]:
    poster_cached = False
    backdrop_cached = False
    if candidate.poster_path:
        target = cached_image_path(image_root, work_id, "poster", candidate.poster_path)
        if not target.is_file():
            image_downloader(candidate.poster_path, target, size="w500")
        poster_cached = target.is_file()
    if candidate.backdrop_path:
        target = cached_image_path(image_root, work_id, "backdrop", candidate.backdrop_path)
        if not target.is_file():
            image_downloader(candidate.backdrop_path, target, size="w1280")
        backdrop_cached = target.is_file()
    return poster_cached, backdrop_cached


def _write_report(report_dir: Path, rows: list[dict[str, Any]], summary: dict[str, Any]) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = report_dir / f"tmdb-match-audit-{stamp}.json"
    csv_path = report_dir / f"tmdb-match-audit-{stamp}.csv"
    json_path.write_text(
        json.dumps({"summary": summary, "items": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    fields = [
        "workId", "title", "category", "yearOrPeriod", "status", "confidence", "mediaType",
        "tmdbId", "matchedTitle", "matchedYear", "reason", "posterCached", "backdropCached",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fields})
    return json_path, csv_path


def sync_tmdb_library(
    database_path: Path | str,
    image_root: Path | str,
    report_dir: Path | str,
    access_token: str,
    *,
    client: TmdbClient | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    image_downloader: Callable[..., Path] = download_tmdb_image,
) -> dict[str, Any]:
    token = str(access_token or "").strip()
    if not token:
        raise ValueError("TMDb API Read Access Token is not configured")
    tmdb = client or TmdbClient(token)
    image_root_path = Path(image_root)
    rows: list[dict[str, Any]] = []
    with connect(database_path) as connection:
        works = connection.execute(
            "SELECT id,category,year_or_period,source_title,official_title FROM works ORDER BY external_work_no"
        ).fetchall()
        total = len(works)
        force_reassess = _stored_matcher_version(connection) < _MATCHER_VERSION
        for index, work in enumerate(works, start=1):
            existing = connection.execute(
                "SELECT * FROM tmdb_work_links WHERE work_id=?",
                (int(work["id"]),),
            ).fetchone()
            candidate: Candidate | None = None
            reason = ""
            status = _UNMATCHED
            if (
                not force_reassess
                and existing is not None
                and existing["match_status"] == _MATCHED
                and existing["tmdb_id"]
            ):
                candidate = Candidate(
                    media_type=str(existing["media_type"]),
                    tmdb_id=int(existing["tmdb_id"]),
                    title=str(existing["matched_title"] or work["official_title"]),
                    year=str(existing["matched_year"] or ""),
                    poster_path=str(existing["poster_path"]) if existing["poster_path"] else None,
                    backdrop_path=str(existing["backdrop_path"]) if existing["backdrop_path"] else None,
                    overview=str(existing["overview"] or ""),
                    title_similarity=1.0,
                    year_similarity=1.0,
                    confidence=float(existing["confidence"] or 1.0),
                )
                status = _MATCHED
                reason = "EXISTING_MATCH"
            else:
                candidates = _collect_candidates(connection, tmdb, work)
                status, candidate, reason = choose_candidate(work, candidates)
                _upsert_link(connection, int(work["id"]), status, candidate)
                connection.commit()
            poster_cached = False
            backdrop_cached = False
            if status == _MATCHED and candidate is not None:
                try:
                    poster_cached, backdrop_cached = _cache_candidate_images(
                        int(work["id"]), candidate, image_root_path, image_downloader=image_downloader
                    )
                except Exception:
                    poster_cached = bool(candidate.poster_path and cached_image_path(image_root_path, int(work["id"]), "poster", candidate.poster_path).is_file())
                    backdrop_cached = bool(candidate.backdrop_path and cached_image_path(image_root_path, int(work["id"]), "backdrop", candidate.backdrop_path).is_file())
            row = {
                "workId": int(work["id"]),
                "title": str(work["official_title"]),
                "category": str(work["category"]),
                "yearOrPeriod": str(work["year_or_period"] or ""),
                "status": status,
                "confidence": round(candidate.confidence, 4) if candidate else "",
                "mediaType": candidate.media_type if candidate else "",
                "tmdbId": candidate.tmdb_id if candidate else "",
                "matchedTitle": candidate.title if candidate else "",
                "matchedYear": candidate.year if candidate else "",
                "reason": reason,
                "posterCached": poster_cached,
                "backdropCached": backdrop_cached,
            }
            rows.append(row)
            if progress_callback is not None:
                progress_callback(
                    {
                        "current": index,
                        "total": total,
                        "matched": sum(1 for item in rows if item["status"] == _MATCHED),
                        "review": sum(1 for item in rows if item["status"] == _REVIEW),
                        "unmatched": sum(1 for item in rows if item["status"] == _UNMATCHED),
                        "currentItem": str(work["official_title"]),
                    }
                )
        _store_matcher_version(connection)
        connection.commit()
    summary = {
        "total": len(rows),
        "matched": sum(1 for item in rows if item["status"] == _MATCHED),
        "review": sum(1 for item in rows if item["status"] == _REVIEW),
        "unmatched": sum(1 for item in rows if item["status"] == _UNMATCHED),
        "posterCached": sum(1 for item in rows if item["posterCached"]),
        "backdropCached": sum(1 for item in rows if item["backdropCached"]),
    }
    json_path, csv_path = _write_report(Path(report_dir), rows, summary)
    return {"summary": summary, "jsonReport": str(json_path), "csvReport": str(csv_path)}
