from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from tmdb_sync import Candidate, choose_candidate


def candidate(media_type: str, tmdb_id: int, title: str, year: str, confidence: float = 1.0) -> Candidate:
    return Candidate(
        media_type, tmdb_id, title, year, "/poster.jpg", "/backdrop.jpg", "",
        1.0, 1.0, confidence,
    )


class TmdbMatcherV7Tests(unittest.TestCase):
    def test_audit_approved_signature_promotes_review_candidate(self):
        work = {
            "official_title": "誰にも言えない",
            "year_or_period": "1993",
            "category": "日本映画・ドラマ",
            "media_file_count": 12,
            "episode_count": 0,
            "movie_content_count": 0,
        }
        status, selected, reason = choose_candidate(
            work,
            [candidate("tv", 36167, "誰にも言えない", "1993")],
        )
        self.assertEqual(status, "MATCHED")
        self.assertEqual(selected.tmdb_id, 36167)
        self.assertEqual(reason, "AUDIT_APPROVED")

    def test_audit_approval_requires_exact_tmdb_signature(self):
        work = {
            "official_title": "SUMMER NUDE",
            "year_or_period": "2013",
            "category": "日本映画・ドラマ",
            "media_file_count": 11,
            "episode_count": 0,
            "movie_content_count": 0,
        }
        wrong = candidate("tv", 999999, "SUMMER NUDE", "2013", 0.81)
        status, selected, reason = choose_candidate(work, [wrong])
        self.assertNotEqual(reason, "AUDIT_APPROVED")
        self.assertNotEqual(status, "MATCHED")
        self.assertEqual(selected.tmdb_id, 999999)

    def test_missing_local_year_can_still_use_explicit_audit_signature(self):
        work = {
            "official_title": "進撃の巨人",
            "year_or_period": "",
            "category": "アニメ",
            "media_file_count": 87,
            "episode_count": 87,
            "movie_content_count": 0,
        }
        status, selected, reason = choose_candidate(
            work,
            [candidate("tv", 1429, "進撃の巨人", "2013", 0.925)],
        )
        self.assertEqual(status, "MATCHED")
        self.assertEqual(selected.tmdb_id, 1429)
        self.assertEqual(reason, "AUDIT_APPROVED")

    def test_aggregate_work_is_never_auto_matched(self):
        work = {
            "official_title": "殺人分析班シリーズ",
            "year_or_period": "2016-2019",
            "category": "日本映画・ドラマ",
            "media_file_count": 20,
            "episode_count": 20,
            "movie_content_count": 0,
        }
        status, selected, reason = choose_candidate(
            work,
            [candidate("tv", 95854, "蝶の力学 殺人分析班", "2019")],
        )
        self.assertEqual(status, "REVIEW")
        self.assertEqual(selected.tmdb_id, 95854)
        self.assertEqual(reason, "AUDIT_AGGREGATE_REVIEW")

    def test_special_local_series_unit_stays_unmatched(self):
        work = {
            "official_title": "3年B組金八先生 第6シリーズ",
            "year_or_period": "2001",
            "category": "日本映画・ドラマ",
            "media_file_count": 23,
            "episode_count": 23,
            "movie_content_count": 0,
        }
        status, selected, reason = choose_candidate(
            work,
            [candidate("tv", 12345, "3年B組金八先生", "2001")],
        )
        self.assertEqual(status, "UNMATCHED")
        self.assertEqual(selected.tmdb_id, 12345)
        self.assertEqual(reason, "AUDIT_SPECIAL_STRUCTURE")


if __name__ == "__main__":
    unittest.main()
