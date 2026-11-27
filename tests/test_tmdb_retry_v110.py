from __future__ import annotations

import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from tmdb_client import TmdbClient, TmdbError


class FakeResponse:
    def __init__(self, body: bytes = b'{"ok":true}') -> None:
        self._body = body
        self.closed = False

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:
        self.closed = True


def http_error(code: int, retry_after: str | None = None) -> HTTPError:
    headers = {}
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPError("https://api.themoviedb.org/3/search/tv", code, "temporary", headers, None)


class TmdbRetryTests(unittest.TestCase):
    def test_http_502_is_retried_then_succeeds(self):
        calls = []
        sleeps = []

        def opener(request, timeout):
            calls.append(request.full_url)
            if len(calls) == 1:
                raise http_error(502)
            return FakeResponse()

        client = TmdbClient(
            "secret-token",
            opener=opener,
            max_retries=3,
            retry_base_seconds=0.25,
            sleeper=sleeps.append,
        )
        self.assertEqual(client.get_json("/configuration"), {"ok": True})
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleeps, [0.25])
        self.assertNotIn("secret-token", calls[0])

    def test_retry_after_is_respected_for_429(self):
        calls = 0
        sleeps = []

        def opener(request, timeout):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise http_error(429, "2")
            return FakeResponse()

        client = TmdbClient("token", opener=opener, sleeper=sleeps.append)
        self.assertEqual(client.get_json("/configuration"), {"ok": True})
        self.assertEqual(calls, 2)
        self.assertEqual(sleeps, [2.0])

    def test_401_fails_without_retry(self):
        calls = 0
        sleeps = []

        def opener(request, timeout):
            nonlocal calls
            calls += 1
            raise http_error(401)

        client = TmdbClient("secret-token", opener=opener, sleeper=sleeps.append)
        with self.assertRaises(TmdbError) as captured:
            client.get_json("/configuration")
        self.assertEqual(str(captured.exception), "TMDb API returned HTTP 401")
        self.assertEqual(calls, 1)
        self.assertEqual(sleeps, [])
        self.assertNotIn("secret-token", str(captured.exception))

    def test_503_exhausts_initial_attempt_plus_three_retries(self):
        calls = 0
        sleeps = []

        def opener(request, timeout):
            nonlocal calls
            calls += 1
            raise http_error(503)

        client = TmdbClient(
            "token",
            opener=opener,
            max_retries=3,
            retry_base_seconds=0.5,
            sleeper=sleeps.append,
        )
        with self.assertRaises(TmdbError) as captured:
            client.get_json("/configuration")
        self.assertEqual(str(captured.exception), "TMDb API returned HTTP 503")
        self.assertEqual(calls, 4)
        self.assertEqual(sleeps, [0.5, 1.0, 2.0])

    def test_connection_failure_is_retried_then_succeeds(self):
        calls = 0
        sleeps = []

        def opener(request, timeout):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise URLError("temporary network failure")
            return FakeResponse()

        client = TmdbClient(
            "token",
            opener=opener,
            max_retries=2,
            retry_base_seconds=0.1,
            sleeper=sleeps.append,
        )
        self.assertEqual(client.get_json("/configuration"), {"ok": True})
        self.assertEqual(calls, 2)
        self.assertEqual(sleeps, [0.1])


if __name__ == "__main__":
    unittest.main()
