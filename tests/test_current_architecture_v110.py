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


class CurrentArchitectureV110Tests(unittest.TestCase):
    def test_current_versions_are_kept_in_sync(self):
        self.assertEqual(APP_VERSION, "1.1.0")
        self.assertEqual(SCHEMA_VERSION, 7)
        self.assertEqual(_MATCHER_VERSION, 8)
        self.assertEqual(_PEOPLE_SYNC_VERSION, 9)
        self.assertEqual(_PEOPLE_AUDIT_VERSION, 8)

    def test_pwa_shell_is_current_and_excludes_runtime_data(self):
        sw = (SRC / "service-worker.js").read_text(encoding="utf-8")
        self.assertIn("video-library-shell-v4", sw)
        for prefix in (
            "/api/",
            "/video/",
            "/subtitle/",
            "/tmdb-image/",
            "/tmdb-person-image/",
        ):
            self.assertIn(prefix, sw)

        offline = (SRC / "offline.html").read_text(encoding="utf-8")
        self.assertIn("<title>関町北映画館</title>", offline)
        self.assertIn("<h1>関町北映画館</h1>", offline)

        manifest = json.loads((SRC / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "関町北映画館")
        self.assertEqual(manifest["short_name"], "関町北映画館")
        self.assertEqual(manifest["background_color"], "#100d0b")
        self.assertEqual(manifest["theme_color"], "#120e0c")

    def test_current_design_docs_match_runtime_architecture(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        basic = (ROOT / "docs" / "00-basic-design.md").read_text(encoding="utf-8")
        database = (ROOT / "docs" / "01-database-design.md").read_text(encoding="utf-8")
        screen = (ROOT / "docs" / "02-screen-design.md").read_text(encoding="utf-8")
        api = (ROOT / "docs" / "03-api-design.md").read_text(encoding="utf-8")
        images = (ROOT / "docs" / "42-1.1.0-tmdb-matching-images.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("SQLiteは現行schema 7", readme)
        self.assertIn("作品matcherはversion 8", readme)
        self.assertIn("人物同期version 9", readme)
        self.assertIn("人物監査version 8", readme)
        self.assertIn("監督／演出」は名前・作品数のテキスト名鑑のみ", readme)
        self.assertNotIn("レトロ映画館UIは次段階で追加", readme)

        self.assertIn("v1.1.0 基本設計", basic)
        self.assertIn("現行schemaは **7**", database)
        self.assertIn("#/people/directors", screen)
        self.assertIn("/api/people?role=director|cast", api)
        self.assertIn("<work_id>-<remote_path_hash>.<ext>", images)


if __name__ == "__main__":
    unittest.main()
