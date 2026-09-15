from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def default_config_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "VideoLibrary" / "config.json"
    return Path.home() / ".video-library" / "config.json"


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    config_path = Path(path) if path is not None else default_config_path()
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("config.json must contain a JSON object")
    return payload


def save_config(payload: dict[str, Any], path: Path | str | None = None) -> Path:
    config_path = Path(path) if path is not None else default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temp = config_path.with_suffix(config_path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, config_path)
    return config_path


def configured_video_root(*, config_path: Path | str | None = None, override: Path | str | None = None) -> Path | None:
    if override is not None:
        text = str(override).strip()
        return Path(text).expanduser() if text else None
    payload = load_config(config_path)
    value = payload.get("videoRoot")
    if value is None:
        return None
    text = str(value).strip()
    return Path(text).expanduser() if text else None


TMDB_TOKEN_ENV = "VIDEO_LIBRARY_TMDB_TOKEN"
TMDB_TOKEN_CONFIG_KEY = "tmdbReadAccessToken"


def configured_tmdb_token(*, config_path: Path | str | None = None) -> str | None:
    env_value = str(os.environ.get(TMDB_TOKEN_ENV) or "").strip()
    if env_value:
        return env_value
    payload = load_config(config_path)
    value = str(payload.get(TMDB_TOKEN_CONFIG_KEY) or "").strip()
    return value or None


def tmdb_token_source(*, config_path: Path | str | None = None) -> str:
    if str(os.environ.get(TMDB_TOKEN_ENV) or "").strip():
        return "environment"
    payload = load_config(config_path)
    if str(payload.get(TMDB_TOKEN_CONFIG_KEY) or "").strip():
        return "config"
    return "none"


def save_tmdb_token(token: str | None, *, config_path: Path | str | None = None) -> Path:
    payload = load_config(config_path)
    value = str(token or "").strip()
    if value:
        payload[TMDB_TOKEN_CONFIG_KEY] = value
    else:
        payload.pop(TMDB_TOKEN_CONFIG_KEY, None)
    return save_config(payload, config_path)
