from __future__ import annotations

import csv
import io
import json
import re
from difflib import SequenceMatcher
from pathlib import PurePosixPath
from typing import Any


def _path(value: str) -> PurePosixPath:
    return PurePosixPath(str(value or "").replace("\\", "/"))


def _norm_text(value: str) -> str:
    text = str(value or "").casefold()
    return re.sub(r"[^0-9a-z\u3040-\u30ff\u3400-\u9fff]+", "", text)


def _stem(value: str) -> str:
    return _path(value).stem


def _parent(value: str) -> str:
    parent = str(_path(value).parent)
    return "" if parent == "." else parent


def _basename_similarity(a: str, b: str) -> float:
    aa = _norm_text(_stem(a))
    bb = _norm_text(_stem(b))
    if not aa or not bb:
        return 0.0
    if aa == bb:
        return 1.0
    return SequenceMatcher(None, aa, bb).ratio()


def _parent_similarity(a: str, b: str) -> float:
    aa = _norm_text(_parent(a))
    bb = _norm_text(_parent(b))
    if not aa or not bb:
        return 0.0
    if aa == bb:
        return 1.0
    return SequenceMatcher(None, aa, bb).ratio()


def _confidence(score: int) -> str:
    if score >= 90:
        return "HIGH"
    if score >= 70:
        return "MEDIUM"
    return "LOW"


def _file_candidate_score(missing: dict[str, Any], new_file: dict[str, Any]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    m_size = missing.get("fileSize")
    n_size = new_file.get("fileSize")
    if m_size is not None and n_size is not None and int(m_size) == int(n_size):
        score += 55
        reasons.append("SIZE_EXACT")
    elif m_size and n_size:
        larger = max(int(m_size), int(n_size))
        diff_ratio = abs(int(m_size) - int(n_size)) / larger if larger else 0
        if diff_ratio <= 0.001:
            score += 35
            reasons.append("SIZE_NEAR")

    m_ext = str(missing.get("extension") or "").casefold().lstrip(".")
    n_ext = str(new_file.get("extension") or "").casefold().lstrip(".")
    if m_ext and n_ext and m_ext == n_ext:
        score += 10
        reasons.append("EXTENSION")

    stem_ratio = _basename_similarity(str(missing.get("relativePath") or ""), str(new_file.get("relativePath") or ""))
    if stem_ratio == 1.0:
        score += 35
        reasons.append("STEM_EXACT")
    elif stem_ratio >= 0.92:
        score += 28
        reasons.append("STEM_VERY_CLOSE")
    elif stem_ratio >= 0.82:
        score += 20
        reasons.append("STEM_CLOSE")
    elif stem_ratio >= 0.70:
        score += 10
        reasons.append("STEM_SIMILAR")

    parent_ratio = _parent_similarity(str(missing.get("relativePath") or ""), str(new_file.get("relativePath") or ""))
    if parent_ratio == 1.0:
        score += 15
        reasons.append("PARENT_EXACT")
    elif parent_ratio >= 0.85:
        score += 10
        reasons.append("PARENT_CLOSE")
    elif parent_ratio >= 0.65:
        score += 5
        reasons.append("PARENT_SIMILAR")

    return min(score, 100), reasons


def _subtitle_candidate_score(subtitle_path: str, video_path: str) -> tuple[int, list[str]]:
    sub = _path(subtitle_path)
    vid = _path(video_path)
    reasons: list[str] = []
    score = 0

    if str(sub.parent).casefold() == str(vid.parent).casefold():
        score += 35
        reasons.append("SAME_FOLDER")
    else:
        parent_ratio = _parent_similarity(subtitle_path, video_path)
        if parent_ratio >= 0.90:
            score += 20
            reasons.append("FOLDER_VERY_CLOSE")
        elif parent_ratio >= 0.75:
            score += 10
            reasons.append("FOLDER_CLOSE")

    sub_stem = sub.stem.casefold()
    vid_stem = vid.stem.casefold()
    if sub_stem == vid_stem:
        score += 60
        reasons.append("STEM_EXACT")
    elif sub_stem.startswith(vid_stem + ".") or sub_stem.startswith(vid_stem + " ") or sub_stem.startswith(vid_stem + "_"):
        score += 50
        reasons.append("VIDEO_STEM_PREFIX")
    else:
        ratio = _basename_similarity(subtitle_path, video_path)
        if ratio >= 0.95:
            score += 45
            reasons.append("STEM_VERY_CLOSE")
        elif ratio >= 0.85:
            score += 35
            reasons.append("STEM_CLOSE")
        elif ratio >= 0.72:
            score += 20
            reasons.append("STEM_SIMILAR")

    return min(score, 100), reasons


def _latest_successful_run_id(connection) -> int | None:
    row = connection.execute(
        "SELECT id FROM scan_runs WHERE status='SUCCESS' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return int(row["id"]) if row else None


def _scan_summary(connection, run_id: int) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT id, started_at, completed_at, status, files_found, files_matched,
               files_missing, files_new, subtitles_found, subtitles_matched,
               subtitles_unmatched, probe_errors, errors, duration_ms
        FROM scan_runs WHERE id=?
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        raise LookupError("SCAN_RUN_NOT_FOUND")
    return {
        "runId": int(row["id"]),
        "startedAt": row["started_at"],
        "completedAt": row["completed_at"],
        "status": row["status"],
        "filesFound": int(row["files_found"]),
        "filesMatched": int(row["files_matched"]),
        "filesMissing": int(row["files_missing"]),
        "filesNew": int(row["files_new"]),
        "subtitlesFound": int(row["subtitles_found"]),
        "subtitlesMatched": int(row["subtitles_matched"]),
        "subtitlesUnmatched": int(row["subtitles_unmatched"]),
        "probeErrors": int(row["probe_errors"]),
        "errors": int(row["errors"]),
        "durationMs": row["duration_ms"],
    }


def scan_diagnostics(connection, *, run_id: int | None = None, candidate_limit: int = 3) -> dict[str, Any]:
    actual_run_id = run_id if run_id is not None else _latest_successful_run_id(connection)
    if actual_run_id is None:
        return {
            "scan": None,
            "summary": {"missing": 0, "newFiles": 0, "unmatchedSubtitles": 0, "errors": 0},
            "missing": [],
            "newFiles": [],
            "unmatchedSubtitles": [],
            "errors": [],
        }

    summary = _scan_summary(connection, actual_run_id)

    missing_rows = connection.execute(
        """
        SELECT vf.id AS video_file_id, vf.video_id, vf.relative_path, vf.extension,
               vf.file_size, vf.modified_time_ns,
               v.external_file_no, v.episode_or_type, v.episode_title,
               w.id AS work_id, w.official_title AS work_title
        FROM video_files vf
        JOIN videos v ON v.id=vf.video_id
        JOIN works w ON w.id=v.work_id
        WHERE vf.scan_status='MISSING'
        ORDER BY w.official_title, v.episode_sort_key, vf.relative_path
        """
    ).fetchall()
    missing = [
        {
            "videoFileId": int(row["video_file_id"]),
            "videoId": int(row["video_id"]),
            "externalFileNo": int(row["external_file_no"]),
            "workId": int(row["work_id"]),
            "workTitle": row["work_title"],
            "episodeOrType": row["episode_or_type"],
            "episodeTitle": row["episode_title"],
            "relativePath": row["relative_path"],
            "extension": row["extension"],
            "fileSize": row["file_size"],
            "modifiedTimeNs": row["modified_time_ns"],
            "candidates": [],
        }
        for row in missing_rows
    ]

    discovery_rows = connection.execute(
        """
        SELECT id, relative_path, extension, file_size, modified_time_ns, status
        FROM scan_discoveries
        WHERE scan_run_id=? AND status='NEW_FILE'
        ORDER BY relative_path
        """,
        (actual_run_id,),
    ).fetchall()
    new_files = [
        {
            "discoveryId": int(row["id"]),
            "relativePath": row["relative_path"],
            "extension": row["extension"],
            "fileSize": row["file_size"],
            "modifiedTimeNs": row["modified_time_ns"],
            "status": row["status"],
        }
        for row in discovery_rows
    ]

    for item in missing:
        scored: list[dict[str, Any]] = []
        for candidate in new_files:
            score, reasons = _file_candidate_score(item, candidate)
            if score < 45:
                continue
            scored.append(
                {
                    "discoveryId": candidate["discoveryId"],
                    "relativePath": candidate["relativePath"],
                    "fileSize": candidate["fileSize"],
                    "extension": candidate["extension"],
                    "score": score,
                    "confidence": _confidence(score),
                    "reasons": reasons,
                }
            )
        scored.sort(key=lambda value: (-int(value["score"]), str(value["relativePath"]).casefold()))
        item["candidates"] = scored[: max(1, candidate_limit)]

    video_rows = connection.execute(
        """
        SELECT vf.video_id, vf.relative_path, vf.extension, vf.is_available,
               v.episode_or_type, v.episode_title, w.official_title AS work_title
        FROM video_files vf
        JOIN videos v ON v.id=vf.video_id
        JOIN works w ON w.id=v.work_id
        ORDER BY vf.relative_path
        """
    ).fetchall()
    videos = [
        {
            "videoId": int(row["video_id"]),
            "relativePath": row["relative_path"],
            "extension": row["extension"],
            "available": bool(row["is_available"]),
            "episodeOrType": row["episode_or_type"],
            "episodeTitle": row["episode_title"],
            "workTitle": row["work_title"],
        }
        for row in video_rows
    ]
    videos_by_parent: dict[str, list[dict[str, Any]]] = {}
    for video in videos:
        videos_by_parent.setdefault(str(_path(video["relativePath"]).parent).casefold(), []).append(video)

    subtitle_rows = connection.execute(
        """
        SELECT id, relative_path, extension, language, match_method, file_size
        FROM subtitles
        WHERE is_available=1 AND video_id IS NULL
        ORDER BY relative_path
        """
    ).fetchall()
    unmatched_subtitles: list[dict[str, Any]] = []
    for row in subtitle_rows:
        relative_path = str(row["relative_path"])
        same_parent = videos_by_parent.get(str(_path(relative_path).parent).casefold(), [])
        pool = same_parent if same_parent else videos
        scored: list[dict[str, Any]] = []
        for video in pool:
            score, reasons = _subtitle_candidate_score(relative_path, str(video["relativePath"]))
            if score < 55:
                continue
            scored.append(
                {
                    "videoId": video["videoId"],
                    "relativePath": video["relativePath"],
                    "workTitle": video["workTitle"],
                    "episodeOrType": video["episodeOrType"],
                    "episodeTitle": video["episodeTitle"],
                    "available": video["available"],
                    "score": score,
                    "confidence": _confidence(score),
                    "reasons": reasons,
                }
            )
        scored.sort(key=lambda value: (-int(value["score"]), str(value["relativePath"]).casefold()))
        unmatched_subtitles.append(
            {
                "subtitleId": int(row["id"]),
                "relativePath": relative_path,
                "extension": row["extension"],
                "language": row["language"],
                "matchMethod": row["match_method"],
                "fileSize": row["file_size"],
                "candidates": scored[: max(1, candidate_limit)],
            }
        )

    error_rows = connection.execute(
        """
        SELECT id, relative_path, error_type, message, created_at
        FROM scan_errors
        WHERE scan_run_id=?
        ORDER BY id
        """,
        (actual_run_id,),
    ).fetchall()
    errors = [
        {
            "id": int(row["id"]),
            "relativePath": row["relative_path"],
            "errorType": row["error_type"],
            "message": row["message"],
            "createdAt": row["created_at"],
        }
        for row in error_rows
    ]

    high_file_candidates = sum(1 for item in missing if item["candidates"] and item["candidates"][0]["confidence"] == "HIGH")
    high_subtitle_candidates = sum(
        1 for item in unmatched_subtitles if item["candidates"] and item["candidates"][0]["confidence"] == "HIGH"
    )

    return {
        "scan": summary,
        "summary": {
            "missing": len(missing),
            "newFiles": len(new_files),
            "unmatchedSubtitles": len(unmatched_subtitles),
            "errors": len(errors),
            "highConfidenceFileCandidates": high_file_candidates,
            "highConfidenceSubtitleCandidates": high_subtitle_candidates,
        },
        "missing": missing,
        "newFiles": new_files,
        "unmatchedSubtitles": unmatched_subtitles,
        "errors": errors,
    }


def diagnostics_json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def diagnostics_csv_bytes(value: dict[str, Any]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["section", "path", "candidate_path", "score", "confidence", "reasons", "details"])

    for item in value.get("missing", []):
        candidates = item.get("candidates") or []
        if not candidates:
            writer.writerow(["MISSING", item.get("relativePath"), "", "", "", "", item.get("workTitle") or ""])
        for candidate in candidates:
            writer.writerow([
                "MISSING_CANDIDATE",
                item.get("relativePath"),
                candidate.get("relativePath"),
                candidate.get("score"),
                candidate.get("confidence"),
                ";".join(candidate.get("reasons") or []),
                item.get("workTitle") or "",
            ])

    for item in value.get("newFiles", []):
        writer.writerow(["NEW_FILE", item.get("relativePath"), "", "", "", "", item.get("fileSize") or ""])

    for item in value.get("unmatchedSubtitles", []):
        candidates = item.get("candidates") or []
        if not candidates:
            writer.writerow(["UNMATCHED_SUBTITLE", item.get("relativePath"), "", "", "", "", item.get("matchMethod") or ""])
        for candidate in candidates:
            writer.writerow([
                "SUBTITLE_CANDIDATE",
                item.get("relativePath"),
                candidate.get("relativePath"),
                candidate.get("score"),
                candidate.get("confidence"),
                ";".join(candidate.get("reasons") or []),
                candidate.get("workTitle") or "",
            ])

    for item in value.get("errors", []):
        writer.writerow([
            "ERROR",
            item.get("relativePath") or "",
            "",
            "",
            "",
            item.get("errorType") or "",
            item.get("message") or "",
        ])

    return b"\xef\xbb\xbf" + output.getvalue().encode("utf-8")
