from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'marker not found: {path}: {old[:120]!r}')
    p.write_text(text.replace(old, new, 1), encoding='utf-8')


path = 'windows-installer/src/tmdb_sync.py'
replace_once(
    path,
    '_UNMATCHED = "UNMATCHED"\n',
    '_UNMATCHED = "UNMATCHED"\n_MATCHER_VERSION = 2\n_MATCHER_VERSION_CACHE_KEY = "tmdb:matcher-version"\n',
)
replace_once(
    path,
    '''def _media_types_for(category: str | None) -> tuple[str, ...]:\n    text = str(category or "")\n    if "映画" in text:\n        return ("movie",)\n    if "ドラマ" in text:\n        return ("tv",)\n    return ("movie", "tv")\n''',
    '''def _media_types_for(category: str | None) -> tuple[str, ...]:\n    text = str(category or "")\n    has_movie = "映画" in text\n    has_tv = "ドラマ" in text or "テレビ" in text\n    if has_movie and has_tv:\n        return ("movie", "tv")\n    if has_movie:\n        return ("movie",)\n    if has_tv:\n        return ("tv",)\n    return ("movie", "tv")\n\n\ndef _stored_matcher_version(connection: sqlite3.Connection) -> int:\n    payload = get_cached_json(connection, _MATCHER_VERSION_CACHE_KEY)\n    if not isinstance(payload, dict):\n        return 0\n    try:\n        return int(payload.get("version") or 0)\n    except (TypeError, ValueError):\n        return 0\n\n\ndef _store_matcher_version(connection: sqlite3.Connection) -> None:\n    put_cached_json(\n        connection,\n        _MATCHER_VERSION_CACHE_KEY,\n        {"version": _MATCHER_VERSION},\n        fetched_at=now_iso(),\n        expires_at=None,\n    )\n''',
)
replace_once(
    path,
    '''        total = len(works)\n        for index, work in enumerate(works, start=1):\n''',
    '''        total = len(works)\n        force_reassess = _stored_matcher_version(connection) < _MATCHER_VERSION\n        for index, work in enumerate(works, start=1):\n''',
)
replace_once(
    path,
    '''            if existing is not None and existing["match_status"] == _MATCHED and existing["tmdb_id"]:\n''',
    '''            if (\n                not force_reassess\n                and existing is not None\n                and existing["match_status"] == _MATCHED\n                and existing["tmdb_id"]\n            ):\n''',
)
# Store matcher version only after all works have been processed successfully.
replace_once(
    path,
    '''            if progress_callback is not None:\n                progress_callback(\n''',
    '''            if progress_callback is not None:\n                progress_callback(\n''',
)
# Insert marker before summary construction after loop. Use the exact summary marker.
replace_once(
    path,
    '''        summary = {\n''',
    '''        _store_matcher_version(connection)\n        connection.commit()\n        summary = {\n''',
)

# Add regression tests.
test_path = Path('tests/test_tmdb_combined_media_v110.py')
test_path.write_text(r'''from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from database import connect, initialize_database, now_iso
from tmdb_sync import _media_types_for, sync_tmdb_library


class CombinedClient:
    def __init__(self):
        self.movie_calls = 0
        self.tv_calls = 0

    def search_movie(self, query, *, year=None, language="ja-JP"):
        self.movie_calls += 1
        return {"results": []}

    def search_tv(self, query, *, first_air_date_year=None, language="ja-JP"):
        self.tv_calls += 1
        return {"results": [{
            "id": 1396,
            "name": "ブレイキング・バッド",
            "original_name": "Breaking Bad",
            "first_air_date": "2008-01-20",
            "poster_path": "/bb.jpg",
            "backdrop_path": "/bb-bg.jpg",
            "overview": "TV series",
        }]}


def seed_combined_work(db: Path) -> int:
    with connect(db) as connection:
        initialize_database(connection)
        stamp = now_iso()
        connection.execute(
            """
            INSERT INTO works(
                external_work_no,category,year_or_period,source_title,official_title,
                media_file_count,subtitle_file_count,subfolder_count,created_at,updated_at
            ) VALUES(1,'海外映画・ドラマ','2008','Breaking Bad','ブレイキング・バッド',1,0,0,?,?)
            """,
            (stamp, stamp),
        )
        work_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        # Simulate a MATCHED row produced by matcher v1. It must be reassessed once.
        connection.execute(
            """
            INSERT INTO tmdb_work_links(
                work_id,media_type,tmdb_id,match_status,confidence,matched_title,matched_year,
                created_at,updated_at
            ) VALUES(?, 'movie', 999, 'MATCHED', 1.0, 'Wrong Movie', '2008', ?, ?)
            """,
            (work_id, stamp, stamp),
        )
        connection.commit()
        return work_id


class CombinedMediaMatchingTests(unittest.TestCase):
    def test_combined_categories_search_movie_and_tv(self):
        self.assertEqual(_media_types_for("日本映画・ドラマ"), ("movie", "tv"))
        self.assertEqual(_media_types_for("海外映画・ドラマ"), ("movie", "tv"))
        self.assertEqual(_media_types_for("日本映画"), ("movie",))
        self.assertEqual(_media_types_for("国内ドラマ"), ("tv",))

    def test_v1_existing_match_is_reassessed_once_and_tv_can_win(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "library.db"
            image_root = root / "TMDbImages"
            reports = root / "diagnostics"
            work_id = seed_combined_work(db)
            client = CombinedClient()

            def fake_download(remote_path, destination, *, size):
                destination = Path(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"image")
                return destination

            report = sync_tmdb_library(
                db, image_root, reports, "token", client=client, image_downloader=fake_download
            )
            self.assertEqual(report["summary"]["matched"], 1)
            self.assertGreater(client.movie_calls, 0)
            self.assertGreater(client.tv_calls, 0)
            with connect(db) as connection:
                row = connection.execute(
                    "SELECT media_type,tmdb_id,match_status FROM tmdb_work_links WHERE work_id=?",
                    (work_id,),
                ).fetchone()
                self.assertEqual(row["media_type"], "tv")
                self.assertEqual(int(row["tmdb_id"]), 1396)
                self.assertEqual(row["match_status"], "MATCHED")
                marker = connection.execute(
                    "SELECT payload_json FROM tmdb_api_cache WHERE cache_key='tmdb:matcher-version'"
                ).fetchone()
                self.assertIn('"version":2', marker["payload_json"])

            # Matcher v2 marker protects the confirmed result on later syncs.
            second_client = CombinedClient()
            second = sync_tmdb_library(
                db, image_root, reports, "token", client=second_client, image_downloader=fake_download
            )
            self.assertEqual(second["items"][0]["reason"], "EXISTING_MATCH")
            self.assertEqual(second_client.movie_calls, 0)
            self.assertEqual(second_client.tv_calls, 0)


if __name__ == "__main__":
    unittest.main()
''', encoding='utf-8')

# Documentation.
doc = Path('docs/43-1.1.0-tmdb-combined-media-fix.md')
doc.write_text('''# 1.1.0-a2 TMDb複合カテゴリ照合修正\n\n## 実機監査で判明した問題\n\n2026-09-15の440作品監査で、`日本映画・ドラマ` / `海外映画・ドラマ` がmovieのみ検索されていた。\n原因はカテゴリ文字列に「映画」が含まれるとmovieのみを返す判定順序だった。\n\n## 修正\n\n- 「映画」と「ドラマ」の両方を含むカテゴリはmovie/tv両方を検索する。\n- 単独映画カテゴリはmovie、単独ドラマカテゴリはtvを維持する。\n- matcher version 2 をDB内TMDbキャッシュへ記録する。\n- version 2へ初回移行するときだけ、旧matcherで作られた既存MATCHEDも再評価する。\n- 再評価が最後まで成功した場合だけversion markerを保存する。中断時は次回再試行する。\n- version 2移行後の既存MATCHEDは従来どおり保護する。\n- REVIEW/UNMATCHEDではTMDb画像URLを公開しない既存安全策を維持する。\n\n## 実機再監査\n\n修正版でTMDb同期を再実行し、440作品のMATCHED/REVIEW/UNMATCHEDと誤マッチを再確認する。\n特に日本ドラマと「ブレイキング・バッド」がtv候補として評価されることを確認する。\n''', encoding='utf-8')

# README note.
readme = Path('README.md')
text = readme.read_text(encoding='utf-8')
section = '''\n\n### TMDb複合カテゴリ照合（1.1.0-a2）\n\n`日本映画・ドラマ` / `海外映画・ドラマ` はmovieとtvの両方を検索します。旧ロジックで作成された既存MATCHEDはmatcher version 2への初回移行時だけ再評価し、その後は従来どおり確定済みMATCHEDを保護します。\n'''
if 'TMDb複合カテゴリ照合（1.1.0-a2）' not in text:
    readme.write_text(text.rstrip() + section + '\n', encoding='utf-8')
