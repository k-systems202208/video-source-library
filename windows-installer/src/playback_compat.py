from __future__ import annotations

import functools
import hashlib
import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from media_probe import find_ffprobe
from playback_cache import DEFAULT_CACHE_LIMIT_BYTES, mark_playback_cache_used, prune_playback_cache

REAL_LIBRARY_VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".webm", ".mpg", ".flv"}


@dataclass(frozen=True)
class PlaybackPreparation:
    path: Path
    content_type: str
    transcoded: bool
    audio_language: str | None = None


@dataclass(frozen=True)
class AudioSelection:
    stream_index: int
    codec: str
    language: str
    japanese: bool
    first_audio: bool


_TRANSCODE_LOCKS: dict[str, threading.Lock] = {}
_TRANSCODE_LOCKS_GUARD = threading.Lock()


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


def _is_japanese(language: str, title: str) -> bool:
    lang = language.casefold().replace("_", "-").strip()
    if lang in {"ja", "jp", "jpn", "japanese"} or lang.startswith(("ja-", "jpn-")):
        return True
    lowered = title.casefold()
    return "japanese" in lowered or "日本語" in title


@functools.lru_cache(maxsize=512)
def _cached_audio_selection(path_text: str, size: int, mtime_ns: int, ffprobe_text: str) -> AudioSelection | None:
    del size, mtime_ns
    command = [
        ffprobe_text,
        "-v", "error",
        "-print_format", "json",
        "-show_streams",
        path_text,
    ]
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30.0,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    streams = payload.get("streams") if isinstance(payload, dict) else None
    if not isinstance(streams, list):
        return None

    audio: list[AudioSelection] = []
    for stream in streams:
        if not isinstance(stream, dict) or stream.get("codec_type") != "audio":
            continue
        tags = stream.get("tags") if isinstance(stream.get("tags"), dict) else {}
        language = str(tags.get("language") or "").strip()
        title = str(tags.get("title") or tags.get("handler_name") or "").strip()
        codec = str(stream.get("codec_name") or "").strip().casefold()
        try:
            index = int(stream.get("index"))
        except (TypeError, ValueError):
            continue
        audio.append(
            AudioSelection(
                stream_index=index,
                codec=codec,
                language=language,
                japanese=_is_japanese(language, title),
                first_audio=len(audio) == 0,
            )
        )
    if not audio:
        return None
    return next((item for item in audio if item.japanese), audio[0])


def preferred_audio_selection(source: Path | str, *, ffprobe_path: Path | str | None = None) -> AudioSelection | None:
    src = Path(source).resolve()
    probe = find_ffprobe(ffprobe_path)
    if probe is None:
        return None
    try:
        stat = src.stat()
    except OSError:
        return None
    return _cached_audio_selection(str(src), int(stat.st_size), int(stat.st_mtime_ns), str(probe))


def _cache_target(source: Path, cache_dir: Path) -> Path:
    stat = source.stat()
    key = f"{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8", errors="surrogatepass")
    digest = hashlib.sha256(key).hexdigest()[:24]
    return cache_dir / f"{digest}.mp4"


def _target_lock(target: Path) -> threading.Lock:
    key = str(target.resolve())
    with _TRANSCODE_LOCKS_GUARD:
        lock = _TRANSCODE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _TRANSCODE_LOCKS[key] = lock
        return lock


def transcode_to_browser_mp4(
    source: Path | str,
    cache_dir: Path | str,
    *,
    ffmpeg_path: Path | str | None = None,
    ffprobe_path: Path | str | None = None,
    timeout_seconds: float = 3600.0,
) -> tuple[Path, str | None]:
    src = Path(source).resolve()
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    target = _cache_target(src, cache)
    selection = preferred_audio_selection(src, ffprobe_path=ffprobe_path)
    audio_language = "ja" if selection is not None and selection.japanese else (selection.language or None if selection else None)

    with _target_lock(target):
        if target.is_file() and target.stat().st_size > 0:
            mark_playback_cache_used(target)
            prune_playback_cache(cache, limit_bytes=DEFAULT_CACHE_LIMIT_BYTES, protected=(target,))
            return target, audio_language

        executable = find_ffmpeg(ffmpeg_path)
        if executable is None:
            raise RuntimeError("FFmpegが見つかりません。互換再生にはFFmpegが必要です。")

        temporary = target.with_name(target.stem + ".partial.mp4")
        try:
            if temporary.exists():
                temporary.unlink()
            audio_map = f"0:{selection.stream_index}" if selection is not None else "0:a:0?"
            command = [
                str(executable),
                "-nostdin", "-y", "-v", "error",
                "-i", str(src),
                "-map", "0:v:0",
                "-map", audio_map,
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
            ]
            if selection is not None and selection.japanese:
                command.extend(["-metadata:s:a:0", "language=jpn"])
            command.extend(["-movflags", "+faststart", str(temporary)])
            try:
                completed = subprocess.run(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                    timeout=timeout_seconds,
                    creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("再生用動画の変換が1時間以内に完了しませんでした。") from exc
            if completed.returncode != 0 or not temporary.is_file() or temporary.stat().st_size <= 0:
                message = completed.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(message[:2000] or f"ffmpeg exit code {completed.returncode}")
            temporary.replace(target)
            mark_playback_cache_used(target)
            prune_playback_cache(cache, limit_bytes=DEFAULT_CACHE_LIMIT_BYTES, protected=(target,))
            return target, audio_language
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
    ffprobe_path: Path | str | None = None,
) -> PlaybackPreparation:
    src = Path(source).resolve()
    ext = extension.casefold()
    selection = preferred_audio_selection(src, ffprobe_path=ffprobe_path)
    effective_audio = selection.codec if selection is not None else audio_codec
    requires_track_selection = bool(selection is not None and selection.japanese and not selection.first_audio)

    if browser_direct_playback(ext, video_codec, effective_audio) and not requires_track_selection:
        content_type = "video/webm" if ext == ".webm" else "video/mp4"
        return PlaybackPreparation(
            path=src,
            content_type=content_type,
            transcoded=False,
            audio_language="ja" if selection is not None and selection.japanese else (selection.language or None if selection else None),
        )

    target, language = transcode_to_browser_mp4(
        src,
        cache_dir,
        ffmpeg_path=ffmpeg_path,
        ffprobe_path=ffprobe_path,
    )
    return PlaybackPreparation(path=target, content_type="video/mp4", transcoded=True, audio_language=language)
