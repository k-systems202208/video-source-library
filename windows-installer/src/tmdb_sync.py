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

from app_version import APP_VERSION
from database import connect, now_iso
from tmdb_cache import get_cached_json, put_cached_json
from tmdb_client import TmdbClient
from tmdb_images import cached_image_path, download_tmdb_image

_MATCHED = "MATCHED"
_REVIEW = "REVIEW"
_UNMATCHED = "UNMATCHED"
_MATCHER_VERSION = 7
_MATCHER_VERSION_CACHE_KEY = "tmdb:matcher-version"
_SEARCH_CACHE_VERSION = 3
_IMAGE_CACHE_REPAIR_VERSION = 3
_IMAGE_CACHE_REPAIR_KEY = "tmdb:image-cache-repair-version"

# 過去の誤候補画像が workId 名のローカルキャッシュとして残った作品。
# matcherの既存MATCHEDは維持し、TMDb詳細を同じIDから再取得して画像だけ取り直す。
# タイトルは _normalize_title() 後の値で保持し、全角/半角記号などの表記揺れに耐える。
_STALE_IMAGE_REPAIR_WORKS: set[tuple[str, str]] = {
    ("trick", "2000-2003"),
    ("pricelessあるわけねぇだろんなもん", "2012"),
    ("スマイル", "2009"),
    ("ビギナーズ", "2012"),
    ("プライド", "2004"),
}

# 440作品の実機監査で確認済みの「同一作品だがTMDb側の表記が異なる」名称。
# TMDb IDは固定せず、検索とタイトル類似度の補助にだけ使う。
_AUDITED_TITLE_ALIASES: dict[str, tuple[str, ...]] = {
    "liargame": ("ライアーゲーム",),
    "ライアーゲーム": ("LIAR GAME",),
    "bloodymonday": ("ブラッディ・マンデイ", "ブラッディマンデイ"),
    "ブラッディマンデイ": ("BLOODY MONDAY",),
    "trick": ("トリック",),
    "トリック": ("TRICK",),
    "goodluck": ("グッドラック", "グッドラック!!", "グッドラック！！"),
    "グッドラック": ("GOOD LUCK!!", "GOOD LUCK"),
}

# 2026-09-16の440作品実機監査で候補内容まで人手確認した確定シグネチャ。
# generic matcherの閾値は緩めず、ローカル作品名/期間とTMDb候補の種別・ID・開始年が
# すべて一致した場合だけ監査承認として確定する。
_AUDIT_APPROVED_MATCHES: dict[tuple[str, str], tuple[str, int, str]] = {
    ("進撃の巨人", ""): ("tv", 1429, "2013"),
    ("誰にも言えない", "1993"): ("tv", 36167, "1993"),
    ("こんな恋のはなし", "1997"): ("tv", 9327, "1997"),
    ("牙狼〈GARO〉", "2005-2006"): ("tv", 1941, "2005"),
    ("半分の月がのぼる空", "2006"): ("tv", 34746, "2006"),
    ("SUMMER NUDE", "2013"): ("tv", 64293, "2013"),
    ("夜行観覧車", "2013"): ("tv", 81864, "2013"),
    ("信長協奏曲", "2014"): ("tv", 62911, "2014"),
    ("仰げば尊し", "2016"): ("tv", 83474, "2016"),
}

# 1つのTMDb作品へ自動確定してはいけないローカル集約項目。
_AUDIT_AGGREGATE_WORKS: set[tuple[str, str]] = {
    ("男はつらいよ", "1969-2019"),
    ("仁義なき戦い", "1973-1974"),
    ("福岡恋愛白書", "2011-2016"),
    ("殺人分析班シリーズ", "2016-2019"),
}

# TMDbのシリーズ構造とローカル管理単位が一致しないため自動紐付けしない項目。
_AUDIT_SPECIAL_UNMATCHED: set[tuple[str, str]] = {
    ("3年B組金八先生 第6シリーズ", "2001"),
}


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


def _audited_aliases(value: str | None) -> tuple[str, ...]:
    return _AUDITED_TITLE_ALIASES.get(_normalize_title(value), ())


def _title_variants(value: str | None) -> set[str]:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    if not text:
        return set()
    raw_variants = {text}
    raw_variants.update(alias.casefold() for alias in _audited_aliases(text))

    without_brackets = re.sub(r"\s*[\(\[][^)\]]*[\)\]]\s*", " ", text).strip()
    if without_brackets:
        raw_variants.add(without_brackets)

    for part in re.split(r"[/／|｜〜～~:：]", text):
        part = part.strip(" -‐‑–—―_・.　")
        if part:
            raw_variants.add(part)

    for match in re.finditer(
        r"([a-z0-9&'! .]+)-([\u3040-\u30ff\u3400-\u9fff々・ー]+)-?",
        text,
        re.IGNORECASE,
    ):
        for part in match.groups():
            part = part.strip(" -‐‑–—―_・.　")
            if part:
                raw_variants.add(part)

    variants = {_normalize_title(item) for item in raw_variants}
    return {item for item in variants if item}


def _title_similarity(left: str | None, right: str | None) -> float:
    left_variants = _title_variants(left)
    right_variants = _title_variants(right)
    if not left_variants or not right_variants:
        return 0.0
    if left_variants & right_variants:
        return 1.0
    return max(
        SequenceMatcher(None, local, remote).ratio()
        for local in left_variants
        for remote in right_variants
    )


def _search_query_variants(value: str | None) -> list[str]:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        return []

    values: list[str] = [text]
    values.extend(_audited_aliases(text))

    without_brackets = re.sub(r"\s*[\(\[][^)\]]*[\)\]]\s*", " ", text).strip()
    if without_brackets and _normalize_title(without_brackets) != _normalize_title(text):
        values.append(without_brackets)

    punctuation_trimmed = re.sub(r"[!！?？]+$", "", text).strip()
    if punctuation_trimmed and punctuation_trimmed.casefold() != text.casefold():
        values.append(punctuation_trimmed)

    for part in re.split(r"[/／|｜〜～~:：]", text):
        part = part.strip(" -‐‑–—―_・.　")
        if part:
            values.append(part)

    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        key = unicodedata.normalize("NFKC", item).casefold().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _work_search_queries(work: sqlite3.Row | dict[str, Any]) -> list[str]:
    titles = [
        str(_work_value(work, "official_title", "") or "").strip(),
        str(_work_value(work, "source_title", "") or "").strip(),
    ]
    result: list[str] = []
    seen: set[str] = set()
    for title in titles:
        for query in _search_query_variants(title):
            key = unicodedata.normalize("NFKC", query).casefold().strip()
            if key and key not in seen:
                seen.add(key)
                result.append(query)
    return result


def _extract_years(value: str | None) -> tuple[int, ...]:
    years: list[int] = []
    for match in re.finditer(r"(?:19|20)\d{2}", str(value or "")):
        year = int(match.group(0))
        if year not in years:
            years.append(year)
    return tuple(years)


def _extract_year(value: str | None) -> int | None:
    years = _extract_years(value)
    return years[0] if years else None


def _is_multi_year_period(value: str | None) -> bool:
    years = _extract_years(value)
    return len(years) >= 2 and min(years) != max(years)


def _work_value(work: sqlite3.Row | dict[str, Any], key: str, default: Any = None) -> Any:
    if isinstance(work, sqlite3.Row):
        return work[key] if key in work.keys() else default
    return work.get(key, default)


def _work_audit_key(work: sqlite3.Row | dict[str, Any]) -> tuple[str, str]:
    return (
        str(_work_value(work, "official_title", "") or "").strip(),
        str(_work_value(work, "year_or_period", "") or "").strip(),
    )


def _requires_image_cache_repair(work: sqlite3.Row | dict[str, Any]) -> bool:
    period = str(_work_value(work, "year_or_period", "") or "").strip()
    titles = {
        _normalize_title(_work_value(work, "official_title", "")),
        _normalize_title(_work_value(work, "source_title", "")),
    }
    titles.discard("")
    return any((title, period) in _STALE_IMAGE_REPAIR_WORKS for title in titles)


def _audit_approved_candidate(
    work: sqlite3.Row | dict[str, Any],
    candidates: Iterable[Candidate],
) -> Candidate | None:
    expected = _AUDIT_APPROVED_MATCHES.get(_work_audit_key(work))
    if expected is None:
        return None
    media_type, tmdb_id, matched_year = expected
    for candidate in candidates:
        if (
            candidate.media_type == media_type
            and candidate.tmdb_id == tmdb_id
            and candidate.year == matched_year
        ):
            return candidate
    return None


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


def _media_type_hint(work: sqlite3.Row | dict[str, Any]) -> tuple[str | None, float]:
    media_types = _media_types_for(str(_work_value(work, "category", "") or ""))
    if len(media_types) == 1:
        return media_types[0], 0.20

    try:
        episode_count = int(_work_value(work, "episode_count", 0) or 0)
    except (TypeError, ValueError):
        episode_count = 0
    try:
        movie_content_count = int(_work_value(work, "movie_content_count", 0) or 0)
    except (TypeError, ValueError):
        movie_content_count = 0
    try:
        media_file_count = int(_work_value(work, "media_file_count", 0) or 0)
    except (TypeError, ValueError):
        media_file_count = 0

    if episode_count > 0 and episode_count > movie_content_count:
        return "tv", 0.16
    if movie_content_count > 0 and movie_content_count > episode_count:
        return "movie", 0.16

    period = str(_work_value(work, "year_or_period", "") or "")
    if media_file_count >= 3 and not _is_multi_year_period(period):
        return "tv", 0.10
    return None, 0.0


def _candidate_rank_score(work: sqlite3.Row | dict[str, Any], candidate: Candidate) -> float:
    preferred_type, bonus = _media_type_hint(work)
    return candidate.confidence + (bonus if candidate.media_type == preferred_type else 0.0)


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


def _stored_image_cache_repair_version(connection: sqlite3.Connection) -> int:
    payload = get_cached_json(connection, _IMAGE_CACHE_REPAIR_KEY)
    if not isinstance(payload, dict):
        return 0
    try:
        return int(payload.get("version") or 0)
    except (TypeError, ValueError):
        return 0


def _store_image_cache_repair_version(connection: sqlite3.Connection) -> None:
    put_cached_json(
        connection,
        _IMAGE_CACHE_REPAIR_KEY,
        {"version": _IMAGE_CACHE_REPAIR_VERSION},
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
        str(_work_value(work, "official_title", "") or "").strip(),
        str(_work_value(work, "source_title", "") or "").strip(),
    ]
    local_titles = [value for value in local_titles if value]
    candidate_titles = _candidate_titles(payload, media_type)
    if not local_titles or not candidate_titles:
        return None

    similarity = max(
        _title_similarity(local, remote)
        for local in local_titles
        for remote in candidate_titles
    )
    local_year = _extract_year(str(_work_value(work, "year_or_period", "") or ""))
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


def _refresh_matched_candidate_details(
    client: TmdbClient,
    candidate: Candidate,
    *,
    language: str = "ja-JP",
) -> Candidate:
    if candidate.media_type == "movie":
        payload = client.movie_details(candidate.tmdb_id, language=language)
    elif candidate.media_type == "tv":
        payload = client.tv_details(candidate.tmdb_id, language=language)
    else:
        raise ValueError("unsupported TMDb media type")

    try:
        detail_id = int(payload.get("id"))
    except (AttributeError, TypeError, ValueError):
        raise ValueError("TMDb detail payload has no valid id") from None
    if detail_id != candidate.tmdb_id:
        raise ValueError("TMDb detail id does not match existing link")

    titles = _candidate_titles(payload, candidate.media_type)
    detail_year = _candidate_year(payload, candidate.media_type)
    return Candidate(
        media_type=candidate.media_type,
        tmdb_id=candidate.tmdb_id,
        title=titles[0] if titles else candidate.title,
        year=str(detail_year or candidate.year),
        poster_path=str(payload.get("poster_path")) if payload.get("poster_path") else None,
        backdrop_path=str(payload.get("backdrop_path")) if payload.get("backdrop_path") else None,
        overview=str(payload.get("overview") or "").strip(),
        title_similarity=candidate.title_similarity,
        year_similarity=candidate.year_similarity,
        confidence=candidate.confidence,
    )


def choose_candidate(
    work: sqlite3.Row | dict[str, Any],
    candidates: Iterable[Candidate],
) -> tuple[str, Candidate | None, str]:
    ranked = sorted(
        candidates,
        key=lambda item: (_candidate_rank_score(work, item), item.confidence, item.title_similarity),
        reverse=True,
    )
    audit_key = _work_audit_key(work)

    if audit_key in _AUDIT_SPECIAL_UNMATCHED:
        return _UNMATCHED, ranked[0] if ranked else None, "AUDIT_SPECIAL_STRUCTURE"

    if audit_key in _AUDIT_AGGREGATE_WORKS:
        return _REVIEW, ranked[0] if ranked else None, "AUDIT_AGGREGATE_REVIEW"

    approved = _audit_approved_candidate(work, ranked)
    if approved is not None:
        return _MATCHED, approved, "AUDIT_APPROVED"

    if not ranked:
        return _UNMATCHED, None, "NO_CANDIDATE"

    top = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    top_rank = _candidate_rank_score(work, top)
    second_rank = _candidate_rank_score(work, second) if second else None
    margin = top_rank - second_rank if second_rank is not None else 1.0

    local_year = _extract_year(str(_work_value(work, "year_or_period", "") or ""))
    exact_year = top.year_similarity >= 0.65 if local_year is not None else False
    title_is_strong = top.title_similarity >= 0.96

    # v5: タイトル完全一致かつ開始年が完全一致し、2位が年またはタイトルで劣る場合は、
    # 従来の0.08より小さい0.05差でも十分な根拠とする。
    exact_title_year_advantage = bool(
        second is not None
        and top.title_similarity >= 0.995
        and top.year_similarity >= 1.0
        and (second.title_similarity < 0.995 or second.year_similarity < 1.0)
        and margin >= 0.05
    )
    unambiguous = second is None or margin >= 0.08 or exact_title_year_advantage

    exact_title_without_year = (
        local_year is None
        and top.title_similarity >= 0.995
        and (second is None or margin >= 0.18)
    )
    multi_year_movie = top.media_type == "movie" and _is_multi_year_period(
        str(_work_value(work, "year_or_period", "") or "")
    )
    preferred_type, media_bonus = _media_type_hint(work)
    media_context_selected = bool(
        preferred_type
        and media_bonus > 0
        and top.media_type == preferred_type
        and second is not None
        and second.media_type != top.media_type
        and margin >= 0.08
    )

    if (
        not multi_year_movie
        and top.confidence >= 0.92
        and title_is_strong
        and unambiguous
        and (exact_year or exact_title_without_year)
    ):
        if exact_title_year_advantage and not media_context_selected:
            return _MATCHED, top, "AUTO_EXACT_TITLE_YEAR"
        return _MATCHED, top, "AUTO_MEDIA_CONTEXT" if media_context_selected else "AUTO_HIGH_CONFIDENCE"

    if top.confidence >= 0.70:
        if multi_year_movie:
            return _REVIEW, top, "MULTI_YEAR_MOVIE_REVIEW"
        return _REVIEW, top, "REVIEW_REQUIRED"
    return _UNMATCHED, top, "LOW_CONFIDENCE"


def _search_cache_key(media_type: str, query: str, year: int | None, language: str) -> str:
    raw = json.dumps(
        {
            "cacheVersion": _SEARCH_CACHE_VERSION,
            "type": media_type,
            "query": query,
            "year": year,
            "language": language,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "tmdb:search:v3:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


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


def _add_search_results(
    found: dict[tuple[str, int], Candidate],
    work: sqlite3.Row | dict[str, Any],
    media_type: str,
    payload: dict[str, Any],
) -> None:
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return
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


def _strong_candidate_for_type(
    found: dict[tuple[str, int], Candidate],
    media_type: str,
) -> bool:
    candidates = [item for item in found.values() if item.media_type == media_type]
    return any(
        item.title_similarity >= 0.96 and item.year_similarity >= 0.65
        for item in candidates
    )


def _collect_candidates(
    connection: sqlite3.Connection,
    client: TmdbClient,
    work: sqlite3.Row,
) -> list[Candidate]:
    queries = _work_search_queries(work)
    year = _extract_year(str(work["year_or_period"] or ""))
    found: dict[tuple[str, int], Candidate] = {}

    for media_type in _media_types_for(str(work["category"] or "")):
        for query in queries:
            if not query:
                continue

            # まず従来どおり年指定。強候補が得られなければ同じクエリを年なしでも検索する。
            payload = _cached_search(connection, client, media_type, query, year)
            _add_search_results(found, work, media_type, payload)
            if _strong_candidate_for_type(found, media_type):
                break

            if year is not None:
                payload = _cached_search(connection, client, media_type, query, None)
                _add_search_results(found, work, media_type, payload)
                if _strong_candidate_for_type(found, media_type):
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


def _image_refresh_flags(
    existing: sqlite3.Row | dict[str, Any] | None,
    status: str,
    candidate: Candidate | None,
) -> tuple[bool, bool]:
    if status != _MATCHED or candidate is None or existing is None:
        return False, False
    old_status = str(existing["match_status"] if isinstance(existing, sqlite3.Row) else existing.get("match_status") or "")
    old_media_type = str(existing["media_type"] if isinstance(existing, sqlite3.Row) else existing.get("media_type") or "")
    old_tmdb_id = existing["tmdb_id"] if isinstance(existing, sqlite3.Row) else existing.get("tmdb_id")
    old_poster = existing["poster_path"] if isinstance(existing, sqlite3.Row) else existing.get("poster_path")
    old_backdrop = existing["backdrop_path"] if isinstance(existing, sqlite3.Row) else existing.get("backdrop_path")
    identity_changed = (
        old_status != _MATCHED
        or old_media_type != candidate.media_type
        or int(old_tmdb_id or 0) != candidate.tmdb_id
    )
    return (
        identity_changed or str(old_poster or "") != str(candidate.poster_path or ""),
        identity_changed or str(old_backdrop or "") != str(candidate.backdrop_path or ""),
    )


def _cache_candidate_images(
    work_id: int,
    candidate: Candidate,
    image_root: Path,
    *,
    image_downloader: Callable[..., Path],
    force_poster_refresh: bool = False,
    force_backdrop_refresh: bool = False,
) -> tuple[bool, bool]:
    poster_cached = False
    backdrop_cached = False
    if candidate.poster_path:
        target = cached_image_path(image_root, work_id, "poster", candidate.poster_path)
        if force_poster_refresh and target.is_file():
            target.unlink()
        if not target.is_file():
            image_downloader(candidate.poster_path, target, size="w500")
        poster_cached = target.is_file()
    if candidate.backdrop_path:
        target = cached_image_path(image_root, work_id, "backdrop", candidate.backdrop_path)
        if force_backdrop_refresh and target.is_file():
            target.unlink()
        if not target.is_file():
            image_downloader(candidate.backdrop_path, target, size="w1280")
        backdrop_cached = target.is_file()
    return poster_cached, backdrop_cached


def _write_report(
    report_dir: Path,
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = report_dir / f"tmdb-match-audit-{stamp}.json"
    csv_path = report_dir / f"tmdb-match-audit-{stamp}.csv"
    json_path.write_text(
        json.dumps({"summary": summary, "items": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    fields = [
        "appVersion",
        "matcherVersion",
        "workId",
        "title",
        "category",
        "yearOrPeriod",
        "status",
        "confidence",
        "mediaType",
        "tmdbId",
        "matchedTitle",
        "matchedYear",
        "reason",
        "posterCached",
        "backdropCached",
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
            """
            SELECT
                w.id,w.category,w.year_or_period,w.source_title,w.official_title,
                w.media_file_count,w.subfolder_count,
                (SELECT COUNT(*) FROM videos v WHERE v.work_id=w.id AND v.content_type='EPISODE') AS episode_count,
                (SELECT COUNT(*) FROM videos v WHERE v.work_id=w.id AND v.content_type='MOVIE') AS movie_content_count
            FROM works w
            ORDER BY w.external_work_no
            """
        ).fetchall()

        total = len(works)
        stored_version = _stored_matcher_version(connection)
        image_cache_repair_version = _stored_image_cache_repair_version(connection)
        legacy_image_repair = image_cache_repair_version < _IMAGE_CACHE_REPAIR_VERSION

        # v6実機監査でMATCHED 426件を確認済み。v7は監査承認と特殊項目の整理なので、
        # v4以降のMATCHEDは保持し、REVIEW/UNMATCHEDだけを再評価する。
        # v3以前は既知の旧誤マッチを含むため従来どおり再評価する。
        force_reassess_matched = stored_version < 4

        for index, work in enumerate(works, start=1):
            existing = connection.execute(
                "SELECT * FROM tmdb_work_links WHERE work_id=?",
                (int(work["id"]),),
            ).fetchone()

            candidate: Candidate | None = None
            reason = ""
            status = _UNMATCHED

            if (
                not force_reassess_matched
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
                if legacy_image_repair and _requires_image_cache_repair(work):
                    candidate = _refresh_matched_candidate_details(tmdb, candidate)
                    _upsert_link(connection, int(work["id"]), status, candidate)
                    connection.commit()
                    reason = "EXISTING_MATCH_METADATA_REFRESH"
            else:
                candidates = _collect_candidates(connection, tmdb, work)
                status, candidate, reason = choose_candidate(work, candidates)
                _upsert_link(connection, int(work["id"]), status, candidate)
                connection.commit()

            poster_cached = False
            backdrop_cached = False
            if status == _MATCHED and candidate is not None:
                force_poster_refresh, force_backdrop_refresh = _image_refresh_flags(existing, status, candidate)
                if legacy_image_repair and _requires_image_cache_repair(work):
                    force_poster_refresh = True
                    force_backdrop_refresh = True
                try:
                    poster_cached, backdrop_cached = _cache_candidate_images(
                        int(work["id"]),
                        candidate,
                        image_root_path,
                        image_downloader=image_downloader,
                        force_poster_refresh=force_poster_refresh,
                        force_backdrop_refresh=force_backdrop_refresh,
                    )
                except Exception:
                    poster_cached = bool(
                        candidate.poster_path
                        and cached_image_path(
                            image_root_path,
                            int(work["id"]),
                            "poster",
                            candidate.poster_path,
                        ).is_file()
                    )
                    backdrop_cached = bool(
                        candidate.backdrop_path
                        and cached_image_path(
                            image_root_path,
                            int(work["id"]),
                            "backdrop",
                            candidate.backdrop_path,
                        ).is_file()
                    )

            row = {
                "appVersion": APP_VERSION,
                "matcherVersion": _MATCHER_VERSION,
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
        _store_image_cache_repair_version(connection)
        connection.commit()

    summary = {
        "appVersion": APP_VERSION,
        "matcherVersion": _MATCHER_VERSION,
        "total": len(rows),
        "matched": sum(1 for item in rows if item["status"] == _MATCHED),
        "review": sum(1 for item in rows if item["status"] == _REVIEW),
        "unmatched": sum(1 for item in rows if item["status"] == _UNMATCHED),
        "posterCached": sum(1 for item in rows if item["posterCached"]),
        "backdropCached": sum(1 for item in rows if item["backdropCached"]),
    }
    json_path, csv_path = _write_report(Path(report_dir), rows, summary)
    return {
        "summary": summary,
        "jsonReport": str(json_path),
        "csvReport": str(csv_path),
    }
