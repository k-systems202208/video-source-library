from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from email.header import decode_header
from typing import Any, Mapping
from urllib.parse import urlparse

TAILSCALE_LOGIN_HEADER = "Tailscale-User-Login"
TAILSCALE_NAME_HEADER = "Tailscale-User-Name"
TAILSCALE_PROFILE_HEADER = "Tailscale-User-Profile-Pic"
MAX_LOGIN_LENGTH = 512
MAX_DISPLAY_NAME_LENGTH = 200
MAX_PROFILE_URL_LENGTH = 2048


@dataclass(frozen=True)
class TailscaleIdentity:
    subject: str
    login_name: str
    display_name: str
    profile_picture_url: str


def _single_header_value(headers: Any, name: str) -> str:
    get_all = getattr(headers, "get_all", None)
    if callable(get_all):
        values = get_all(name)
        if values is None or len(values) != 1:
            return ""
        return str(values[0] or "")
    if isinstance(headers, Mapping):
        matches = [v for k, v in headers.items() if str(k).casefold() == name.casefold()]
        if len(matches) != 1:
            return ""
        return str(matches[0] or "")
    getter = getattr(headers, "get", None)
    return str(getter(name, "") or "") if callable(getter) else ""


def decode_identity_header(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parts = decode_header(raw)
    except Exception:
        parts = [(raw, None)]
    out: list[str] = []
    for part, charset in parts:
        if isinstance(part, str):
            out.append(part)
            continue
        decoded = None
        for encoding in ([str(charset)] if charset else []) + ["utf-8", "latin-1"]:
            try:
                decoded = part.decode(encoding)
                break
            except (LookupError, UnicodeDecodeError):
                pass
        out.append(decoded if decoded is not None else part.decode("utf-8", errors="replace"))
    return unicodedata.normalize("NFKC", "".join(out)).strip()


def _has_control(value: str) -> bool:
    return any(unicodedata.category(ch) == "Cc" for ch in value)


def normalize_login(value: str) -> str:
    decoded = decode_identity_header(value)
    if not decoded or len(decoded) > MAX_LOGIN_LENGTH or _has_control(decoded):
        return ""
    return decoded.casefold()


def normalize_display_name(value: str, *, fallback: str) -> str:
    decoded = decode_identity_header(value)
    if not decoded or len(decoded) > MAX_DISPLAY_NAME_LENGTH or _has_control(decoded):
        decoded = decode_identity_header(fallback)
    return (decoded or "Tailscale利用者")[:MAX_DISPLAY_NAME_LENGTH]


def normalize_profile_picture_url(value: str) -> str:
    decoded = decode_identity_header(value)
    if not decoded or len(decoded) > MAX_PROFILE_URL_LENGTH or _has_control(decoded):
        return ""
    parsed = urlparse(decoded)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        return ""
    return decoded


def parse_tailscale_identity(headers: Any) -> TailscaleIdentity | None:
    raw_login = _single_header_value(headers, TAILSCALE_LOGIN_HEADER)
    subject = normalize_login(raw_login)
    if not subject:
        return None
    login_name = decode_identity_header(raw_login)
    display_name = normalize_display_name(_single_header_value(headers, TAILSCALE_NAME_HEADER), fallback=login_name or subject)
    profile = normalize_profile_picture_url(_single_header_value(headers, TAILSCALE_PROFILE_HEADER))
    return TailscaleIdentity(subject, login_name or subject, display_name, profile)
