from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from tmdb_sync import (
    Candidate,
    _AUDIT_FORCE_REASSESS_WORKS,
    _MATCHER_VERSION,
    choose_candidate,
)


def candidate(media_type: str, tmdb_id: int, title: str, year: str) -> Candidate:
    return Candidate(
        media_type=media_type,
        tmdb_id=tmdb_id,
        title=title,
        year=year,
        poster_path="/poster.jpg",
        backdrop_path="/backdrop.jpg",
        overview="",
        title_similarity=1.0,
        year_similarity=1.0,
        confidence=1.0,
    )


class TmdbMatcherV8Tests(unittest.TestCase):
    def test_matcher_version_is_8(self):
        self.assertEqual(_MATCHER_VERSION, 8)

    def test_half_moon_2006_is_never_auto_matched_to_anime_tmdb_record(self):
        work = {
            "official_title": "半分の月がのぼる空",
            "year_or_period": "2006",
            "category": "日本映画・ドラマ",
            "media_file_count": 13,
            "episode_count": 13,
            "movie_content_count": 0,
        }
        status, selected, reason = choose_candidate(
            work,
            [candidate("tv", 34746, "半分の月がのぼる空", "2006")],
        )
        self.assertEqual(status, "UNMATCHED")
        self.assertIsNotNone(selected)
        self.assertEqual(selected.tmdb_id, 34746)
        self.assertEqual(reason, "AUDIT_SPECIAL_STRUCTURE")

    def test_half_moon_existing_match_is_marked_for_one_time_reassessment(self):
        self.assertIn(("半分の月がのぼる空", "2006"), _AUDIT_FORCE_REASSESS_WORKS)

    def test_sync_source_does_not_retain_force_reassess_signature_as_existing_match(self):
        source = (SRC / "tmdb_sync.py").read_text(encoding="utf-8")
        self.assertIn("_work_audit_key(work) not in _AUDIT_FORCE_REASSESS_WORKS", source)
        self.assertNotIn(
            '("半分の月がのぼる空", "2006"): ("tv", 34746, "2006")',
            source,
        )


if __name__ == "__main__":
    unittest.main()
