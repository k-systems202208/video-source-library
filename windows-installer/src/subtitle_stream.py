from __future__ import annotations

import html
import re
import sqlite3
from pathlib import Path

SUPPORTED_STREAM_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa"}
_TIMING_SRT_RE = re.compile(
    r"^(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{3})(?P<settings>.*)$"
)
_ASS_TAG_RE = re.compile(r"\{[^}]*\}")


def _decode_subtitle(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for encoding in ("utf-8", "cp932"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def _normalize_lines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")


def _timestamp_to_vtt(value: str) -> str:
    return value.strip().replace(",", ".")


def _srt_to_vtt(text: str) -> str:
    lines = _normalize_lines(text).split("\n")
    output = ["WEBVTT", ""]
    for line in lines:
        match = _TIMING_SRT_RE.match(line.strip())
        if match:
            line = (
                f"{_timestamp_to_vtt(match.group('start'))} --> "
                f"{_timestamp_to_vtt(match.group('end'))}{match.group('settings')}"
            )
        output.append(line)
    return "\n".join(output).rstrip() + "\n"


def _ass_timestamp(value: str) -> str:
    match = re.fullmatch(r"\s*(\d+):(\d{2}):(\d{2})(?:[.:](\d{1,3}))?\s*", value)
    if not match:
        raise ValueError(f"invalid ASS timestamp: {value}")
    hours, minutes, seconds = (int(match.group(i)) for i in range(1, 4))
    fraction = match.group(4) or "0"
    if len(fraction) == 1:
        millis = int(fraction) * 100
    elif len(fraction) == 2:
        millis = int(fraction) * 10
    else:
        millis = int(fraction[:3])
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def _ass_text_to_vtt(value: str) -> str:
    text = _ASS_TAG_RE.sub("", value)
    text = text.replace(r"\N", "\n").replace(r"\n", "\n").replace(r"\h", " ")
    return html.escape(text, quote=False)


def _ass_to_vtt(text: str) -> str:
    normalized = _normalize_lines(text)
    in_events = False
    fields: list[str] = []
    cues: list[str] = []
    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            in_events = line.casefold() == "[events]"
            continue
        if not in_events:
            continue
        if line.casefold().startswith("format:"):
            fields = [part.strip().casefold() for part in line.split(":", 1)[1].split(",")]
            continue
        if not line.casefold().startswith("dialogue:"):
            continue
        if not fields:
            fields = ["layer", "start", "end", "style", "name", "marginl", "marginr", "marginv", "effect", "text"]
        body = raw_line.split(":", 1)[1].lstrip()
        parts = body.split(",", len(fields) - 1)
        if len(parts) != len(fields):
            continue
        values = {name: parts[index] for index, name in enumerate(fields)}
        start = values.get("start")
        end = values.get("end")
        cue_text = values.get("text", "")
        if not start or not end:
            continue
        try:
            start_vtt = _ass_timestamp(start)
            end_vtt = _ass_timestamp(end)
        except ValueError:
            continue
        cues.append(f"{start_vtt} --> {end_vtt}\n{_ass_text_to_vtt(cue_text)}")
    return "WEBVTT\n\n" + "\n\n".join(cues) + ("\n" if cues else "")


def _vtt_to_vtt(text: str) -> str:
    normalized = _normalize_lines(text).lstrip()
    if normalized.startswith("WEBVTT"):
        return normalized.rstrip() + "\n"
    return "WEBVTT\n\n" + normalized.rstrip() + "\n"


def subtitle_bytes_to_webvtt(raw: bytes, extension: str) -> bytes:
    ext = extension.casefold()
    if not ext.startswith("."):
        ext = "." + ext
    if ext not in SUPPORTED_STREAM_EXTENSIONS:
        raise ValueError(f"unsupported subtitle extension: {extension}")
    text = _decode_subtitle(raw)
    if ext == ".srt":
        converted = _srt_to_vtt(text)
    elif ext in {".ass", ".ssa"}:
        converted = _ass_to_vtt(text)
    else:
        converted = _vtt_to_vtt(text)
    return converted.encode("utf-8")


def subtitle_file_to_webvtt(path: Path, extension: str | None = None) -> bytes:
    return subtitle_bytes_to_webvtt(path.read_bytes(), extension or path.suffix)


def resolve_subtitle_file(
    connection: sqlite3.Connection,
    video_root: Path | str,
    subtitle_id: int,
) -> tuple[Path, str] | None:
    row = connection.execute(
        """
        SELECT relative_path, extension
        FROM subtitles
        WHERE id=? AND video_id IS NOT NULL AND is_available=1
        """,
        (int(subtitle_id),),
    ).fetchone()
    if row is None:
        return None
    extension = str(row["extension"] or "").casefold()
    if not extension.startswith("."):
        extension = "." + extension
    if extension not in SUPPORTED_STREAM_EXTENSIONS:
        return None
    root = Path(video_root).expanduser().resolve()
    relative = str(row["relative_path"] or "").replace("\\", "/")
    candidate = (root / Path(relative)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate, extension
