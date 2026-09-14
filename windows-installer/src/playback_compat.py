from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

REAL_LIBRARY_VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".webm", ".mpg", ".flv"}


@dataclass(frozen=True)
class PlaybackPreparation:
    path: Path
    content_type: str
    transcoded: bool


def find_ffmpeg(explicit: Path | str | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env_value = os.environ.get("VIDEO_LIBRARY_FFMPEG")
    if env_value:
        candidates.append(Path(env_value).expanduser())

    here = Path(__file__).resolve().parent
    candidates.extend(
        [
            here / "ffmpeg.exe",
            here / "tools" / "ffmpeg.exe",
            here.parent / "tools" / "ffmpeg.exe",
        ]
    )
    found = shutil.which("ffmpeg.exe") or shutil.which("ffmpeg")
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


def browser_direct_playback(extension: str, video_codec: str | None, audio_codec: str | None) -> bool:
    ext = extension.casefold()
    video = (video_codec or "").casefold()
    audio = (audio_codec or "").casefold()

    if ext in {".mp4", ".m4v"}:
        return video in {"h264", "avc", "avc1"} and (not audio or audio in {"aac", "mp3"})
    if ext == ".webm":
        return video in {"vp8", "vp9", "av1"} and (not audio or audio in {"opus", "vorbis"})
    return False


def _cache_target(source: Path, cache_dir: Path) -> Path:
    stat = source.stat()
    key = f"{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8", errors="surrogatepass")
    digest = hashlib.sha256(key).hexdigest()[:24]
    return cache_dir / f"{digest}.mp4"


def transcode_to_browser_mp4(
    source: Path | str,
    cache_dir: Path | str,
    *,
    ffmpeg_path: Path | str | None = None,
    timeout_seconds: float = 3600.0,
) -> Path:
    src = Path(source).resolve()
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    target = _cache_target(src, cache)
    if target.is_file() and target.stat().st_size > 0:
        return target

    executable = find_ffmpeg(ffmpeg_path)
    if executable is None:
        raise RuntimeError("FFmpegが見つかりません。互換再生にはFFmpegが必要です。")

    temporary = target.with_name(target.stem + ".partial.mp4")
    try:
        if temporary.exists():
            temporary.unlink()
        command = [
            str(executable),
            "-nostdin",
            "-y",
            "-v",
            "error",
            "-i",
            str(src),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(temporary),
        ]
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout_seconds,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0,
        )
        if completed.returncode != 0 or not temporary.is_file() or temporary.stat().st_size <= 0:
            message = completed.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(message[:2000] or f"ffmpeg exit code {completed.returncode}")
        temporary.replace(target)
        return target
    finally:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass


def prepare_browser_playback(
    source: Path | str,
    extension: str,
    video_codec: str | None,
    audio_codec: str | None,
    cache_dir: Path | str,
    *,
    ffmpeg_path: Path | str | None = None,
) -> PlaybackPreparation:
    src = Path(source).resolve()
    ext = extension.casefold()
    if browser_direct_playback(ext, video_codec, audio_codec):
        content_type = "video/webm" if ext == ".webm" else "video/mp4"
        return PlaybackPreparation(path=src, content_type=content_type, transcoded=False)

    target = transcode_to_browser_mp4(src, cache_dir, ffmpeg_path=ffmpeg_path)
    return PlaybackPreparation(path=target, content_type="video/mp4", transcoded=True)
