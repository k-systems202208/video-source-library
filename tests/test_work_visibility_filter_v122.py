from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from work_visibility import filter_work_visibility


class WorkVisibilityFilterV122Tests(unittest.TestCase):
    def setUp(self):
        self.items = [
            {"id": 1, "title": "電車男", "visible": True},
            {"id": 2, "title": "Train Man", "visible": True},
            {"id": 3, "title": "新幹線大爆破", "visible": False},
            {"id": 4, "title": "男はつらいよ", "visible": True},
        ]

    def test_partial_title_match(self):
        result = filter_work_visibility(self.items, "男")
        self.assertEqual([item["id"] for item in result], [1, 4])

    def test_filter_is_case_insensitive_and_nfkc_normalized(self):
        result = filter_work_visibility(self.items, "  ＴＲＡＩＮ  ")
        self.assertEqual([item["id"] for item in result], [2])

    def test_blank_filter_returns_all_in_original_order(self):
        result = filter_work_visibility(self.items, "   ")
        self.assertEqual([item["id"] for item in result], [1, 2, 3, 4])

    def test_no_match_returns_empty_list(self):
        self.assertEqual(filter_work_visibility(self.items, "存在しない作品"), [])

    def test_filter_does_not_change_visibility_values(self):
        result = filter_work_visibility(self.items, "新幹線")
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]["visible"])
        self.assertFalse(self.items[2]["visible"])

    def test_launcher_has_live_filter_controls_and_preserves_bound_variables(self):
        launcher = (SRC / "launcher.py").read_text(encoding="utf-8")
        self.assertIn('text="作品名フィルター"', launcher)
        self.assertIn('text="クリア"', launcher)
        self.assertIn('filter_text.trace_add("write", apply_filter)', launcher)
        self.assertIn("filter_work_visibility(works, filter_text.get())", launcher)
        self.assertIn("row_widgets: dict[int, ttk.Checkbutton]", launcher)
        self.assertIn("variable=variables[work_id]", launcher)
        self.assertIn('filter_count.set(f"表示 {len(matches):,} / 全{len(works):,}作品")', launcher)


if __name__ == "__main__":
    unittest.main()
