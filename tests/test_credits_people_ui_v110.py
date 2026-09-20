from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from app_version import APP_VERSION
from library_service import _work_filters


class CreditsPeopleUiV110Tests(unittest.TestCase):
    def test_version_and_installer_match_current_release(self):
        self.assertEqual(APP_VERSION, "1.2.3")
        installer = (ROOT / "windows-installer" / "installer" / "VideoLibrary.iss").read_text(encoding="utf-8")
        self.assertIn('#define MyAppVersion "1.2.3"', installer)

    def test_work_search_already_includes_director_and_cast(self):
        sql, params = _work_filters("テスト出演者", None)
        self.assertIn("director_or_direction", sql)
        self.assertIn("main_cast_or_voice_actors", sql)
        self.assertEqual(len(params), 4)
        self.assertTrue(all(value == "%テスト出演者%" for value in params))

    def test_ui_displays_credits_and_person_route(self):
        html = (SRC / "video-library.html").read_text(encoding="utf-8")
        self.assertIn("監督／演出", html)
        self.assertIn("主な出演者／声優", html)
        self.assertIn("splitCreditPeople", html)
        self.assertIn("creditRow", html)
        self.assertIn("#/person/${encodeURIComponent(name)}", html)
        self.assertIn(r"/^#\/person\/(.+)$/", html)
        self.assertIn("人物「", html)

    def test_credit_split_does_not_split_foreign_name_middle_dot(self):
        html = (SRC / "video-library.html").read_text(encoding="utf-8")
        splitter = html[html.index("function splitCreditPeople"):html.index("function creditRow")]
        self.assertNotIn("|・", splitter)


if __name__ == "__main__":
    unittest.main()
