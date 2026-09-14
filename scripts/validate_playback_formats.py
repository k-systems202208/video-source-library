from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from playback_compat import REAL_LIBRARY_VIDEO_EXTENSIONS, find_ffmpeg, prepare_browser_playback

FIXTURE = ROOT / "tests" / "fixtures" / "real_library_video_extensions.json"
EXPECTED_TOTAL = 4869


def _run(command: list[str], *, timeout: float = 120.0) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=timeout)
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}\n{stderr}")
    return completed


def _probe(ffprobe: str, path: Path) -> tuple[str, str]:
    completed = _run([
        ffprobe,
        "-v", "error",
        "-print_format", "json",
        "-show_streams",
        str(path),
    ])
    payload = json.loads(completed.stdout.decode("utf-8"))
    streams = payload.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise AssertionError(f"video stream missing: {path}")
    if audio is None:
        raise AssertionError(f"audio stream missing: {path}")
    return str(video.get("codec_name") or ""), str(audio.get("codec_name") or "")


def _make_source(ffmpeg: str, path: Path, video_args: list[str], audio_args: list[str], format_args: list[str] | None = None) -> None:
    command = [
        ffmpeg,
        "-nostdin", "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=12",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
        "-t", "0.7", "-shortest",
        *video_args,
        *audio_args,
    ]
    if format_args:
        command.extend(format_args)
    command.append(str(path))
    _run(command)
    if not path.is_file() or path.stat().st_size <= 0:
        raise AssertionError(f"fixture was not generated: {path}")


def main() -> int:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    extension_counts = {str(k).casefold(): int(v) for k, v in data["extensions"].items()}
    if int(data["total"]) != EXPECTED_TOTAL or sum(extension_counts.values()) != EXPECTED_TOTAL:
        raise AssertionError(f"real-library extension fixture total mismatch: {data}")
    if set(extension_counts) != REAL_LIBRARY_VIDEO_EXTENSIONS:
        raise AssertionError(
            f"real-library extension coverage mismatch: fixture={sorted(extension_counts)} code={sorted(REAL_LIBRARY_VIDEO_EXTENSIONS)}"
        )

    ffmpeg_path = find_ffmpeg()
    ffprobe_path = shutil.which("ffprobe.exe") or shutil.which("ffprobe")
    if ffmpeg_path is None:
        raise RuntimeError("FFmpeg is required for playback-format CI")
    if not ffprobe_path:
        raise RuntimeError("ffprobe is required for playback-format CI")
    ffmpeg = str(ffmpeg_path)

    recipes: dict[str, tuple[list[str], list[str], list[str] | None]] = {
        ".mp4": (["-c:v", "libx264", "-pix_fmt", "yuv420p"], ["-c:a", "aac"], None),
        ".webm": (["-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p"], ["-c:a", "libopus"], None),
        ".mkv": (["-c:v", "libx264", "-pix_fmt", "yuv420p"], ["-c:a", "ac3"], None),
        ".avi": (["-c:v", "mpeg4", "-q:v", "5"], ["-c:a", "libmp3lame"], None),
        ".mpg": (["-c:v", "mpeg2video", "-q:v", "5"], ["-c:a", "mp2"], ["-f", "mpeg"]),
        ".flv": (["-c:v", "flv", "-q:v", "5"], ["-c:a", "libmp3lame"], ["-f", "flv"]),
    }

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        cache = root / "PlaybackCache"
        results: list[str] = []
        for extension in sorted(REAL_LIBRARY_VIDEO_EXTENSIONS):
            source = root / f"input{extension}"
            video_args, audio_args, format_args = recipes[extension]
            _make_source(ffmpeg, source, video_args, audio_args, format_args)
            source_video, source_audio = _probe(ffprobe_path, source)

            prepared = prepare_browser_playback(
                source,
                extension,
                source_video,
                source_audio,
                cache,
                ffmpeg_path=ffmpeg,
            )
            out_video, out_audio = _probe(ffprobe_path, prepared.path)
            if prepared.content_type == "video/mp4":
                if out_video != "h264" or out_audio != "aac":
                    raise AssertionError(
                        f"{extension}: MP4 playback output must be h264+aac, got {out_video}+{out_audio}"
                    )
            elif prepared.content_type == "video/webm":
                if out_video not in {"vp8", "vp9", "av1"} or out_audio not in {"opus", "vorbis"}:
                    raise AssertionError(
                        f"{extension}: WebM playback output is not browser compatible: {out_video}+{out_audio}"
                    )
            else:
                raise AssertionError(f"{extension}: unexpected playback MIME {prepared.content_type}")

            _run([
                ffmpeg,
                "-nostdin", "-v", "error",
                "-i", str(prepared.path),
                "-map", "0:v:0", "-map", "0:a:0",
                "-t", "0.2",
                "-f", "null", "-",
            ])
            mode = "TRANSCODE" if prepared.transcoded else "DIRECT"
            results.append(f"{extension.upper():5} {extension_counts[extension]:4} files -> {mode:9} {out_video}+{out_audio}")

        print("Playback format CI: all real-library extensions are playable")
        for line in results:
            print("  " + line)
        print(f"  TOTAL {sum(extension_counts.values())} files / {len(extension_counts)} extensions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
