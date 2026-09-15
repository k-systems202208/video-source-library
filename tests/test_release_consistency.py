from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(SCRIPTS))

from app_version import APP_VERSION
import launcher
import server
from validate_real_library import build_parser, collect_validation_failures


class ReleaseConsistencyTests(unittest.TestCase):
    def test_version_is_shared_across_python_and_installer(self):
        self.assertEqual(APP_VERSION, "0.9.4")
        self.assertEqual(launcher.APP_VERSION, APP_VERSION)
        self.assertEqual(server.APP_VERSION, APP_VERSION)
        installer = (ROOT / "windows-installer" / "installer" / "VideoLibrary.iss").read_text(
            encoding="utf-8"
        )
        self.assertIn(f'#define MyAppVersion "{APP_VERSION}"', installer)

    def test_real_validation_defaults_match_verified_library(self):
        args = build_parser().parse_args(
            ["--database", "library.db", "--video-root", "D:/Videos"]
        )
        self.assertEqual(args.expected_works, 440)
        self.assertEqual(args.expected_videos, 4869)
        self.assertEqual(args.expected_subtitles, 1234)
        self.assertEqual(args.expected_matched_subtitles, 1227)
        self.assertEqual(args.expected_orphan_subtitles, 7)
        self.assertEqual(args.expected_unsupported_subtitles, 3)

    def test_orphan_subtitles_are_normal_but_ambiguous_unmatched_are_not(self):
        args = build_parser().parse_args(
            ["--database", "library.db", "--video-root", "D:/Videos"]
        )
        result = {
            "quickCheck": "ok",
            "foreignKeyErrors": 0,
            "counts": {
                "works": 440,
                "videos": 4869,
                "available_videos": 4869,
                "subtitles": 1234,
                "matched_subtitles": 1227,
                "unlinked_subtitles": 7,
                "probed_videos": 4869,
                "probe_errors": 0,
            },
            "diagnostics": {
                "missing": 0,
                "newFiles": 0,
                "unmatchedSubtitles": 0,
                "orphanSubtitles": 7,
                "unsupportedSubtitles": 3,
                "errors": 0,
                "highConfidenceFileCandidates": 0,
                "highConfidenceSubtitleCandidates": 0,
            },
        }
        self.assertEqual(
            collect_validation_failures(result, args, ffprobe_enabled=True),
            [],
        )

        broken = copy.deepcopy(result)
        broken["diagnostics"]["unmatchedSubtitles"] = 1
        self.assertIn(
            "ambiguous unmatched subtitles remain",
            collect_validation_failures(broken, args, ffprobe_enabled=True),
        )


if __name__ == "__main__":
    unittest.main()
