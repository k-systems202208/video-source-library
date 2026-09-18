from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TMDB_API_BASE = "https://api.themoviedb.org/3"
_CREDENTIAL_QUERY_NAMES = {"api_key", "access_token", "token", "authorization"}
_RETRYABLE_HTTP_STATUS = {429, 502, 503, 504}


class TmdbError(RuntimeError):
    pass


class TmdbClient:
    def __init__(
        self,
        access_token: str,
        *,
        opener: Callable[..., Any] = urlopen,
        timeout: float = 15.0,
        max_retries: int = 3,
        retry_base_seconds: float = 1.0,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        token = str(access_token or "").strip()
        if not token:
            raise ValueError("TMDb API Read Access Token is required")
        if int(max_retries) < 0:
            raise ValueError("max_retries must be 0 or greater")
        if float(retry_base_seconds) < 0:
            raise ValueError("retry_base_seconds must be 0 or greater")
        self._access_token = token
        self._opener = opener
        self._timeout = timeout
        self._max_retries = int(max_retries)
        self._retry_base_seconds = float(retry_base_seconds)
        self._sleeper = sleeper

    def _retry_after_seconds(self, error: HTTPError) -> float | None:
        headers = getattr(error, "headers", None)
        if headers is None:
            return None
        value = headers.get("Retry-After")
        if value in (None, ""):
            return None
        text = str(value).strip()
        try:
            return max(0.0, float(text))
        except ValueError:
            pass
        try:
            retry_at = parsedate_to_datetime(text)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            return max(0.0, (retry_at.astimezone(timezone.utc) - now).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None

    def _retry_delay(self, retry_index: int, error: HTTPError | None = None) -> float:
        if error is not None:
            retry_after = self._retry_after_seconds(error)
            if retry_after is not None:
                return retry_after
        return self._retry_base_seconds * (2 ** retry_index)

    def get_json(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        endpoint = str(path or "").strip()
        if not endpoint.startswith("/") or endpoint.startswith("//"):
            raise ValueError("TMDb path must be an API-relative path")
        query = dict(params or {})
        if any(str(key).lower() in _CREDENTIAL_QUERY_NAMES for key in query):
            raise ValueError("credentials must not be placed in TMDb query parameters")
        encoded = urlencode([(str(k), str(v)) for k, v in query.items() if v is not None])
        url = TMDB_API_BASE + endpoint + ("?" + encoded if encoded else "")
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "Accept": "application/json",
            },
            method="GET",
        )

        last_http_code: int | None = None
        last_connection_error = False
        for attempt in range(self._max_retries + 1):
            try:
                response = self._opener(request, timeout=self._timeout)
                try:
                    body = response.read()
                finally:
                    close = getattr(response, "close", None)
                    if callable(close):
                        close()
                break
            except HTTPError as exc:
                last_http_code = int(exc.code)
                if last_http_code not in _RETRYABLE_HTTP_STATUS or attempt >= self._max_retries:
                    raise TmdbError(f"TMDb API returned HTTP {last_http_code}") from None
                self._sleeper(self._retry_delay(attempt, exc))
            except (URLError, TimeoutError, OSError):
                last_connection_error = True
                if attempt >= self._max_retries:
                    raise TmdbError("TMDb API connection failed") from None
                self._sleeper(self._retry_delay(attempt))
        else:
            if last_http_code is not None:
                raise TmdbError(f"TMDb API returned HTTP {last_http_code}")
            if last_connection_error:
                raise TmdbError("TMDb API connection failed")
            raise TmdbError("TMDb API request failed")

        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise TmdbError("TMDb API returned invalid JSON") from None

    def configuration(self) -> dict[str, Any]:
        value = self.get_json("/configuration")
        return value if isinstance(value, dict) else {}

    def search_movie(self, query: str, *, year: str | int | None = None, language: str = "ja-JP") -> dict[str, Any]:
        params: dict[str, Any] = {"query": query, "language": language, "include_adult": "false"}
        if year not in (None, ""):
            params["year"] = year
        value = self.get_json("/search/movie", params)
        return value if isinstance(value, dict) else {}

    def search_tv(self, query: str, *, first_air_date_year: str | int | None = None, language: str = "ja-JP") -> dict[str, Any]:
        params: dict[str, Any] = {"query": query, "language": language, "include_adult": "false"}
        if first_air_date_year not in (None, ""):
            params["first_air_date_year"] = first_air_date_year
        value = self.get_json("/search/tv", params)
        return value if isinstance(value, dict) else {}

    def search_person(self, query: str, *, language: str = "ja-JP") -> dict[str, Any]:
        value = self.get_json(
            "/search/person",
            {"query": query, "language": language, "include_adult": "false"},
        )
        return value if isinstance(value, dict) else {}

    def person_combined_credits(self, person_id: int, *, language: str = "ja-JP") -> dict[str, Any]:
        value = self.get_json(
            f"/person/{int(person_id)}/combined_credits",
            {"language": language},
        )
        return value if isinstance(value, dict) else {}

    def movie_details(self, movie_id: int, *, language: str = "ja-JP") -> dict[str, Any]:
        value = self.get_json(f"/movie/{int(movie_id)}", {"language": language})
        return value if isinstance(value, dict) else {}

    def tv_details(self, tv_id: int, *, language: str = "ja-JP") -> dict[str, Any]:
        value = self.get_json(f"/tv/{int(tv_id)}", {"language": language})
        return value if isinstance(value, dict) else {}

    def movie_credits(self, movie_id: int, *, language: str = "ja-JP") -> dict[str, Any]:
        value = self.get_json(f"/movie/{int(movie_id)}/credits", {"language": language})
        return value if isinstance(value, dict) else {}

    def tv_aggregate_credits(self, tv_id: int, *, language: str = "ja-JP") -> dict[str, Any]:
        value = self.get_json(f"/tv/{int(tv_id)}/aggregate_credits", {"language": language})
        return value if isinstance(value, dict) else {}
