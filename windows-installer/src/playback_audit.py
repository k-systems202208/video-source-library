from __future__ import annotations

import csv
import json
import os
import re
import subprocess
from difflib import SequenceMatcher
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from database import connect, initialize_database
from media_probe import find_ffprobe
from playback_compat import REAL_LIBRARY_VIDEO_EXTENSIONS, browser_direct_playback, browser_transcode_codec_args, find_ffmpeg

SUBTITLE_ONLY_CONTAINER_FORMATS = {"ass", "ssa", "srt", "subrip", "webvtt", "vtt"}
SOURCE_DATA_ERROR_REASONS = {"SUBTITLE_CONTENT_REGISTERED_AS_VIDEO", "MISSING_FILE", "NO_VIDEO_STREAM", "PATH_ESCAPE"}
AUDIT_VIDEO_EXTENSIONS = REAL_LIBRARY_VIDEO_EXTENSIONS | {".m4v", ".mov", ".wmv"}


@dataclass(frozen=True)
class AuditProbe:
    status: str
    container_format: str = ""
    video_codec: str = ""
    video_profile: str = ""
    pixel_format: str = ""
    audio_codecs: tuple[str, ...] = ()
    audio_languages: tuple[str, ...] = ()
    audio_track_count: int = 0
    has_japanese_audio: bool = False
    preferred_audio_index: int | None = None
    preferred_audio_codec: str = ""
    preferred_audio_language: str = ""
    preferred_audio_is_first: bool = True
    embedded_subtitle_count: int = 0
    sample_decode: str = "NOT_RUN"
    route: str = "NO_ROUTE"
    reason: str = ""
    error: str = ""


def _is_japanese(language: str, title: str) -> bool:
    lang = language.casefold().replace("_", "-").strip()
    if lang in {"ja", "jp", "jpn", "japanese"} or lang.startswith(("ja-", "jpn-")):
        return True
    lowered = title.casefold()
    return "japanese" in lowered or "日本語" in title


def _no_video_reason(container_format: str) -> str:
    formats = {part.strip().casefold() for part in str(container_format or "").split(",") if part.strip()}
    if formats & SUBTITLE_ONLY_CONTAINER_FORMATS:
        return "SUBTITLE_CONTENT_REGISTERED_AS_VIDEO"
    return "NO_VIDEO_STREAM"


def parse_audit_probe_payload(
    payload: dict[str, Any],
    *,
    extension: str,
    ffmpeg_available: bool,
) -> AuditProbe:
    streams = payload.get("streams")
    if not isinstance(streams, list):
        streams = []
    format_info = payload.get("format")
    if not isinstance(format_info, dict):
        format_info = {}

    container_format = str(format_info.get("format_name") or "").strip()
    videos = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "video"]
    audios = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "audio"]
    subtitles = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "subtitle"]
    if not videos:
        return AuditProbe(
            status="OK",
            container_format=container_format,
            audio_track_count=len(audios),
            embedded_subtitle_count=len(subtitles),
            route="NO_ROUTE",
            reason=_no_video_reason(container_format),
        )

    video_codec = str(videos[0].get("codec_name") or "").strip().casefold()
    video_profile = str(videos[0].get("profile") or "").strip()
    pixel_format = str(videos[0].get("pix_fmt") or "").strip()
    parsed_audio: list[dict[str, Any]] = []
    for position, stream in enumerate(audios):
        tags = stream.get("tags") if isinstance(stream.get("tags"), dict) else {}
        language = str(tags.get("language") or "").strip()
        title = str(tags.get("title") or tags.get("handler_name") or "").strip()
        try:
            index = int(stream.get("index"))
        except (TypeError, ValueError):
            index = position
        parsed_audio.append(
            {
                "index": index,
                "codec": str(stream.get("codec_name") or "").strip().casefold(),
                "language": language,
                "japanese": _is_japanese(language, title),
                "first": position == 0,
            }
        )

    preferred = next((item for item in parsed_audio if item["japanese"]), parsed_audio[0] if parsed_audio else None)
    preferred_codec = str(preferred["codec"]) if preferred else ""
    preferred_language = str(preferred["language"]) if preferred else ""
    preferred_is_first = bool(preferred is None or preferred["first"])
    direct = browser_direct_playback(extension, video_codec, preferred_codec or None) and preferred_is_first

    if direct:
        route = "DIRECT"
        reason = ""
    elif ffmpeg_available:
        route = "TRANSCODE"
        reason = "BROWSER_INCOMPATIBLE_OR_TRACK_SELECTION"
    else:
        route = "NO_ROUTE"
        reason = "FFMPEG_NOT_AVAILABLE"

    return AuditProbe(
        status="OK",
        container_format=container_format,
        video_codec=video_codec,
        video_profile=video_profile,
        pixel_format=pixel_format,
        audio_codecs=tuple(str(item["codec"]) for item in parsed_audio),
        audio_languages=tuple(str(item["language"]) for item in parsed_audio),
        audio_track_count=len(parsed_audio),
        has_japanese_audio=any(bool(item["japanese"]) for item in parsed_audio),
        preferred_audio_index=int(preferred["index"]) if preferred else None,
        preferred_audio_codec=preferred_codec,
        preferred_audio_language=preferred_language,
        preferred_audio_is_first=preferred_is_first,
        embedded_subtitle_count=len(subtitles),
        route=route,
        reason=reason,
    )


def _sanitize_process_error(text: str, source: Path) -> str:
    sanitized = str(text or "")
    candidates = {str(source), source.as_posix()}
    try:
        candidates.add(str(source.resolve()))
        candidates.add(source.resolve().as_posix())
    except OSError:
        pass
    for candidate in sorted((value for value in candidates if value), key=len, reverse=True):
        sanitized = sanitized.replace(candidate, "<video>")
    return sanitized[:1000]


def probe_for_audit(
    source: Path,
    *,
    extension: str,
    ffprobe_path: Path,
    ffmpeg_available: bool,
    timeout_seconds: float = 30.0,
) -> AuditProbe:
    command = [
        str(ffprobe_path),
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(source),
    ]
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout_seconds,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return AuditProbe(
            status="ERROR",
            route="NO_ROUTE",
            reason="PROBE_ERROR",
            error=_sanitize_process_error(f"{type(exc).__name__}: {exc}", source),
        )
    if completed.returncode != 0:
        error = completed.stderr.decode("utf-8", errors="replace").strip()
        return AuditProbe(
            status="ERROR",
            route="NO_ROUTE",
            reason="PROBE_ERROR",
            error=_sanitize_process_error(error, source) or f"ffprobe exit code {completed.returncode}",
        )
    try:
        payload = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return AuditProbe(
            status="ERROR",
            route="NO_ROUTE",
            reason="PROBE_ERROR",
            error=f"invalid ffprobe JSON: {exc}"[:1000],
        )
    if not isinstance(payload, dict):
        return AuditProbe(
            status="ERROR",
            route="NO_ROUTE",
            reason="PROBE_ERROR",
            error="ffprobe JSON root is not an object",
        )
    return parse_audit_probe_payload(payload, extension=extension, ffmpeg_available=ffmpeg_available)


def verify_playback_sample(
    source: Path,
    *,
    preferred_audio_index: int | None,
    ffmpeg_path: Path,
    route: str = "TRANSCODE",
    timeout_seconds: float = 60.0,
) -> tuple[bool, str]:
    command = [
        str(ffmpeg_path),
        "-nostdin", "-v", "error",
        "-t", "0.5",
        "-i", str(source),
        "-map", "0:v:0",
    ]
    command.extend(["-map", f"0:{preferred_audio_index}"] if preferred_audio_index is not None else ["-map", "0:a:0?"])
    if route == "TRANSCODE":
        command.extend(browser_transcode_codec_args(preset="ultrafast", crf="30", audio_bitrate="96k"))
    command.extend(["-f", "null", "-"])
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout_seconds,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, _sanitize_process_error(f"{type(exc).__name__}: {exc}", source)
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        return False, _sanitize_process_error(message, source) or f"ffmpeg exit code {completed.returncode}"
    return True, ""


def _safe_source(video_root: Path, relative_path: str) -> Path | None:
    try:
        root = video_root.resolve()
        source = (root / Path(relative_path)).resolve()
        source.relative_to(root)
        return source
    except (OSError, ValueError):
        return None


def _candidate_name_key(path: Path) -> str:
    stem = path.stem.casefold()
    stem = re.sub(r"[\[\](){}._-]+", " ", stem)
    stem = re.sub(r"\b(?:720p|1080p|2160p|x264|x265|h264|h265|hevc|aac|flac|web[- ]?dl|bluray|hdtv)\b", " ", stem)
    return " ".join(stem.split())


def _episode_numbers(path: Path) -> set[int]:
    stem = path.stem.casefold()
    values: set[int] = set()
    patterns = [
        r"(?:^|[^a-z0-9])(?:ep|e|episode)[ ._-]*0*(\d{1,3})(?:[^0-9]|$)",
        r"(?:^|[^a-z0-9])0*(\d{1,3})(?:[^0-9]|$)",
    ]
    for pattern in patterns:
        for raw in re.findall(pattern, stem):
            try:
                values.add(int(raw))
            except ValueError:
                pass
        if values:
            break
    return values


def _repair_candidate_score(target: Path, candidate: Path) -> tuple[float, str]:
    target_key = _candidate_name_key(target)
    candidate_key = _candidate_name_key(candidate)
    ratio = SequenceMatcher(None, target_key, candidate_key).ratio()
    target_eps = _episode_numbers(target)
    candidate_eps = _episode_numbers(candidate)
    if target_eps and candidate_eps and target_eps & candidate_eps:
        return min(1.0, ratio + 0.40), "EPISODE_MATCH"
    if target_eps and candidate_eps and not (target_eps & candidate_eps):
        return max(0.0, ratio - 0.35), "EPISODE_MISMATCH"
    return ratio, "NAME_SIMILARITY"


def _find_repair_candidates(
    source: Path,
    *,
    video_root: Path,
    ffprobe_path: Path,
    ffmpeg_available: bool,
    directory_cache: dict[Path, list[dict[str, Any]]],
    limit: int = 3,
) -> list[dict[str, Any]]:
    parent = source.parent
    try:
        parent.relative_to(video_root)
    except ValueError:
        return []
    if not parent.is_dir():
        return []

    viable = directory_cache.get(parent)
    if viable is None:
        viable = []
        try:
            entries = sorted(parent.iterdir(), key=lambda item: item.name.casefold())
        except OSError:
            entries = []
        for candidate in entries:
            if not candidate.is_file() or candidate.suffix.casefold() not in AUDIT_VIDEO_EXTENSIONS:
                continue
            if candidate == source:
                continue
            candidate_probe = probe_for_audit(
                candidate,
                extension=candidate.suffix,
                ffprobe_path=ffprobe_path,
                ffmpeg_available=ffmpeg_available,
            )
            if not candidate_probe.video_codec or candidate_probe.reason in SOURCE_DATA_ERROR_REASONS or candidate_probe.reason == "PROBE_ERROR":
                continue
            try:
                relative = candidate.relative_to(video_root).as_posix()
            except ValueError:
                continue
            viable.append(
                {
                    "path": candidate,
                    "relativePath": relative,
                    "containerFormat": candidate_probe.container_format,
                    "videoCodec": candidate_probe.video_codec,
                }
            )
        directory_cache[parent] = viable

    ranked: list[dict[str, Any]] = []
    for candidate in viable:
        path = candidate["path"]
        if path == source:
            continue
        score, reason = _repair_candidate_score(source, path)
        if reason == "EPISODE_MISMATCH":
            continue
        ranked.append(
            {
                "relativePath": candidate["relativePath"],
                "score": round(score, 4),
                "reason": reason,
                "containerFormat": candidate["containerFormat"],
                "videoCodec": candidate["videoCodec"],
            }
        )
    ranked.sort(key=lambda item: (-float(item["score"]), str(item["relativePath"]).casefold()))
    return ranked[: max(0, limit)]


def summarize_audit(items: list[dict[str, Any]]) -> dict[str, Any]:
    extensions = Counter(str(item.get("extension") or "").lower() for item in items)
    containers = Counter(str(item.get("containerFormat") or "") for item in items if item.get("containerFormat"))
    video_codecs = Counter(str(item.get("videoCodec") or "") for item in items if item.get("videoCodec"))
    audio_codecs: Counter[str] = Counter()
    for item in items:
        for codec in item.get("audioCodecs") or []:
            if codec:
                audio_codecs[str(codec)] += 1

    direct = sum(1 for item in items if item.get("route") == "DIRECT")
    transcode = sum(1 for item in items if item.get("route") == "TRANSCODE")
    raw_no_route = sum(1 for item in items if item.get("route") == "NO_ROUTE")
    source_data_errors = sum(1 for item in items if item.get("reason") in SOURCE_DATA_ERROR_REASONS)
    application_no_route = sum(
        1
        for item in items
        if item.get("route") == "NO_ROUTE" and item.get("reason") not in SOURCE_DATA_ERROR_REASONS
    )

    return {
        "total": len(items),
        "playableVideoTotal": len(items) - source_data_errors,
        "direct": direct,
        "transcode": transcode,
        "noRoute": raw_no_route,
        "applicationNoRoute": application_no_route,
        "sourceDataErrors": source_data_errors,
        "sourceDataErrorsWithCandidates": sum(1 for item in items if item.get("reason") in SOURCE_DATA_ERROR_REASONS and int(item.get("repairCandidateCount") or 0) > 0),
        "sourceDataErrorsWithoutCandidates": sum(1 for item in items if item.get("reason") in SOURCE_DATA_ERROR_REASONS and int(item.get("repairCandidateCount") or 0) == 0),
        "probeErrors": sum(1 for item in items if item.get("reason") == "PROBE_ERROR"),
        "decodeErrors": sum(1 for item in items if item.get("reason") == "DECODE_ERROR"),
        "missing": sum(1 for item in items if item.get("reason") == "MISSING_FILE"),
        "pathEscapes": sum(1 for item in items if item.get("reason") == "PATH_ESCAPE"),
        "noVideoStream": sum(1 for item in items if item.get("reason") == "NO_VIDEO_STREAM"),
        "subtitleContentRegisteredAsVideo": sum(
            1 for item in items if item.get("reason") == "SUBTITLE_CONTENT_REGISTERED_AS_VIDEO"
        ),
        "withJapaneseAudio": sum(1 for item in items if item.get("hasJapaneseAudio")),
        "multiAudio": sum(1 for item in items if int(item.get("audioTrackCount") or 0) > 1),
        "withExternalSubtitles": sum(1 for item in items if int(item.get("externalSubtitleCount") or 0) > 0),
        "externalSubtitleFiles": sum(int(item.get("externalSubtitleCount") or 0) for item in items),
        "withEmbeddedSubtitles": sum(1 for item in items if int(item.get("embeddedSubtitleCount") or 0) > 0),
        "embeddedSubtitleStreams": sum(int(item.get("embeddedSubtitleCount") or 0) for item in items),
        "extensions": dict(sorted(extensions.items())),
        "containers": dict(sorted(containers.items())),
        "videoCodecs": dict(sorted(video_codecs.items())),
        "audioCodecs": dict(sorted(audio_codecs.items())),
    }


def write_audit_reports(
    output_dir: Path,
    report: dict[str, Any],
    *,
    stamp: str | None = None,
) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = stamp or datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    json_path = output_dir / f"playback-audit-{suffix}.json"
    csv_path = output_dir / f"playback-audit-{suffix}.csv"
    source_errors_path = output_dir / f"playback-audit-source-errors-{suffix}.csv"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    fields = [
        "videoId", "externalFileNo", "title", "episode", "relativePath", "extension",
        "containerFormat", "videoCodec", "videoProfile", "pixelFormat", "audioCodecs", "audioLanguages", "audioTrackCount",
        "hasJapaneseAudio", "preferredAudioIndex", "preferredAudioCodec", "preferredAudioLanguage",
        "externalSubtitleCount", "embeddedSubtitleCount", "sampleDecode", "route", "reason", "error",
        "repairCandidateCount", "repairCandidates",
    ]

    def csv_row(item: dict[str, Any]) -> dict[str, Any]:
        row = dict(item)
        row["audioCodecs"] = ";".join(row.get("audioCodecs") or [])
        row["audioLanguages"] = ";".join(row.get("audioLanguages") or [])
        row["repairCandidates"] = ";".join(
            f"{candidate.get('relativePath', '')}|{candidate.get('score', '')}|{candidate.get('reason', '')}"
            for candidate in (row.get("repairCandidates") or [])
        )
        return row

    items = list(report.get("items") or [])
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for item in items:
            writer.writerow(csv_row(item))

    with source_errors_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for item in items:
            if item.get("reason") in SOURCE_DATA_ERROR_REASONS:
                writer.writerow(csv_row(item))
    return json_path, csv_path, source_errors_path


def audit_real_library(
    database_path: Path | str,
    video_root: Path | str,
    output_dir: Path | str,
    *,
    ffprobe_path: Path | str | None = None,
    ffmpeg_path: Path | str | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    root = Path(video_root).resolve()
    probe = find_ffprobe(ffprobe_path)
    ffmpeg = find_ffmpeg(ffmpeg_path)
    if probe is None:
        raise RuntimeError("ffprobeが見つかりません。全件再生監査を実行できません。")

    with connect(database_path) as connection:
        initialize_database(connection)
        rows = connection.execute(
            """
            SELECT vf.video_id, v.external_file_no, v.official_title, v.episode_or_type,
                   v.episode_title, vf.relative_path, vf.extension,
                   (SELECT COUNT(*) FROM subtitles s WHERE s.video_id=vf.video_id AND s.is_available=1) external_subtitles
            FROM video_files vf
            JOIN videos v ON v.id=vf.video_id
            ORDER BY v.external_file_no
            """
        ).fetchall()

    items: list[dict[str, Any]] = []
    repair_directory_cache: dict[Path, list[dict[str, Any]]] = {}
    total = len(rows)
    for position, row in enumerate(rows, start=1):
        relative_path = str(row["relative_path"] or "")
        extension = str(row["extension"] or Path(relative_path).suffix).casefold()
        source = _safe_source(root, relative_path)
        if source is None:
            result = AuditProbe(
                status="ERROR",
                route="NO_ROUTE",
                reason="PATH_ESCAPE",
                error="relative path escapes video root",
            )
        elif not source.is_file():
            result = AuditProbe(
                status="ERROR",
                route="NO_ROUTE",
                reason="MISSING_FILE",
                error="registered video file was not found",
            )
        else:
            result = probe_for_audit(
                source,
                extension=extension,
                ffprobe_path=probe,
                ffmpeg_available=ffmpeg is not None,
            )

            if result.route != "NO_ROUTE" and ffmpeg is not None:
                decoded, decode_error = verify_playback_sample(
                    source,
                    preferred_audio_index=result.preferred_audio_index,
                    ffmpeg_path=ffmpeg,
                    route=result.route,
                )
                if decoded:
                    result = replace(result, sample_decode="PASS")
                else:
                    result = replace(
                        result,
                        sample_decode="FAIL",
                        route="NO_ROUTE",
                        reason="DECODE_ERROR",
                        error=decode_error,
                    )

        title = str(row["official_title"] or "")
        episode = str(row["episode_title"] or row["episode_or_type"] or "")
        item = {
            "videoId": int(row["video_id"]),
            "externalFileNo": int(row["external_file_no"]),
            "title": title,
            "episode": episode,
            "relativePath": relative_path.replace("\\", "/"),
            "extension": extension,
            "containerFormat": result.container_format,
            "videoCodec": result.video_codec,
            "videoProfile": result.video_profile,
            "pixelFormat": result.pixel_format,
            "audioCodecs": list(result.audio_codecs),
            "audioLanguages": list(result.audio_languages),
            "audioTrackCount": result.audio_track_count,
            "hasJapaneseAudio": result.has_japanese_audio,
            "preferredAudioIndex": result.preferred_audio_index,
            "preferredAudioCodec": result.preferred_audio_codec,
            "preferredAudioLanguage": result.preferred_audio_language,
            "externalSubtitleCount": int(row["external_subtitles"] or 0),
            "embeddedSubtitleCount": result.embedded_subtitle_count,
            "sampleDecode": result.sample_decode,
            "route": result.route,
            "reason": result.reason,
            "error": result.error,
            "repairCandidateCount": 0,
            "repairCandidates": [],
        }
        if result.reason in SOURCE_DATA_ERROR_REASONS and source is not None:
            candidates = _find_repair_candidates(
                source,
                video_root=root,
                ffprobe_path=probe,
                ffmpeg_available=ffmpeg is not None,
                directory_cache=repair_directory_cache,
            )
            item["repairCandidates"] = candidates
            item["repairCandidateCount"] = len(candidates)
        items.append(item)
        if progress_callback is not None:
            current_summary = summarize_audit(items)
            progress_callback(
                {
                    "current": position,
                    "total": total,
                    "currentItem": relative_path,
                    "direct": current_summary["direct"],
                    "transcode": current_summary["transcode"],
                    "noRoute": current_summary["noRoute"],
                    "applicationNoRoute": current_summary["applicationNoRoute"],
                    "sourceDataErrors": current_summary["sourceDataErrors"],
                    "sourceDataErrorsWithCandidates": current_summary["sourceDataErrorsWithCandidates"],
                    "sourceDataErrorsWithoutCandidates": current_summary["sourceDataErrorsWithoutCandidates"],
                }
            )

    report = {
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "ffprobeAvailable": True,
        "ffmpegAvailable": ffmpeg is not None,
        "summary": summarize_audit(items),
        "items": items,
    }
    json_path, csv_path, source_errors_path = write_audit_reports(Path(output_dir), report)
    report["jsonReport"] = str(json_path)
    report["csvReport"] = str(csv_path)
    report["sourceErrorsCsvReport"] = str(source_errors_path)
    return report
