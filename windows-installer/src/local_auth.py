from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
from dataclasses import dataclass
from http.cookies import SimpleCookie
from typing import Callable

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,256}$")
DEFAULT_ONE_TIME_TOKEN_TTL_SECONDS = 60
MIN_ONE_TIME_TOKEN_TTL_SECONDS = 10
MAX_ONE_TIME_TOKEN_TTL_SECONDS = 120
DEFAULT_SESSION_TTL_SECONDS = 12 * 60 * 60
SESSION_COOKIE_NAME = "video_library_owner_session"


@dataclass(frozen=True)
class SessionIssue:
    value: str
    max_age: int


class LocalOwnerAuth:
    """Local launcher -> browser owner authentication.

    The launcher and server share a per-process control secret. The launcher
    registers a short-lived one-time token; the browser exchanges it for an
    HttpOnly SameSite=Strict session cookie. Restarting the server invalidates
    all tokens and sessions.
    """

    def __init__(self, control_secret: str, *, clock: Callable[[], float] | None = None,
                 session_ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS) -> None:
        secret = str(control_secret or "")
        if len(secret) < 32:
            raise ValueError("control secret must contain at least 32 characters")
        if session_ttl_seconds < 60:
            raise ValueError("session ttl must be at least 60 seconds")
        self._secret = secret.encode("utf-8")
        self._clock = clock or time.monotonic
        self._session_ttl_seconds = int(session_ttl_seconds)
        self._one_time_tokens: dict[str, float] = {}
        self._sessions: dict[str, float] = {}
        self._lock = threading.Lock()

    @staticmethod
    def is_valid_token_format(value: str) -> bool:
        return bool(TOKEN_PATTERN.fullmatch(str(value or "")))

    def control_secret_matches(self, candidate: str) -> bool:
        return hmac.compare_digest(self._secret, str(candidate or "").encode("utf-8"))

    def _digest(self, value: str) -> str:
        return hmac.new(self._secret, value.encode("utf-8"), hashlib.sha256).hexdigest()

    def _purge_locked(self, now: float) -> None:
        self._one_time_tokens = {k: v for k, v in self._one_time_tokens.items() if v > now}
        self._sessions = {k: v for k, v in self._sessions.items() if v > now}

    def register_one_time_token(self, token: str, *, ttl_seconds: int = DEFAULT_ONE_TIME_TOKEN_TTL_SECONDS) -> int:
        if not self.is_valid_token_format(token):
            raise ValueError("one-time token format is invalid")
        ttl = max(MIN_ONE_TIME_TOKEN_TTL_SECONDS, min(int(ttl_seconds), MAX_ONE_TIME_TOKEN_TTL_SECONDS))
        now = float(self._clock())
        digest = self._digest(token)
        with self._lock:
            self._purge_locked(now)
            self._one_time_tokens[digest] = now + ttl
        return ttl

    def consume_one_time_token(self, token: str) -> bool:
        if not self.is_valid_token_format(token):
            return False
        now = float(self._clock())
        digest = self._digest(token)
        with self._lock:
            expiry = self._one_time_tokens.pop(digest, None)
            self._purge_locked(now)
        return expiry is not None and expiry > now

    def issue_session(self) -> SessionIssue:
        raw = secrets.token_urlsafe(48)
        now = float(self._clock())
        with self._lock:
            self._purge_locked(now)
            self._sessions[self._digest(raw)] = now + self._session_ttl_seconds
        return SessionIssue(raw, self._session_ttl_seconds)

    def validate_session(self, value: str) -> bool:
        if not self.is_valid_token_format(value):
            return False
        now = float(self._clock())
        digest = self._digest(value)
        with self._lock:
            expiry = self._sessions.get(digest)
            self._purge_locked(now)
        return expiry is not None and expiry > now


def cookie_value(cookie_header: str | None, name: str = SESSION_COOKIE_NAME) -> str:
    if not cookie_header:
        return ""
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header)
    except Exception:
        return ""
    morsel = cookie.get(name)
    return str(morsel.value) if morsel else ""


def session_cookie_header(issue: SessionIssue, *, secure: bool = False) -> str:
    parts = [f"{SESSION_COOKIE_NAME}={issue.value}", "Path=/", "HttpOnly", "SameSite=Strict", f"Max-Age={issue.max_age}"]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)
