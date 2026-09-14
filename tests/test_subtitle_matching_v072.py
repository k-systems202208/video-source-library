from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from subtitle_tools import (
    UNSUPPORTED_SUBTITLE_EXTENSIONS,
    match_subtitle_to_video,
)


class SafeSubtitleMatching072Tests(unittest.TestCase):
    def test_existing_same_folder_exact_and_language_suffix_are_preserved(self):
        videos = ["movie/work/episode01.mkv", "movie/work/episode02.mkv"]
        exact = match_subtitle_to_video("movie/work/episode01.srt", videos)
        self.assertEqual(exact.video_relative_path, videos[0])
        self.assertEqual(exact.match_method, "EXACT_STEM")

        language = match_subtitle_to_video("movie/work/episode02.ja.forced.srt", videos)
        self.assertEqual(language.video_relative_path, videos[1])
        self.assertEqual(language.match_method, "LANGUAGE_SUFFIX")
        self.assertEqual(language.language, "ja")
        self.assertTrue(language.is_forced)

    def test_subtitles_folder_exact_stem_matches_only_inside_same_work(self):
        videos = [
            "movie_jpn/show-a/Episode 01.mkv",
            "movie_jpn/show-b/Episode 01.mkv",
        ]
        value = match_subtitle_to_video(
            "movie_jpn/show-a/Subtitles/Episode 01.ass",
            videos,
        )
        self.assertEqual(value.video_relative_path, videos[0])
        self.assertEqual(value.match_method, "WORK_EXACT_STEM")

    def test_video_stem_prefix_matches_only_when_unique(self):
        videos = [
            "movie/film/Film.2024.1080p.YIFY.mp4",
            "movie/other/Film.2024.1080p.YIFY.mp4",
        ]
        value = match_subtitle_to_video(
            "movie/film/Film.2024.1080p.YIFY-jpn.srt",
            videos,
        )
        self.assertEqual(value.video_relative_path, videos[0])
        self.assertEqual(value.match_method, "WORK_STEM_PREFIX")
        self.assertEqual(value.language, "ja")

    def test_one_video_work_accepts_different_subtitle_release_name(self):
        videos = [
            "movie/single-film/Single.Film.2020.1080p.BluRay.mp4",
            "movie/another-film/Another.Film.2020.mp4",
        ]
        value = match_subtitle_to_video(
            "movie/single-film/Subs/jpn.srt",
            videos,
        )
        self.assertEqual(value.video_relative_path, videos[0])
        self.assertEqual(value.match_method, "WORK_SINGLE_VIDEO")
        self.assertEqual(value.language, "ja")

    def test_common_season_episode_formats_match_unique_episode(self):
        videos = [
            "movie/show/Season 2/Show-S02E01 720p.mkv",
            "movie/show/Season 2/Show-S02E10 720p.mkv",
            "movie/show/Season 5/Show-S05E01 1080p.mkv",
        ]
        cases = [
            ("movie/show/Season 2/subs/Show 2x10 Title.srt", videos[1]),
            ("movie/show/Season 2/subs/show s2_10.srt", videos[1]),
            ("movie/show/Season 5/subs/ep501-jpn.srt", videos[2]),
        ]
        for subtitle, expected in cases:
            with self.subTest(subtitle=subtitle):
                value = match_subtitle_to_video(subtitle, videos)
                self.assertEqual(value.video_relative_path, expected)
                self.assertEqual(value.match_method, "EPISODE_NUMBER")

    def test_single_season_e_number_is_allowed_only_when_unique(self):
        videos = [
            "movie_jpn/show/Show.E01.mkv",
            "movie_jpn/show/Show.E02.mkv",
        ]
        value = match_subtitle_to_video("movie_jpn/show/Subs/other-release E02.ass", videos)
        self.assertEqual(value.video_relative_path, videos[1])
        self.assertEqual(value.match_method, "EPISODE_NUMBER")

    def test_misplaced_subtitle_uses_filename_episode_before_folder_episode(self):
        videos = [
            "movie/show/Season 4/Show-S04E01.mkv",
            "movie/show/Season 4/Show-S04E13.mkv",
        ]
        value = match_subtitle_to_video(
            "movie/show/Season 4/subs/episode 1/show s4_13.srt",
            videos,
        )
        self.assertEqual(value.video_relative_path, videos[1])
        self.assertEqual(value.match_method, "EPISODE_NUMBER")

    def test_ambiguous_episode_is_never_auto_matched(self):
        videos = [
            "movie/show/Season 1/Show-S01E01.mkv",
            "movie/show/Season 2/Show-S02E01.mkv",
        ]
        value = match_subtitle_to_video("movie/show/Subs/Show E01.srt", videos)
        self.assertIsNone(value.video_relative_path)
        self.assertEqual(value.match_method, "UNMATCHED")

    def test_prefix_without_separator_boundary_is_not_accepted(self):
        videos = [
            "movie/work/Film.mkv",
            "movie/work/FilmExtended.mkv",
        ]
        value = match_subtitle_to_video("movie/work/Subs/FilmExtendedCut.srt", videos)
        self.assertIsNone(value.video_relative_path)

    def test_unsupported_subtitle_extensions_remain_separate(self):
        self.assertEqual(UNSUPPORTED_SUBTITLE_EXTENSIONS, {".idx", ".sub", ".smi"})


if __name__ == "__main__":
    unittest.main()
