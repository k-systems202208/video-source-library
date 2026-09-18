from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReleaseWorkflowV110Tests(unittest.TestCase):
    def test_release_workflow_has_safe_automatic_release_contract(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("branches: [main]", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("contents: write", workflow)
        self.assertIn("APP_VERSION", workflow)
        self.assertIn("gh release view", workflow)
        self.assertIn("should_release=false", workflow)
        self.assertIn("should_release=true", workflow)
        self.assertIn("Build Windows installer", workflow)
        self.assertIn("Verify and package release assets", workflow)
        self.assertIn("gh @args", workflow)
        self.assertIn("VideoLibrary-Windows-Installer-", workflow)

    def test_110_release_notes_exist_and_describe_current_runtime(self):
        notes = (ROOT / "docs" / "80-1.1.0-release.md").read_text(encoding="utf-8")
        for expected in (
            "# 自宅動画ライブラリ 1.1.0",
            "SQLite schema: 7",
            "TMDb matcher: 8",
            "people sync: 9",
            "people audit: 8",
            "関町北映画館UI",
        ):
            self.assertIn(expected, notes)


if __name__ == "__main__":
    unittest.main()
