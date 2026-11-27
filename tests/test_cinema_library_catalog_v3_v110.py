from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "windows-installer" / "src" / "video-library.html"


class CinemaLibraryCatalogV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = HTML.read_text(encoding="utf-8")

    def test_catalog_v3_marker_and_headings_exist(self) -> None:
        self.assertIn("CINEMA_LIBRARY_CATALOG_V3", self.html)
        self.assertIn("PRIVATE SCREENING CATALOG", self.html)
        self.assertIn("作品目録 <small>CATALOG</small>", self.html)
        self.assertIn("ARCHIVED TITLES", self.html)

    def test_catalog_search_order_and_category_are_preserved(self) -> None:
        self.assertIn('id="search"', self.html)
        self.assertIn('id="sort"', self.html)
        self.assertIn('id="categories"', self.html)
        self.assertIn("目録検索 <small>SEARCH</small>", self.html)
        self.assertIn("並び順 <small>ORDER</small>", self.html)
        self.assertIn("GENRE / CATEGORY", self.html)

    def test_catalog_count_tracks_filtered_total(self) -> None:
        self.assertIn('id="catalogCount"', self.html)
        self.assertIn("catalogCount.textContent=`${Number(d.total||0).toLocaleString()} 作品`", self.html)

    def test_home_sections_and_existing_behaviour_remain(self) -> None:
        self.assertIn("上映中 <small>NOW SHOWING</small>", self.html)
        self.assertIn("次回上映 <small>COMING SOON</small>", self.html)
        self.assertIn("makeOpenable(c,()=>openInWork(x.workId,x.videoId))", self.html)
        self.assertIn("makeOpenable(c,()=>{location.hash=`#/work/${w.id}`})", self.html)
        self.assertIn("const PAGE=60", self.html)

    def test_detail_v2_is_retained(self) -> None:
        self.assertIn("CINEMA_LIBRARY_DETAIL_V2", self.html)
        self.assertIn("FEATURE PRESENTATION", self.html)
        self.assertIn("上映プログラム", self.html)
        self.assertIn("上映目録", self.html)


if __name__ == "__main__":
    unittest.main()
