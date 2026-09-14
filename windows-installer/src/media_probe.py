from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProbeResult:
    status: str
    container_format: str | None = None
    duration_ms: int | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    width: int | None = None
    height: int | None = None
    embedded_subtitle_count: int = 0
    playback_support: str = "UNKNOWN"
    error: str = ""


def find_ffprobe(explicit: Path | str | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env_value = os.environ.get("VIDEO_LIBRARY_FFPROBE")
    if env_value:
        candidates.append(Path(env_value).expanduser())

    here = Path(__file__).resolve().parent
    candidates.extend(
        [
            here / "ffprobe.exe",
            here / "tools" / "ffprobe.exe",
            here.parent / "tools" / "ffprobe.exe",
        ]
    )
    found = shutil.which("ffprobe.exe") or shutil.which("ffprobe")
    if found:
        candidates.append(Path(found))

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file():
            return resolved
    return None


def _safe_int(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _duration_ms(value: Any) -> int | None:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return int(round(seconds * 1000.0))


def playback_support(
    extension: str,
    video_codec: str | None,
    audio_codec: str | None,
) -> str:
    ext = extension.casefold()
    video = (video_codec or "").casefold()
    audio = (audio_codec or "").casefold()

    if ext in {".mp4", ".m4v"}:
        if video in {"h264", "avc", "avc1"} and (not audio or audio in {"aac", "mp3"}):
            return "DIRECT"
        return "UNKNOWN"

    if ext == ".webm":
        if video in {"vp8", "vp9", "av1"} and (not audio or audio in {"opus", "vorbis"}):
            return "DIRECT"
        return "UNKNOWN"

    return "UNKNOWN"


def parse_probe_payload(payload: dict[str, Any], *, extension: str) -> ProbeResult:
    streams = payload.get("streams")
    if not isinstance(streams, list):
        streams = []
    format_info = payload.get("format")
    if not isinstance(format_info, dict):
        format_info = {}

    video_stream = next(
        (stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "video"),
        {},
    )
    audio_stream = next(
        (stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "audio"),
        {},
    )
    embedded_subtitles = sum(
        1
        for stream in streams
        if isinstance(stream, dict) and stream.get("codec_type") == "subtitle"
    )

    video_codec = str(video_stream.get("codec_name") or "").strip() or None
    audio_codec = str(audio_stream.get("codec_name") or "").strip() or None
    container = str(format_info.get("format_name") or "").strip() or None
    duration = _duration_ms(format_info.get("duration"))
    if duration is None:
        duration = _duration_ms(video_stream.get("duration"))

    return ProbeResult(
        status="OK",
        container_format=container,
        duration_ms=duration,
        video_codec=video_codec,
        audio_codec=audio_codec,
        width=_safe_int(video_stream.get("width")),
        height=_safe_int(video_stream.get("height")),
        embedded_subtitle_count=embedded_subtitles,
        playback_support=playback_support(extension, video_codec, audio_codec),
    )


def probe_media(
    path: Path | str,
    *,
    extension: str | None = None,
    ffprobe_path: Path | str | None = None,
    timeout_seconds: float = 30.0,
) -> ProbeResult:
    executable = find_ffprobe(ffprobe_path)
    if executable is None:
        return ProbeResult(status="NOT_AVAILABLE", error="ffprobe was not found")

    source = Path(path)
    ext = (extension or source.suffix).casefold()
    command = [
        str(executable),
        "-v",
        "error",
        "-print_format",
        "json",
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
        return ProbeResult(status="ERROR", error=f"{type(exc).__name__}: {exc}"[:1000])

    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        return ProbeResult(status="ERROR", error=message[:1000] or f"ffprobe exit code {completed.returncode}")

    try:
        payload = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return ProbeResult(status="ERROR", error=f"invalid ffprobe JSON: {exc}"[:1000])
    if not isinstance(payload, dict):
        return ProbeResult(status="ERROR", error="ffprobe JSON root is not an object")
    return parse_probe_payload(payload, extension=ext)
