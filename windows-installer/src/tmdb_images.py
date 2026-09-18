from __future__ import annotations

import hashlib
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
_ALLOWED_SUFFIXES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
_REPAIR_LOCK = threading.Lock()


def _safe_suffix(remote_path: str) -> str:
    suffix = Path(str(remote_path or "")).suffix.casefold()
    if suffix not in _ALLOWED_SUFFIXES:
        raise ValueError("unsupported TMDb image extension")
    return suffix


def cached_image_path(image_root: Path | str, work_id: int, kind: str, remote_path: str) -> Path:
    if kind not in {"poster", "backdrop"}:
        raise ValueError("kind must be poster or backdrop")
    clean_path = str(remote_path or "").strip()
    suffix = _safe_suffix(clean_path)
    identity = hashlib.sha256(clean_path.encode("utf-8")).hexdigest()[:12]
    root = Path(image_root)
    return root / kind / f"{int(work_id)}-{identity}{suffix}"


def cached_person_image_path(image_root: Path | str, person_id: int, remote_path: str) -> Path:
    suffix = _safe_suffix(remote_path)
    return Path(image_root) / "person" / f"{int(person_id)}{suffix}"


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


def resolve_or_repair_cached_tmdb_image(
    connection: sqlite3.Connection,
    image_root: Path | str,
    work_id: int,
    kind: str,
    *,
    image_downloader: Callable[..., Path] = download_tmdb_image,
) -> tuple[Path, str] | None:
    """Resolve a cached TMDb image and repair a missing cache file on demand.

    The database already stores TMDb's image path for MATCHED works.  If the
    corresponding local cache file has disappeared or a previous sync did not
    finish downloading it, fetch only that image from image.tmdb.org.  A single
    process-wide lock avoids duplicate writes to the same .tmp file when a
    catalog and a home strip request the same work at once.
    """
    resolved = resolve_cached_tmdb_image(connection, image_root, work_id, kind)
    if resolved is not None:
        return resolved

    column = {"poster": "poster_path", "backdrop": "backdrop_path"}.get(kind)
    if column is None:
        return None
    row = connection.execute(
        f"SELECT {column} image_path FROM tmdb_work_links WHERE work_id=? AND match_status='MATCHED'",
        (int(work_id),),
    ).fetchone()
    if row is None or not row["image_path"]:
        return None
    remote_path = str(row["image_path"])
    try:
        target = cached_image_path(image_root, int(work_id), kind, remote_path)
    except ValueError:
        return None

    with _REPAIR_LOCK:
        if not target.is_file():
            try:
                image_downloader(
                    remote_path,
                    target,
                    size="w500" if kind == "poster" else "w1280",
                )
            except Exception:
                return None
    if not target.is_file():
        return None
    return target, image_content_type(target)


def resolve_or_repair_cached_tmdb_person_image(
    connection: sqlite3.Connection,
    image_root: Path | str,
    person_id: int,
    *,
    image_downloader: Callable[..., Path] = download_tmdb_image,
) -> tuple[Path, str] | None:
    row = connection.execute(
        "SELECT profile_path FROM tmdb_people WHERE tmdb_person_id=?",
        (int(person_id),),
    ).fetchone()
    if row is None or not row["profile_path"]:
        return None
    remote_path = str(row["profile_path"])
    try:
        target = cached_person_image_path(image_root, int(person_id), remote_path)
    except ValueError:
        return None

    with _REPAIR_LOCK:
        if not target.is_file():
            try:
                image_downloader(remote_path, target, size="w185")
            except Exception:
                return None
    if not target.is_file():
        return None
    return target, image_content_type(target)
