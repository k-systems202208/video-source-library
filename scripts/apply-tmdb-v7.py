from pathlib import Path


sync = Path("windows-installer/src/tmdb_sync.py")
text = sync.read_text(encoding="utf-8")
text = text.replace("_MATCHER_VERSION = 6", "_MATCHER_VERSION = 7")

alias_end = '''    "goodluck": ("グッドラック", "グッドラック!!", "グッドラック！！"),
    "グッドラック": ("GOOD LUCK!!", "GOOD LUCK"),
}
'''
audit_constants = '''    "goodluck": ("グッドラック", "グッドラック!!", "グッドラック！！"),
    "グッドラック": ("GOOD LUCK!!", "GOOD LUCK"),
}

# 2026-09-16の440作品実機監査で候補内容まで人手確認した確定シグネチャ。
# generic matcherの閾値は緩めず、ローカル作品名/期間とTMDb候補の種別・ID・開始年が
# すべて一致した場合だけ監査承認として確定する。
_AUDIT_APPROVED_MATCHES: dict[tuple[str, str], tuple[str, int, str]] = {
    ("進撃の巨人", ""): ("tv", 1429, "2013"),
    ("誰にも言えない", "1993"): ("tv", 36167, "1993"),
    ("こんな恋のはなし", "1997"): ("tv", 9327, "1997"),
    ("牙狼〈GARO〉", "2005-2006"): ("tv", 1941, "2005"),
    ("半分の月がのぼる空", "2006"): ("tv", 34746, "2006"),
    ("SUMMER NUDE", "2013"): ("tv", 64293, "2013"),
    ("夜行観覧車", "2013"): ("tv", 81864, "2013"),
    ("信長協奏曲", "2014"): ("tv", 62911, "2014"),
    ("仰げば尊し", "2016"): ("tv", 83474, "2016"),
}

# 1つのTMDb作品へ自動確定してはいけないローカル集約項目。
_AUDIT_AGGREGATE_WORKS: set[tuple[str, str]] = {
    ("男はつらいよ", "1969-2019"),
    ("仁義なき戦い", "1973-1974"),
    ("福岡恋愛白書", "2011-2016"),
    ("殺人分析班シリーズ", "2016-2019"),
}

# TMDbのシリーズ構造とローカル管理単位が一致しないため自動紐付けしない項目。
_AUDIT_SPECIAL_UNMATCHED: set[tuple[str, str]] = {
    ("3年B組金八先生 第6シリーズ", "2001"),
}
'''
if alias_end not in text:
    raise SystemExit("alias insertion point not found")
text = text.replace(alias_end, audit_constants, 1)

work_value_block = '''def _work_value(work: sqlite3.Row | dict[str, Any], key: str, default: Any = None) -> Any:
    if isinstance(work, sqlite3.Row):
        return work[key] if key in work.keys() else default
    return work.get(key, default)
'''
work_value_plus = work_value_block + '''

def _work_audit_key(work: sqlite3.Row | dict[str, Any]) -> tuple[str, str]:
    return (
        str(_work_value(work, "official_title", "") or "").strip(),
        str(_work_value(work, "year_or_period", "") or "").strip(),
    )


def _audit_approved_candidate(
    work: sqlite3.Row | dict[str, Any],
    candidates: Iterable[Candidate],
) -> Candidate | None:
    expected = _AUDIT_APPROVED_MATCHES.get(_work_audit_key(work))
    if expected is None:
        return None
    media_type, tmdb_id, matched_year = expected
    for candidate in candidates:
        if (
            candidate.media_type == media_type
            and candidate.tmdb_id == tmdb_id
            and candidate.year == matched_year
        ):
            return candidate
    return None
'''
if work_value_block not in text:
    raise SystemExit("work_value insertion point not found")
text = text.replace(work_value_block, work_value_plus, 1)

choose_head = '''    ranked = sorted(
        candidates,
        key=lambda item: (_candidate_rank_score(work, item), item.confidence, item.title_similarity),
        reverse=True,
    )
    if not ranked:
        return _UNMATCHED, None, "NO_CANDIDATE"

    top = ranked[0]
'''
choose_v7 = '''    ranked = sorted(
        candidates,
        key=lambda item: (_candidate_rank_score(work, item), item.confidence, item.title_similarity),
        reverse=True,
    )
    audit_key = _work_audit_key(work)

    if audit_key in _AUDIT_SPECIAL_UNMATCHED:
        return _UNMATCHED, ranked[0] if ranked else None, "AUDIT_SPECIAL_STRUCTURE"

    if audit_key in _AUDIT_AGGREGATE_WORKS:
        return _REVIEW, ranked[0] if ranked else None, "AUDIT_AGGREGATE_REVIEW"

    approved = _audit_approved_candidate(work, ranked)
    if approved is not None:
        return _MATCHED, approved, "AUDIT_APPROVED"

    if not ranked:
        return _UNMATCHED, None, "NO_CANDIDATE"

    top = ranked[0]
'''
if choose_head not in text:
    raise SystemExit("choose_candidate insertion point not found")
text = text.replace(choose_head, choose_v7, 1)

text = text.replace(
    "# v5実機監査でMATCHED 424件を確認済み。v6は日本語別名検索の追加なので、\n"
    "        # v4以降のMATCHEDは保持し、REVIEW/UNMATCHEDだけを再検索する。",
    "# v6実機監査でMATCHED 426件を確認済み。v7は監査承認と特殊項目の整理なので、\n"
    "        # v4以降のMATCHEDは保持し、REVIEW/UNMATCHEDだけを再評価する。",
)
sync.write_text(text, encoding="utf-8")

# Existing tests that assert the current runtime matcher marker follow v7.
for target in Path("tests").glob("test_tmdb*.py"):
    value = target.read_text(encoding="utf-8")
    value = value.replace('\\"version\\":6', '\\"version\\":7')
    value = value.replace('["matcherVersion"], 6', '["matcherVersion"], 7')
    value = value.replace('["matcherVersion"], "6"', '["matcherVersion"], "7"')
    target.write_text(value, encoding="utf-8")

Path("tests/test_tmdb_matcher_v7_v110.py").write_text(r'''from __future__ import annotations

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
''', encoding="utf-8")

Path("docs/50-1.1.0-tmdb-audit-finalization-v7.md").write_text('''# 1.1.0 TMDb matcher v7 - 実機監査の確定処理\n\n## 実機監査結果\n\n2026-09-16 23:04生成のmatcher v6監査CSVを440作品すべて確認した。\n\n- MATCHED: 426\n- REVIEW: 12\n- UNMATCHED: 2\n- `TRICK` と `GOOD LUCK!!` はv6で正しいTV候補へ改善。\n- 既知の誤マッチ25件と表記差6件も正しい候補を維持。\n\n## v7の目的\n\n検索閾値を緩めず、実機監査で候補内容まで確認済みの9件だけを明示的に承認する。\n\n承認はローカル作品名・ローカル期間・media type・TMDb ID・TMDb開始年の完全一致を必要とし、どれか1つでも異なれば適用しない。\n\n承認対象:\n\n- 進撃の巨人 / tv 1429 / 2013\n- 誰にも言えない / tv 36167 / 1993\n- こんな恋のはなし / tv 9327 / 1997\n- 牙狼〈GARO〉 / tv 1941 / 2005\n- 半分の月がのぼる空 / tv 34746 / 2006\n- SUMMER NUDE / tv 64293 / 2013\n- 夜行観覧車 / tv 81864 / 2013\n- 信長協奏曲 / tv 62911 / 2014\n- 仰げば尊し / tv 83474 / 2016\n\n## 集合・特殊項目\n\n次の4件は複数作品を1つのローカル項目として管理しているため、単一TMDb作品へ自動確定しない。\n\n- 男はつらいよ\n- 仁義なき戦い\n- 福岡恋愛白書\n- 殺人分析班シリーズ\n\n`3年B組金八先生 第6シリーズ` はTMDbのシリーズ構造とローカル管理単位が一致しないため、自動紐付けせずUNMATCHEDを維持する。\n\n## 期待結果\n\n- MATCHED: 435\n- REVIEW: 4\n- UNMATCHED: 1\n\nこれを通常の自動検索精度改善の完了条件とする。集合・特殊項目は別途UI/データモデル側で扱う。\n''', encoding="utf-8")

# Temporary patch machinery is removed from the product commit.
Path("scripts/apply-tmdb-v7.py").unlink()
Path(".github/workflows/apply-tmdb-v7.yml").unlink()
