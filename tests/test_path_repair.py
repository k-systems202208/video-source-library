from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from database import connect
from metadata_importer import import_file
from sample_metadata import build_metadata
from scan_runner import relaxed_path_matches, scan_library
from scanner import normalize_relative_path, resolve_video_file


class RelaxedPathMatchingTests(unittest.TestCase):
    def test_question_mark_matches_one_diacritic_character_only(self):
        self.assertTrue(relaxed_path_matches(
            "movie/F?ten/Torajir?.mkv",
            "movie/Fūten/Torajirō.mkv",
        ))
        self.assertTrue(relaxed_path_matches(
            "movie/B?ky?.mkv",
            "movie/Bōkyō.mkv",
        ))
        self.assertFalse(relaxed_path_matches(
            "movie/F?ten/Torajir?.mkv",
            "movie/Fūten/Torajiro-extra.mkv",
        ))
        self.assertFalse(relaxed_path_matches(
            "movie/F?ten/Torajir?.mkv",
            "other/Fūten/Torajirō.mkv",
        ))


class PathRepairScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.db = base / "library.db"
        self.root = base / "videos"
        self.root.mkdir()
        metadata = base / "fixture.json"
        self.payload = build_metadata(work_count=6, video_count=6)
        metadata.write_text(json.dumps(self.payload, ensure_ascii=False), encoding="utf-8")
        import_file(metadata, self.db)

    def tearDown(self):
        self.temp.cleanup()

    def _create_other_exact_files(self) -> None:
        for work in self.payload["works"]:
            for entry in work["files"]:
                if entry["file_no"] == 1:
                    continue
                relative = normalize_relative_path(entry["relative_path"])
                path = self.root.joinpath(*relative.split("/"))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"video-{entry['file_no']}".encode("ascii"))

    def test_unique_unicode_candidate_repairs_catalog_before_scan(self):
        corrupted = "sample/work-001/F?ten-Torajir?.mp4"
        actual = "sample/work-001/Fūten-Torajirō.mp4"
        with connect(self.db) as connection:
            connection.execute(
                """
                UPDATE video_files
                SET relative_path=?, filename=?
                WHERE video_id=(SELECT id FROM videos WHERE external_file_no=1)
                """,
                (corrupted, "F?ten-Torajir?.mp4"),
            )
            connection.commit()

        first = self.root.joinpath(*actual.split("/"))
        first.parent.mkdir(parents=True, exist_ok=True)
        first.write_bytes(b"first-video")
        first.with_suffix(".ja.srt").write_text("WEBVTT\n", encoding="utf-8")
        self._create_other_exact_files()

        with patch("scanner.find_ffprobe", return_value=None):
            with connect(self.db) as connection:
                result = scan_library(connection, self.root)
                self.assertEqual(result["pathsRepaired"], 1)
                self.assertEqual(result["pathRepairAmbiguous"], 0)
                self.assertEqual(result["filesMatched"], 6)
                self.assertEqual(result["filesMissing"], 0)
                self.assertEqual(result["filesNew"], 0)

                row = connection.execute(
                    """
                    SELECT vf.video_id, vf.source_subfolder, vf.filename,
                           vf.relative_path, vf.extension, vf.scan_status
                    FROM video_files vf
                    JOIN videos v ON v.id=vf.video_id
                    WHERE v.external_file_no=1
                    """
                ).fetchone()
                self.assertEqual(row["relative_path"], actual)
                self.assertEqual(row["filename"], "Fūten-Torajirō.mp4")
                self.assertEqual(row["extension"], "MP4")
                self.assertEqual(row["source_subfolder"], "Season 1")
                self.assertEqual(row["scan_status"], "MATCHED")
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM scan_discoveries").fetchone()[0], 0)

                subtitle = connection.execute(
                    "SELECT video_id, match_method FROM subtitles WHERE relative_path=?",
                    ("sample/work-001/Fūten-Torajirō.ja.srt",),
                ).fetchone()
                self.assertIsNotNone(subtitle)
                self.assertEqual(int(subtitle["video_id"]), int(row["video_id"]))
                self.assertNotEqual(subtitle["match_method"], "UNMATCHED")

                resolved = resolve_video_file(connection, self.root, int(row["video_id"]))
                self.assertIsNotNone(resolved)
                self.assertEqual(resolved[0], first.resolve())

        self.assertTrue(first.is_file())

    def test_ambiguous_candidates_are_not_repaired(self):
        corrupted = "sample/work-001/Torajir?.mp4"
        with connect(self.db) as connection:
            connection.execute(
                """
                UPDATE video_files
                SET relative_path=?, filename=?
                WHERE video_id=(SELECT id FROM videos WHERE external_file_no=1)
                """,
                (corrupted, "Torajir?.mp4"),
            )
            connection.commit()

        for name in ("Torajirō.mp4", "Torajirū.mp4"):
            path = self.root / "sample" / "work-001" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode("utf-8"))
        self._create_other_exact_files()

        with patch("scanner.find_ffprobe", return_value=None):
            with connect(self.db) as connection:
                result = scan_library(connection, self.root)
                self.assertEqual(result["pathsRepaired"], 0)
                self.assertEqual(result["pathRepairAmbiguous"], 1)
                self.assertEqual(result["filesMatched"], 5)
                self.assertEqual(result["filesMissing"], 1)
                self.assertEqual(result["filesNew"], 2)
                row = connection.execute(
                    """
                    SELECT relative_path, scan_status
                    FROM video_files vf JOIN videos v ON v.id=vf.video_id
                    WHERE v.external_file_no=1
                    """
                ).fetchone()
                self.assertEqual(row["relative_path"], corrupted)
                self.assertEqual(row["scan_status"], "MISSING")


if __name__ == "__main__":
    unittest.main()
