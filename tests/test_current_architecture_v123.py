from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from app_version import APP_VERSION
from database import SCHEMA_VERSION
from tmdb_people import _PEOPLE_AUDIT_VERSION, _PEOPLE_SYNC_VERSION
from tmdb_sync import _MATCHER_VERSION


class CurrentArchitectureV123Tests(unittest.TestCase):
    def test_current_versions_are_kept_in_sync(self):
        self.assertEqual(APP_VERSION, "1.2.3")
        self.assertEqual(SCHEMA_VERSION, 8)
        self.assertEqual(_MATCHER_VERSION, 8)
        self.assertEqual(_PEOPLE_SYNC_VERSION, 10)
        self.assertEqual(_PEOPLE_AUDIT_VERSION, 9)

    def test_pwa_shell_is_current_and_excludes_runtime_data(self):
        sw = (SRC / "service-worker.js").read_text(encoding="utf-8")
        self.assertIn("video-library-shell-v6", sw)
        for prefix in (
            "/api/",
            "/video/",
            "/subtitle/",
            "/tmdb-image/",
            "/tmdb-person-image/",
        ):
            self.assertIn(prefix, sw)

        manifest = json.loads((SRC / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "関町北映画館")

    def test_current_design_docs_match_people_alias_patch(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        basic = (ROOT / "docs" / "00-basic-design.md").read_text(encoding="utf-8")
        database = (ROOT / "docs" / "01-database-design.md").read_text(encoding="utf-8")
        screen = (ROOT / "docs" / "02-screen-design.md").read_text(encoding="utf-8")
        api = (ROOT / "docs" / "03-api-design.md").read_text(encoding="utf-8")
        people_patch = (ROOT / "docs" / "87-1.2.3-stephen-alpert-alias.md").read_text(
            encoding="utf-8"
        )
        release = (ROOT / "docs" / "88-1.2.3-release.md").read_text(encoding="utf-8")

        self.assertIn("1.2.3: ジブリ追加後の人物別名補正（現行）", readme)
        self.assertIn("v1.2.3 基本設計", basic)
        self.assertIn("現行schemaは **8**", database)
        self.assertIn("作品名フィルター", screen)
        self.assertNotIn("/api/admin/works/visibility", api)
        self.assertIn("Stephen Alpert", people_patch)
        self.assertIn("# 自宅動画ライブラリ 1.2.3", release)


if __name__ == "__main__":
    unittest.main()
