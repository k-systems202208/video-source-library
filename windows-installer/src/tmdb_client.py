from __future__ import annotations

import json
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TMDB_API_BASE = "https://api.themoviedb.org/3"
_CREDENTIAL_QUERY_NAMES = {"api_key", "access_token", "token", "authorization"}


class TmdbError(RuntimeError):
    pass


class TmdbClient:
    def __init__(
        self,
        access_token: str,
        *,
        opener: Callable[..., Any] = urlopen,
        timeout: float = 15.0,
    ) -> None:
        token = str(access_token or "").strip()
        if not token:
            raise ValueError("TMDb API Read Access Token is required")
        self._access_token = token
        self._opener = opener
        self._timeout = timeout

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
        try:
            response = self._opener(request, timeout=self._timeout)
            try:
                body = response.read()
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
        except HTTPError as exc:
            raise TmdbError(f"TMDb API returned HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError):
            raise TmdbError("TMDb API connection failed") from None
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

    def movie_details(self, tmdb_id: int, *, language: str = "ja-JP") -> dict[str, Any]:
        value = self.get_json(f"/movie/{int(tmdb_id)}", {"language": language})
        return value if isinstance(value, dict) else {}

    def tv_details(self, tmdb_id: int, *, language: str = "ja-JP") -> dict[str, Any]:
        value = self.get_json(f"/tv/{int(tmdb_id)}", {"language": language})
        return value if isinstance(value, dict) else {}
