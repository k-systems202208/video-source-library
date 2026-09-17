from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected 1 match, found {count}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


sync = ROOT / "windows-installer" / "src" / "tmdb_sync.py"
replace_once(sync, '_IMAGE_CACHE_REPAIR_VERSION = 2', '_IMAGE_CACHE_REPAIR_VERSION = 3')
replace_once(
    sync,
    '''# v3時代に誤MATCHEDだったTRICKは、後続matcherでtv/19616へ修正されても
# workId.jpg が残り続けたため、既存インストールで一度だけ画像を取り直す。
_LEGACY_STALE_IMAGE_WORKS: set[tuple[str, str]] = {
    ("TRICK", "2000-2003"),
}
''',
    '''# 過去の誤候補画像が workId 名のローカルキャッシュとして残った作品。
# matcherの既存MATCHEDは維持し、TMDb詳細を同じIDから再取得して画像だけ取り直す。
# タイトルは _normalize_title() 後の値で保持し、全角/半角記号などの表記揺れに耐える。
_STALE_IMAGE_REPAIR_WORKS: set[tuple[str, str]] = {
    ("trick", "2000-2003"),
    ("pricelessあるわけねぇだろんなもん", "2012"),
    ("スマイル", "2009"),
    ("ビギナーズ", "2012"),
    ("プライド", "2004"),
}
''',
)
needle = '''def _work_audit_key(work: sqlite3.Row | dict[str, Any]) -> tuple[str, str]:
    return (
        str(_work_value(work, "official_title", "") or "").strip(),
        str(_work_value(work, "year_or_period", "") or "").strip(),
    )


'''
replacement = needle + '''def _requires_image_cache_repair(work: sqlite3.Row | dict[str, Any]) -> bool:
    period = str(_work_value(work, "year_or_period", "") or "").strip()
    titles = {
        _normalize_title(_work_value(work, "official_title", "")),
        _normalize_title(_work_value(work, "source_title", "")),
    }
    titles.discard("")
    return any((title, period) in _STALE_IMAGE_REPAIR_WORKS for title in titles)


'''
replace_once(sync, needle, replacement)
text = sync.read_text(encoding="utf-8")
old_expr = '_work_audit_key(work) in _LEGACY_STALE_IMAGE_WORKS'
if text.count(old_expr) != 2:
    raise RuntimeError(f"expected 2 legacy repair checks, found {text.count(old_expr)}")
sync.write_text(text.replace(old_expr, '_requires_image_cache_repair(work)'), encoding="utf-8")

server = ROOT / "windows-installer" / "src" / "server.py"
server_text = server.read_text(encoding="utf-8")
old_cache = 'self._common(cache="public, max-age=3600")'
if server_text.count(old_cache) != 1:
    raise RuntimeError(f"server image cache marker count={server_text.count(old_cache)}")
server.write_text(server_text.replace(old_cache, 'self._common(cache="no-store")', 1), encoding="utf-8")

html = ROOT / "windows-installer" / "src" / "video-library.html"
replace_once(html, '.brand{justify-self:center}.header-search-wrap{grid-column:2;grid-row:1;justify-self:stretch}', 'header .brand{justify-self:start}.header-search-wrap{grid-column:2;grid-row:1;justify-self:stretch}')

metadata_test = ROOT / "tests" / "test_tmdb_detail_metadata_refresh_v110.py"
replace_once(metadata_test, 'self.assertEqual(_IMAGE_CACHE_REPAIR_VERSION, 2)', 'self.assertEqual(_IMAGE_CACHE_REPAIR_VERSION, 3)')

new_test = ROOT / "tests" / "test_tmdb_multi_image_repair_v110.py"
new_test.write_text(r'''from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from database import connect, initialize_database, now_iso
from tmdb_cache import put_cached_json
from tmdb_sync import _IMAGE_CACHE_REPAIR_VERSION, _requires_image_cache_repair, sync_tmdb_library


class ExistingMatchClient:
    def __init__(self):
        self.detail_calls = []

    def search_movie(self, *args, **kwargs):
        raise AssertionError("existing MATCHED must not be rematched")

    def search_tv(self, *args, **kwargs):
        raise AssertionError("existing MATCHED must not be rematched")

    def tv_details(self, tv_id, *, language="ja-JP"):
        self.detail_calls.append((tv_id, language))
        return {
            "id": tv_id,
            "name": "スマイル",
            "first_air_date": "2009-04-17",
            "poster_path": "/correct-smile-poster.jpg",
            "backdrop_path": "/correct-smile-backdrop.jpg",
            "overview": "correct",
        }


class TmdbMultiImageRepairV110Tests(unittest.TestCase):
    def test_repair_version_is_three(self):
        self.assertEqual(_IMAGE_CACHE_REPAIR_VERSION, 3)

    def test_all_reported_titles_and_trick_are_repair_targets(self):
        cases = [
            ("TRICK", "2000-2003"),
            ("PRICELESS〜あるわけねぇだろ、んなもん!〜", "2012"),
            ("スマイル", "2009"),
            ("ビギナーズ!", "2012"),
            ("ビギナーズ！", "2012"),
            ("プライド", "2004"),
        ]
        for title, period in cases:
            with self.subTest(title=title):
                self.assertTrue(_requires_image_cache_repair({
                    "official_title": title,
                    "source_title": "",
                    "year_or_period": period,
                }))
        self.assertFalse(_requires_image_cache_repair({
            "official_title": "プライド", "source_title": "", "year_or_period": "2005"
        }))

    def test_existing_tmdb_id_is_preserved_while_both_images_are_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "library.db"
            images = root / "TMDbImages"
            reports = root / "diagnostics"
            with connect(db) as connection:
                initialize_database(connection)
                stamp = now_iso()
                connection.execute(
                    """
                    INSERT INTO works(
                        external_work_no,category,year_or_period,source_title,official_title,
                        media_file_count,subtitle_file_count,subfolder_count,created_at,updated_at
                    ) VALUES(1,'日本映画・ドラマ','2009','Smile','スマイル',11,0,1,?,?)
                    """,
                    (stamp, stamp),
                )
                work_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
                connection.execute(
                    """
                    INSERT INTO tmdb_work_links(
                        work_id,media_type,tmdb_id,match_status,confidence,matched_title,matched_year,
                        poster_path,backdrop_path,overview,synced_at,created_at,updated_at
                    ) VALUES(?, 'tv', 18819, 'MATCHED', 1.0, 'スマイル', '2009',
                             '/old-poster.jpg', '/old-backdrop.jpg', 'old', ?, ?, ?)
                    """,
                    (work_id, stamp, stamp, stamp),
                )
                put_cached_json(connection, "tmdb:matcher-version", {"version": 7}, fetched_at=stamp, expires_at=None)
                put_cached_json(connection, "tmdb:image-cache-repair-version", {"version": 2}, fetched_at=stamp, expires_at=None)
                connection.commit()

            poster = images / "poster" / f"{work_id}.jpg"
            backdrop = images / "backdrop" / f"{work_id}.jpg"
            poster.parent.mkdir(parents=True)
            backdrop.parent.mkdir(parents=True)
            poster.write_bytes(b"wrong poster")
            backdrop.write_bytes(b"wrong backdrop")

            def downloader(remote_path, destination, *, size):
                target = Path(destination)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(f"{remote_path}:{size}".encode("utf-8"))
                return target

            client = ExistingMatchClient()
            result = sync_tmdb_library(
                db, images, reports, "token", client=client, image_downloader=downloader
            )
            self.assertEqual(client.detail_calls, [(18819, "ja-JP")])
            self.assertEqual(result["summary"]["matcherVersion"], 7)
            self.assertNotEqual(poster.read_bytes(), b"wrong poster")
            self.assertNotEqual(backdrop.read_bytes(), b"wrong backdrop")
            self.assertIn(b"correct-smile-poster", poster.read_bytes())
            self.assertIn(b"correct-smile-backdrop", backdrop.read_bytes())

            with connect(db) as connection:
                row = connection.execute(
                    "SELECT media_type,tmdb_id,poster_path,backdrop_path FROM tmdb_work_links WHERE work_id=?",
                    (work_id,),
                ).fetchone()
                self.assertEqual(row["media_type"], "tv")
                self.assertEqual(int(row["tmdb_id"]), 18819)
                self.assertEqual(row["poster_path"], "/correct-smile-poster.jpg")
                self.assertEqual(row["backdrop_path"], "/correct-smile-backdrop.jpg")

    def test_tmdb_images_are_not_browser_cached_after_repair(self):
        source = (SRC / "server.py").read_text(encoding="utf-8")
        segment = source[source.index("def _serve_tmdb_image"):source.index("def do_GET")]
        self.assertIn('self._common(cache="no-store")', segment)
        self.assertNotIn("max-age=3600", segment)

    def test_desktop_header_brand_is_left_aligned_only_in_desktop_rule(self):
        html = (SRC / "video-library.html").read_text(encoding="utf-8")
        desktop = html[html.index("@media(min-width:1200px){"):html.index("@media(min-width:768px) and (max-width:1199px){")]
        self.assertIn("header .brand{justify-self:start}", desktop)


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")

doc = ROOT / "docs" / "61-1.1.0-four-tmdb-image-repair-header.md"
doc.write_text('''# 1.1.0 4作品TMDb画像キャッシュ修復 / ヘッダー左寄せ

## 対象

- PRICELESS〜あるわけねぇだろ、んなもん!〜 (2012)
- スマイル (2009)
- ビギナーズ! / ビギナーズ！ (2012)
- プライド (2004)
- 既存修復対象の TRICK (2000-2003) も継続

## 原因

TMDbリンクが正しい候補へ更新された後でも、ポスター・背景のローカルキャッシュは `workId` をファイル名として保持するため、過去の誤候補画像が残ることがある。TRICKで確認済みの同種事象。

## 対応

- matcherVersion 7は変更しない。
- image cache repair versionを3へ更新。
- 対象作品は既存MATCHEDの `media_type / tmdb_id` を維持し、同じTMDb IDの詳細APIから最新 `poster_path / backdrop_path / overview` を再取得する。
- ポスターと背景の既存キャッシュを両方削除して再ダウンロードする。
- 対象タイトル判定をNFKC・英数字/かな漢字ベースで正規化し、全角/半角記号差を吸収する。
- `/tmdb-image/...` は `Cache-Control: no-store` とし、修復直後にブラウザが古い画像を再利用しないようにする。
- 1200px以上のPCレイアウトだけヘッダー看板を左寄せし、Tablet/Smartphoneは既存配置を維持する。

## 実機確認

最新版を上書き後、ランチャーからTMDb同期を1回実行する。対象4作品のポスターと詳細背景が正しい日本ドラマ画像へ更新されることを確認する。
''', encoding="utf-8")
