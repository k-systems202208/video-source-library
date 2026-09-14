from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from subtitle_tools import match_subtitle_to_video


class ResidualSubtitleMatch074Tests(unittest.TestCase):
    def test_residual_67_distribution_matches_real_data_analysis(self):
        videos: list[str] = []
        subtitles: list[str] = []

        # 34 Breaking Bad subtitles: a main episode and an Inside-extra share the
        # same SxxExx key. The subtitle's Season branch must disambiguate them.
        for season in (1, 5):
            for episode in range(1, 18):
                videos.append(
                    f"movie/2008_Breaking Bad Season 1,2,3,4,5+Extras/Season {season}/"
                    f"Breaking Bad-S{season:02d}E{episode:02d} 1080p WEB-DL.mkv"
                )
                videos.append(
                    f"movie/2008_Breaking Bad Season 1,2,3,4,5+Extras/"
                    f"Inside Breaking Bad Season {season} [Extras]/"
                    f"Inside Breaking Bad S{season:02d}E{episode:02d} 480p WEB-Rip.mkv"
                )
                subtitles.append(
                    f"movie/2008_Breaking Bad Season 1,2,3,4,5+Extras/Season {season}/"
                    f"subtitle-pack/episode {episode}/Breaking.Bad.S{season:02d}E{episode:02d}.JP.srt"
                )

        # 4 HiGH&LOW subtitles: S1 and S2 both have EP05-08 without an explicit
        # season token in the filename, so the S1 branch must decide uniquely.
        for episode in range(5, 9):
            videos.extend([
                f"movie_jpn/2015-2016_HiGH&LOW/HiGH&LOW S1(2015)/HiGHLOW EP{episode:02d} 720P HDTV X265-ER.mkv",
                f"movie_jpn/2015-2016_HiGH&LOW/HiGH&LOW S2 (2016)/HiGH&LOW Season 2 E{episode:02d}.mp4",
            ])
            subtitles.append(
                f"movie_jpn/2015-2016_HiGH&LOW/HiGH&LOW S1(2015)/Subs/"
                f"HiGHLOW EP{episode:02d} 720p x265-ER.ssa"
            )

        # 5 Murder Analysis Squad subtitles: two sub-series reuse EP01-05.
        for episode in range(1, 6):
            videos.extend([
                f"movie_jpn/2016-2019_Murder Analysis Squad/Suishou no Kodou (2016)/"
                f"Suishou no Kodou EP{episode:02d} 720p HDTV DX265.mkv",
                f"movie_jpn/2016-2019_Murder Analysis Squad/Aku no Hado (2019) [Spinoff]/"
                f"Aku no Hadou EP{episode:02d} 720p HDTV x264 JPTVTS.mp4",
            ])
            subtitles.append(
                f"movie_jpn/2016-2019_Murder Analysis Squad/Suishou no Kodou (2016)/"
                f"Suishou no Kodou ep{episode:02d} 720p HDTV x264 AAC-DoA.ass"
            )

        # 12 Koukou Kyoushi subtitles differ only by separators.
        for episode in range(1, 12):
            videos.append(
                f"movie_jpn/1993_Kou kou Kyoushi/Koukou_Kyoushi_1993_{episode:02d}.mkv"
            )
            subtitles.append(
                f"movie_jpn/1993_Kou kou Kyoushi/Subs/Koukou Kyoushi 1993 - {episode:02d}.ass"
            )
        videos.append("movie_jpn/1993_Kou kou Kyoushi/Koukou_Kyoushi_1993_Special.mkv")
        subtitles.append("movie_jpn/1993_Kou kou Kyoushi/Subs/Koukou Kyoushi 1993 Special.ass")

        # Hammer Session: separators differ, but the alphanumeric stem is exact.
        videos.extend([
            "movie_jpn/2010_HAMMER SESSION!/hammer_session_04.mp4",
            "movie_jpn/2010_HAMMER SESSION!/hammer_session_05.mp4",
        ])
        subtitles.append("movie_jpn/2010_HAMMER SESSION!/Subs/Hammer Session 04.ass")

        # Two-part movie: video uses Trim1/Trim2, subtitles only trailing 1/2.
        videos.extend([
            "movie/2001_Life As A House/Life.As.A.House - Trim1.mp4",
            "movie/2001_Life As A House/Life.As.A.House - Trim2.mp4",
        ])
        subtitles.extend([
            "movie/2001_Life As A House/Life As A House1.srt",
            "movie/2001_Life As A House/Life As A House2.srt",
        ])

        # One movie inside a content branch; another video elsewhere in the work
        # prevents WORK_SINGLE_VIDEO from resolving it prematurely.
        videos.extend([
            "movie_jpn/2007-2012_Liar Game/Liar Game The Final Stage (2010)/Liar.game.the.final.stage.2010.x264.dts-waf2.mp4",
            "movie_jpn/2007-2012_Liar Game/Liar Game Reborn (2012)/Liar Game -reborn-.2012.mp4",
        ])
        subtitles.append(
            "movie_jpn/2007-2012_Liar Game/Liar Game The Final Stage (2010)/english-pack/"
            "Liar.Game.The.Final.Stage.2010.x264.DTS-WAF.ass"
        )

        # Joker SP: only technical release tokens differ.
        videos.extend([
            "movie_jpn/2010_Joker Yurusarezaru Sousakan/Joker.e01.hdtv.x264.aac-chdtv.mkv",
            "movie_jpn/2010_Joker Yurusarezaru Sousakan/Joker.sp.hdtv.x264.aac-chdtv.mkv",
        ])
        subtitles.append(
            "movie_jpn/2010_Joker Yurusarezaru Sousakan/Joker.SP.720p.HDTV.x264.AAC-CHDTV.ass"
        )

        # 5 Kita no Kuni kara special subtitles have no registered special video.
        videos.extend([
            "movie_jpn/1981_Kita no Kuni kara/Kita no Kuni kara ep01 (720x540 x264-AAC).mkv",
            "movie_jpn/1981_Kita no Kuni kara/Kita no Kuni kara ep02 (720x540 x264-AAC).mkv",
        ])
        subtitles.extend([
            "movie_jpn/1981_Kita no Kuni kara/Subs/Kita no Kuni kara SP 1983 ~Fuyu~ (720x540 x264-AAC).ass",
            "movie_jpn/1981_Kita no Kuni kara/Subs/Kita no Kuni kara SP 1984 ~Natsu~ (720x540 x264-AAC).ass",
            "movie_jpn/1981_Kita no Kuni kara/Subs/Kita no Kuni kara SP 1987 ~Hatsukoi~ (720x540 x264-AAC).ass",
            "movie_jpn/1981_Kita no Kuni kara/Subs/Kita no Kuni kara SP 1995 ~Himitsu~ Part 1 (856x480 x264-AAC).ass",
            "movie_jpn/1981_Kita no Kuni kara/Subs/Kita no Kuni kara SP 1995 ~Himitsu~ Part 2 (856x480 x264-AAC).ass",
        ])

        # Two orphan subtitle folders have no registered video at all.
        subtitles.extend([
            "movie/2016_La La Land/La.La.Land.srt",
            "movie/2024_The Idea Of You/Subs/jpn.srt",
        ])

        self.assertEqual(len(subtitles), 67)
        results = [match_subtitle_to_video(subtitle, videos) for subtitle in subtitles]
        methods = Counter(result.match_method for result in results)

        self.assertEqual(
            methods,
            Counter({
                "EPISODE_BRANCH": 43,
                "WORK_CANONICAL_STEM": 13,
                "SPLIT_PART_NUMBER": 2,
                "BRANCH_SINGLE_VIDEO": 1,
                "WORK_RELEASE_KEY": 1,
                "UNMATCHED": 7,
            }),
        )
        self.assertEqual(sum(result.video_relative_path is not None for result in results), 60)
        self.assertEqual(sum(result.video_relative_path is None for result in results), 7)

    def test_episode_branch_requires_unique_deeper_branch(self):
        videos = [
            "movie/Test/Season 5/A/Show S05E02.mkv",
            "movie/Test/Season 5/B/Show S05E02.mkv",
        ]
        result = match_subtitle_to_video(
            "movie/Test/Season 5/Subs/Show S05E02.srt",
            videos,
        )
        self.assertIsNone(result.video_relative_path)
        self.assertEqual(result.match_method, "UNMATCHED")

    def test_release_key_does_not_ignore_semantic_tokens(self):
        videos = [
            "movie/Test/Joker.sp.hdtv.x264.aac-group.mkv",
            "movie/Test/Joker.commentary.sp.hdtv.x264.aac-group.mkv",
        ]
        result = match_subtitle_to_video(
            "movie/Test/Joker.SP.720p.HDTV.x264.AAC-group.ass",
            videos,
        )
        self.assertEqual(result.video_relative_path, videos[0])
        self.assertEqual(result.match_method, "WORK_RELEASE_KEY")


if __name__ == "__main__":
    unittest.main()
