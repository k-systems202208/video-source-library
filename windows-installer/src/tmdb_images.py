from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
_ALLOWED_SUFFIXES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def _safe_suffix(remote_path: str) -> str:
    suffix = Path(str(remote_path or "")).suffix.casefold()
    if suffix not in _ALLOWED_SUFFIXES:
        raise ValueError("unsupported TMDb image extension")
    return suffix


def cached_image_path(image_root: Path | str, work_id: int, kind: str, remote_path: str) -> Path:
    if kind not in {"poster", "backdrop"}:
        raise ValueError("kind must be poster or backdrop")
    suffix = _safe_suffix(remote_path)
    root = Path(image_root)
    return root / kind / f"{int(work_id)}{suffix}"


def image_content_type(path: Path | str) -> str:
    return _ALLOWED_SUFFIXES.get(Path(path).suffix.casefold(), "application/octet-stream")


def download_tmdb_image(
    remote_path: str,
    destination: Path | str,
    *,
    size: str,
    opener: Callable[..., Any] = urlopen,
    timeout: float = 20.0,
) -> Path:
    suffix = _safe_suffix(remote_path)
    target = Path(destination)
    if target.suffix.casefold() != suffix:
        raise ValueError("TMDb image destination extension mismatch")
    clean_path = str(remote_path or "").strip()
    if not clean_path.startswith("/") or clean_path.startswith("//"):
        raise ValueError("invalid TMDb image path")
    url = f"{TMDB_IMAGE_BASE}/{size}{clean_path}"
    request = Request(
        url,
        headers={"Accept": "image/avif,image/webp,image/png,image/jpeg,*/*;q=0.5", "User-Agent": "VideoLibrary/1.1"},
        method="GET",
    )
    response = opener(request, timeout=timeout)
    try:
        length_text = response.headers.get("Content-Length") if getattr(response, "headers", None) else None
        if length_text:
            try:
                if int(length_text) > MAX_IMAGE_BYTES:
                    raise ValueError("TMDb image is too large")
            except ValueError as exc:
                if str(exc) == "TMDb image is too large":
                    raise
        body = response.read(MAX_IMAGE_BYTES + 1)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
    if len(body) > MAX_IMAGE_BYTES:
        raise ValueError("TMDb image is too large")
    if not body:
        raise ValueError("TMDb image is empty")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_bytes(body)
    temp.replace(target)
    return target


def resolve_cached_tmdb_image(
    connection: sqlite3.Connection,
    image_root: Path | str,
    work_id: int,
    kind: str,
) -> tuple[Path, str] | None:
    column = {"poster": "poster_path", "backdrop": "backdrop_path"}.get(kind)
    if column is None:
        return None
    row = connection.execute(
        f"SELECT {column} image_path FROM tmdb_work_links WHERE work_id=? AND match_status='MATCHED'",
        (int(work_id),),
    ).fetchone()
    if row is None or not row["image_path"]:
        return None
    try:
        path = cached_image_path(image_root, int(work_id), kind, str(row["image_path"]))
    except ValueError:
        return None
    if not path.is_file():
        return None
    return path, image_content_type(path)
