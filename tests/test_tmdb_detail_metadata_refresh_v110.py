from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from tmdb_client import TmdbClient
from tmdb_sync import Candidate, _IMAGE_CACHE_REPAIR_VERSION, _refresh_matched_candidate_details


class Response:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")
    def read(self):
        return self._body
    def close(self):
        pass


class TmdbDetailMetadataRefreshV110Tests(unittest.TestCase):
    def test_client_fetches_tv_details(self):
        seen = []
        def opener(request, timeout):
            seen.append(request.full_url)
            return Response({"id": 19616, "name": "トリック"})
        client = TmdbClient("token", opener=opener, max_retries=0)
        payload = client.tv_details(19616)
        self.assertEqual(payload["id"], 19616)
        self.assertIn("/tv/19616?language=ja-JP", seen[0])

    def test_refresh_replaces_stale_backdrop_metadata_without_rematching(self):
        class FakeClient:
            def tv_details(self, tv_id, *, language="ja-JP"):
                self.called = (tv_id, language)
                return {
                    "id": 19616,
                    "name": "トリック",
                    "first_air_date": "2000-07-07",
                    "poster_path": "/correct-poster.jpg",
                    "backdrop_path": "/correct-backdrop.jpg",
                    "overview": "correct overview",
                }
        old = Candidate(
            "tv", 19616, "トリック", "2000",
            "/correct-poster.jpg", "/wrong-backdrop.jpg", "old overview",
            1.0, 1.0, 1.0,
        )
        client = FakeClient()
        refreshed = _refresh_matched_candidate_details(client, old)
        self.assertEqual(client.called, (19616, "ja-JP"))
        self.assertEqual(refreshed.tmdb_id, 19616)
        self.assertEqual(refreshed.poster_path, "/correct-poster.jpg")
        self.assertEqual(refreshed.backdrop_path, "/correct-backdrop.jpg")
        self.assertEqual(refreshed.overview, "correct overview")
        self.assertEqual(refreshed.confidence, old.confidence)

    def test_detail_id_mismatch_is_rejected(self):
        class FakeClient:
            def tv_details(self, tv_id, *, language="ja-JP"):
                return {"id": 99999, "name": "wrong"}
        old = Candidate("tv", 19616, "トリック", "2000", "/p.jpg", "/b.jpg", "", 1.0, 1.0, 1.0)
        with self.assertRaises(ValueError):
            _refresh_matched_candidate_details(FakeClient(), old)

    def test_repair_version_is_incremented_for_existing_run167_installs(self):
        self.assertEqual(_IMAGE_CACHE_REPAIR_VERSION, 2)


if __name__ == "__main__":
    unittest.main()
