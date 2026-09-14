from __future__ import annotations

import base64
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
_BOOTSTRAP_PREFIX = b"VideoLibraryOwnerBootstrapV1\0"
_BOOTSTRAP_NONCE_BYTES = 16
_BOOTSTRAP_SIGNATURE_BYTES = 32
_BOOTSTRAP_PAYLOAD_BYTES = 8 + _BOOTSTRAP_NONCE_BYTES + _BOOTSTRAP_SIGNATURE_BYTES


@dataclass(frozen=True)
class SessionIssue:
    value: str
    max_age: int


def _normalized_secret(control_secret: str) -> bytes:
    secret = str(control_secret or "")
    if len(secret) < 32:
        raise ValueError("control secret must contain at least 32 characters")
    return secret.encode("utf-8")


def create_bootstrap_token(
    control_secret: str,
    *,
    ttl_seconds: int = DEFAULT_ONE_TIME_TOKEN_TTL_SECONDS,
    now: float | None = None,
) -> str:
    """Create a self-contained short-lived owner bootstrap token.

    Launcher and server run in the same process and share the control secret,
    so the launcher does not need to register the token through localhost HTTP.
    The server verifies this HMAC-signed token when the browser exchanges it.
    """
    secret = _normalized_secret(control_secret)
    ttl = max(MIN_ONE_TIME_TOKEN_TTL_SECONDS, min(int(ttl_seconds), MAX_ONE_TIME_TOKEN_TTL_SECONDS))
    issued_at = int(time.time() if now is None else now)
    expires_at = issued_at + ttl
    body = expires_at.to_bytes(8, "big") + secrets.token_bytes(_BOOTSTRAP_NONCE_BYTES)
    signature = hmac.new(secret, _BOOTSTRAP_PREFIX + body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(body + signature).rstrip(b"=").decode("ascii")


class LocalOwnerAuth:
    """Local launcher -> browser owner authentication.

    The launcher and server share a per-process control secret. The normal
    Windows launcher creates an HMAC-signed short-lived bootstrap token without
    any localhost HTTP registration. The browser exchanges it for an HttpOnly
    SameSite=Strict session cookie. Legacy registered one-time tokens remain
    supported for compatibility and tests. Restarting the server invalidates
    sessions and replay state.
    """

    def __init__(self, control_secret: str, *, clock: Callable[[], float] | None = None,
                 session_ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS) -> None:
        self._secret = _normalized_secret(control_secret)
        if session_ttl_seconds < 60:
            raise ValueError("session ttl must be at least 60 seconds")
        self._clock = clock or time.monotonic
        self._session_ttl_seconds = int(session_ttl_seconds)
        self._one_time_tokens: dict[str, float] = {}
        self._consumed_bootstrap_tokens: dict[str, float] = {}
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

    def _consume_bootstrap_token(self, token: str) -> bool:
        try:
            padding = "=" * ((4 - len(token) % 4) % 4)
            raw = base64.urlsafe_b64decode((token + padding).encode("ascii"))
        except Exception:
            return False
        if len(raw) != _BOOTSTRAP_PAYLOAD_BYTES:
            return False
        body = raw[:8 + _BOOTSTRAP_NONCE_BYTES]
        signature = raw[8 + _BOOTSTRAP_NONCE_BYTES:]
        expected = hmac.new(self._secret, _BOOTSTRAP_PREFIX + body, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            return False
        expires_at = int.from_bytes(body[:8], "big")
        now = time.time()
        if expires_at <= now or expires_at > now + MAX_ONE_TIME_TOKEN_TTL_SECONDS + 5:
            return False
        digest = self._digest(token)
        with self._lock:
            self._consumed_bootstrap_tokens = {
                k: v for k, v in self._consumed_bootstrap_tokens.items() if v > now
            }
            if digest in self._consumed_bootstrap_tokens:
                return False
            self._consumed_bootstrap_tokens[digest] = float(expires_at)
        return True

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
        if expiry is not None:
            return expiry > now
        return self._consume_bootstrap_token(token)

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
