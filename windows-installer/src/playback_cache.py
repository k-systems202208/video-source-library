from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_CACHE_LIMIT_BYTES = 20 * 1024**3


@dataclass(frozen=True)
class PlaybackCacheStats:
    file_count: int
    total_bytes: int


@dataclass(frozen=True)
class PlaybackCacheCleanup:
    removed_files: int
    removed_bytes: int
    remaining_files: int
    remaining_bytes: int
    failed_files: int = 0


def _cache_files(cache_dir: Path | str) -> list[Path]:
    root = Path(cache_dir)
    if not root.is_dir():
        return []
    result: list[Path] = []
    for path in root.glob("*.mp4"):
        if not path.is_file() or path.name.endswith(".partial.mp4"):
            continue
        result.append(path)
    return result


def _managed_files(cache_dir: Path | str) -> list[Path]:
    root = Path(cache_dir)
    if not root.is_dir():
        return []
    return [path for path in root.glob("*.mp4") if path.is_file()]


def playback_cache_stats(cache_dir: Path | str) -> PlaybackCacheStats:
    total = 0
    count = 0
    for path in _cache_files(cache_dir):
        try:
            total += int(path.stat().st_size)
            count += 1
        except OSError:
            continue
    return PlaybackCacheStats(file_count=count, total_bytes=total)


def mark_playback_cache_used(path: Path | str) -> None:
    target = Path(path)
    try:
        os.utime(target, None)
    except OSError:
        pass


def prune_playback_cache(
    cache_dir: Path | str,
    *,
    limit_bytes: int = DEFAULT_CACHE_LIMIT_BYTES,
    protected: Iterable[Path | str] = (),
) -> PlaybackCacheCleanup:
    if limit_bytes < 0:
        raise ValueError("limit_bytes must be zero or greater")

    root = Path(cache_dir)
    protected_paths: set[Path] = set()
    for item in protected:
        try:
            protected_paths.add(Path(item).resolve())
        except OSError:
            protected_paths.add(Path(item).absolute())

    entries: list[tuple[int, int, Path]] = []
    total = 0
    for path in _cache_files(root):
        try:
            stat = path.stat()
        except OSError:
            continue
        total += int(stat.st_size)
        entries.append((int(stat.st_mtime_ns), int(stat.st_size), path))

    removed_files = 0
    removed_bytes = 0
    failed_files = 0
    if total > limit_bytes:
        for _mtime_ns, size, path in sorted(entries, key=lambda item: item[0]):
            if total <= limit_bytes:
                break
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path.absolute()
            if resolved in protected_paths:
                continue
            try:
                path.unlink()
            except OSError:
                failed_files += 1
                continue
            total -= size
            removed_files += 1
            removed_bytes += size

    remaining = playback_cache_stats(root)
    return PlaybackCacheCleanup(
        removed_files=removed_files,
        removed_bytes=removed_bytes,
        remaining_files=remaining.file_count,
        remaining_bytes=remaining.total_bytes,
        failed_files=failed_files,
    )


def clear_playback_cache(cache_dir: Path | str) -> PlaybackCacheCleanup:
    root = Path(cache_dir)
    removed_files = 0
    removed_bytes = 0
    failed_files = 0
    for path in _managed_files(root):
        try:
            size = int(path.stat().st_size)
            path.unlink()
        except OSError:
            failed_files += 1
            continue
        removed_files += 1
        removed_bytes += size
    remaining = playback_cache_stats(root)
    return PlaybackCacheCleanup(
        removed_files=removed_files,
        removed_bytes=removed_bytes,
        remaining_files=remaining.file_count,
        remaining_bytes=remaining.total_bytes,
        failed_files=failed_files,
    )


def format_bytes(value: int) -> str:
    size = float(max(0, int(value)))
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"
