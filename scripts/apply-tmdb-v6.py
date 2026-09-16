from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected text not found in {path}: {old!r}")
    target.write_text(text.replace(old, new), encoding="utf-8")


sync = Path("windows-installer/src/tmdb_sync.py")
text = sync.read_text(encoding="utf-8")
text = text.replace("_MATCHER_VERSION = 5", "_MATCHER_VERSION = 6")
text = text.replace("_SEARCH_CACHE_VERSION = 2", "_SEARCH_CACHE_VERSION = 3")
text = text.replace(
    '    "ブラッディマンデイ": ("BLOODY MONDAY",),\n}',
    '    "ブラッディマンデイ": ("BLOODY MONDAY",),\n'
    '    "trick": ("トリック",),\n'
    '    "トリック": ("TRICK",),\n'
    '    "goodluck": ("グッドラック", "グッドラック!!", "グッドラック！！"),\n'
    '    "グッドラック": ("GOOD LUCK!!", "GOOD LUCK"),\n'
    '}',
)
text = text.replace('return "tmdb:search:v2:" +', 'return "tmdb:search:v3:" +')
text = text.replace(
    "# v4実機監査でMATCHED 420件を確認済み。v5は検索経路の改善なので、\n"
    "        # v4 MATCHEDは保持し、REVIEW/UNMATCHEDだけを再検索する。",
    "# v5実機監査でMATCHED 424件を確認済み。v6は日本語別名検索の追加なので、\n"
    "        # v4以降のMATCHEDは保持し、REVIEW/UNMATCHEDだけを再検索する。",
)
sync.write_text(text, encoding="utf-8")

# Existing regression tests follow the current runtime matcher version.
for path in (
    "tests/test_tmdb_combined_media_v110.py",
    "tests/test_tmdb_audit_runtime_v110.py",
    "tests/test_tmdb_matcher_v3_v110.py",
):
    target = Path(path)
    value = target.read_text(encoding="utf-8").replace('\\"version\\":5', '\\"version\\":6')
    value = value.replace('["matcherVersion"], 5', '["matcherVersion"], 6')
    value = value.replace('["matcherVersion"], "5"', '["matcherVersion"], "6"')
    target.write_text(value, encoding="utf-8")

v5 = Path("tests/test_tmdb_matcher_v5_v110.py")
value = v5.read_text(encoding="utf-8")
value = value.replace("matcher v5", "matcher v6")
value = value.replace("test_search_cache_namespace_is_v2", "test_search_cache_namespace_is_v3")
value = value.replace('startswith("tmdb:search:v2:")', 'startswith("tmdb:search:v3:")')
value = value.replace('["matcherVersion"], 5', '["matcherVersion"], 6')
value = value.replace('\\"version\\":5', '\\"version\\":6')
v5.write_text(value, encoding="utf-8")

Path("tests/test_tmdb_matcher_v6_v110.py").write_text(r'''from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from tmdb_sync import _collect_candidates, _search_query_variants, _title_similarity, choose_candidate


class DummyConnection:
    def commit(self):
        return None


class JapaneseAliasClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int | None]] = []

    def search_movie(self, query, *, year=None, language="ja-JP"):
        return {"results": []}

    def search_tv(self, query, *, first_air_date_year=None, language="ja-JP"):
        self.calls.append((query, first_air_date_year))
        if query == "トリック" and first_air_date_year == 2000:
            return {"results": [{
                "id": 19616,
                "name": "トリック",
                "original_name": "TRICK",
                "first_air_date": "2000-07-07",
                "poster_path": "/trick.jpg",
                "backdrop_path": "/trick-bg.jpg",
                "overview": "TV drama",
            }]}
        if query == "グッドラック" and first_air_date_year == 2003:
            return {"results": [{
                "id": 2146,
                "name": "GOOD LUCK!!",
                "original_name": "GOOD LUCK!!",
                "first_air_date": "2003-01-19",
                "poster_path": "/goodluck.jpg",
                "backdrop_path": "/goodluck-bg.jpg",
                "overview": "TV drama",
            }]}
        return {"results": []}


class TmdbMatcherV6Tests(unittest.TestCase):
    def test_audited_japanese_aliases_are_searchable_and_equivalent(self):
        self.assertIn("トリック", _search_query_variants("TRICK"))
        self.assertIn("グッドラック", _search_query_variants("GOOD LUCK!!"))
        self.assertEqual(_title_similarity("TRICK", "トリック"), 1.0)
        self.assertEqual(_title_similarity("GOOD LUCK!!", "グッドラック"), 1.0)

    def _assert_alias_match(self, title: str, period: str, expected_id: int, expected_query: str, expected_year: int):
        work = {
            "category": "国内ドラマ",
            "year_or_period": period,
            "official_title": title,
            "source_title": title,
            "media_file_count": 10,
            "episode_count": 10,
            "movie_content_count": 0,
        }
        client = JapaneseAliasClient()
        with patch("tmdb_sync.get_cached_json", return_value=None), patch("tmdb_sync.put_cached_json"):
            candidates = _collect_candidates(DummyConnection(), client, work)
        status, selected, _ = choose_candidate(work, candidates)
        self.assertEqual(status, "MATCHED")
        self.assertIsNotNone(selected)
        self.assertEqual(selected.tmdb_id, expected_id)
        self.assertIn((expected_query, expected_year), client.calls)

    def test_trick_resolves_through_japanese_alias(self):
        self._assert_alias_match("TRICK", "2000-2003", 19616, "トリック", 2000)

    def test_good_luck_resolves_through_japanese_alias(self):
        self._assert_alias_match("GOOD LUCK!!", "2003", 2146, "グッドラック", 2003)


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")

Path("docs/49-1.1.0-tmdb-matcher-v6.md").write_text('''# 1.1.0 TMDb matcher v6\n\n## 実機監査\n\n2026-09-16 22:40生成の matcher v5 監査CSVを確認した。\n\n- 440作品\n- MATCHED 424\n- REVIEW 13\n- UNMATCHED 3\n\nv5で `LIAR GAME`、`BLOODY MONDAY`、`アンタッチャブル〜事件記者・鳴海遼子〜`、`妻は、くノ一〜最終章〜` は改善した。\n\n一方、正しいTMDb TVレコードが存在する `TRICK` と `GOOD LUCK!!` は、英字検索だけでは別作品が優先されていた。\n\n## v6修正\n\n- matcher versionを6へ更新。\n- search cache namespaceをv3へ更新。\n- 実機監査済みの日本語別名を検索・タイトル照合へ追加。\n  - `TRICK` ↔ `トリック`\n  - `GOOD LUCK!!` ↔ `グッドラック`\n- TMDb IDはマッチャーへ固定せず、検索結果から従来のタイトル・年・media contextで選択する。\n- v5でMATCHED済みの424件はAPI再検索せず保持する。\n- REVIEW / UNMATCHEDだけを再評価する。\n- 表示バージョンは1.1.0を維持する。\n\n## 安全策\n\n- 複数作品をまとめたライブラリ項目は従来どおり自動確定しない。\n- TMDb候補がない作品や低信頼候補を無理にMATCHEDへ昇格しない。\n- 元動画、字幕、再生状態は変更しない。\n\n## 回帰テスト\n\n- `TRICK` から日本語別名検索で2000年TV候補を取得できる。\n- `GOOD LUCK!!` から日本語別名検索で2003年TV候補を取得できる。\n- 日本語別名と英字タイトルのtitle similarityが1.0になる。\n- search cache namespaceがv3になる。\n- 既存のv4以降MATCHED保持を維持する。\n''', encoding="utf-8")

# Remove the temporary patch machinery before committing the actual product changes.
Path("scripts/apply-tmdb-v6.py").unlink()
Path(".github/workflows/apply-tmdb-v6.yml").unlink()
