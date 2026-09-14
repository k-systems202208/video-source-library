from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from database import connect, initialize_database, now_iso
from scan_diagnostics import diagnostics_csv_bytes, scan_diagnostics


def _insert_work(connection, no: int, title: str, relative_path: str, media_count: int, subtitle_count: int) -> int:
    stamp = now_iso()
    cursor = connection.execute(
        """
        INSERT INTO works(
            external_work_no, category, official_title, media_file_count,
            subtitle_file_count, subfolder_count, relative_path, created_at, updated_at
        ) VALUES(?, '海外映画・ドラマ', ?, ?, ?, 0, ?, ?, ?)
        """,
        (no, title, media_count, subtitle_count, relative_path, stamp, stamp),
    )
    return int(cursor.lastrowid)


def _insert_video(connection, work_id: int, external_no: int, path: str, episode: str) -> None:
    stamp = now_iso()
    cursor = connection.execute(
        """
        INSERT INTO videos(
            work_id, external_file_no, official_title, episode_or_type,
            episode_sort_key, content_type, created_at, updated_at
        ) VALUES(?, ?, ?, ?, ?, 'EPISODE', ?, ?)
        """,
        (work_id, external_no, episode, episode, f"{external_no:06d}", stamp, stamp),
    )
    video_id = int(cursor.lastrowid)
    filename = Path(path.replace("\\", "/")).name
    extension = Path(filename).suffix.lstrip(".").upper()
    connection.execute(
        """
        INSERT INTO video_files(
            video_id, filename, relative_path, extension, file_size,
            modified_time_ns, is_available, scan_status, created_at, updated_at
        ) VALUES(?, ?, ?, ?, 1000, 1, 1, 'MATCHED', ?, ?)
        """,
        (video_id, filename, path, extension, stamp, stamp),
    )


def _insert_subtitle(connection, path: str) -> None:
    stamp = now_iso()
    filename = Path(path.replace("\\", "/")).name
    extension = Path(filename).suffix.lstrip(".").upper()
    connection.execute(
        """
        INSERT INTO subtitles(
            video_id, relative_path, filename, extension, language, is_forced,
            is_default, match_method, file_size, modified_time_ns, is_available,
            last_scanned_at, created_at, updated_at
        ) VALUES(NULL, ?, ?, ?, NULL, 0, 0, 'UNMATCHED', 100, 1, 1, ?, ?, ?)
        """,
        (path, filename, extension, stamp, stamp, stamp),
    )


def seed(db: Path) -> int:
    stamp = now_iso()
    with connect(db) as c:
        initialize_database(c)

        _insert_work(c, 1, "ラ・ラ・ランド", "movie/2016_La La Land", 0, 1)
        _insert_work(c, 2, "アイデア･オブ･ユー", "movie/2024_The Idea Of You", 0, 1)
        kita = _insert_work(c, 3, "北の国から", "movie_jpn/1981_Kita no Kuni kara", 2, 5)
        _insert_video(
            c,
            kita,
            1,
            "movie_jpn/1981_Kita no Kuni kara/Kita no Kuni kara ep01 (720x540 x264-AAC).mkv",
            "第1話",
        )
        _insert_video(
            c,
            kita,
            2,
            "movie_jpn/1981_Kita no Kuni kara/Kita no Kuni kara ep24 finale (720x540 x264-AAC).mkv",
            "第24話",
        )

        control = _insert_work(c, 4, "対照作品", "movie/Control", 1, 1)
        _insert_video(c, control, 3, "movie/Control/Movie.mkv", "映画")

        paths = [
            "movie/2016_La La Land/La.La.Land.srt",
            "movie/2024_The Idea Of You/Subs/jpn.srt",
            "movie_jpn/1981_Kita no Kuni kara/Subs/Kita no Kuni kara SP 1983 ~Fuyu~ (720x540 x264-AAC).ass",
            "movie_jpn/1981_Kita no Kuni kara/Subs/Kita no Kuni kara SP 1984 ~Natsu~ (720x540 x264-AAC).ass",
            "movie_jpn/1981_Kita no Kuni kara/Subs/Kita no Kuni kara SP 1987 ~Hatsukoi~ (720x540 x264-AAC).ass",
            "movie_jpn/1981_Kita no Kuni kara/Subs/Kita no Kuni kara SP 1995 ~Himitsu~ Part 1 (856x480 x264-AAC).ass",
            "movie_jpn/1981_Kita no Kuni kara/Subs/Kita no Kuni kara SP 1995 ~Himitsu~ Part 2 (856x480 x264-AAC).ass",
            "movie/Control/Movie.commentary.srt",
        ]
        for path in paths:
            _insert_subtitle(c, path)

        cursor = c.execute(
            """
            INSERT INTO scan_runs(
                started_at, completed_at, status, files_found, files_matched,
                files_missing, files_new, subtitles_found, subtitles_matched,
                subtitles_unmatched, probe_errors, errors, duration_ms, created_at
            ) VALUES(?, ?, 'SUCCESS', 3, 3, 0, 0, 8, 0, 8, 0, 0, 1000, ?)
            """,
            (stamp, stamp, stamp),
        )
        run_id = int(cursor.lastrowid)
        for index, extension in enumerate(("IDX", "SUB", "SMI"), start=1):
            c.execute(
                """
                INSERT INTO scan_discoveries(
                    scan_run_id, relative_path, extension, file_size,
                    modified_time_ns, status, created_at
                ) VALUES(?, ?, ?, 10, 1, 'UNSUPPORTED_SUBTITLE', ?)
                """,
                (run_id, f"movie/Unsupported/sample{index}.{extension.lower()}", extension, stamp),
            )
        c.commit()
        return run_id


class OrphanSubtitleDiagnosticsTests(unittest.TestCase):
    def test_known_no_target_subtitles_are_separated_from_ambiguous_unmatched(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "library.db"
            run_id = seed(db)
            with connect(db) as c:
                value = scan_diagnostics(c)

            self.assertEqual(value["scan"]["runId"], run_id)
            self.assertEqual(value["summary"]["orphanSubtitles"], 7)
            self.assertEqual(value["summary"]["unmatchedSubtitles"], 1)
            self.assertEqual(value["summary"]["unsupportedSubtitles"], 3)
            self.assertEqual(len(value["orphanSubtitles"]), 7)
            self.assertEqual(len(value["unmatchedSubtitles"]), 1)
            self.assertTrue(value["unmatchedSubtitles"][0]["relativePath"].endswith("Movie.commentary.srt"))

            reasons = [item["orphanReason"] for item in value["orphanSubtitles"]]
            self.assertEqual(reasons.count("NO_REGISTERED_VIDEO_IN_WORK"), 2)
            self.assertEqual(reasons.count("SPECIAL_VIDEO_NOT_REGISTERED"), 5)

            text = diagnostics_csv_bytes(value)[3:].decode("utf-8")
            self.assertEqual(text.count("ORPHAN_SUBTITLE"), 7)
            self.assertIn("NO_REGISTERED_VIDEO_IN_WORK", text)
            self.assertIn("SPECIAL_VIDEO_NOT_REGISTERED", text)
            self.assertIn("SUBTITLE_CANDIDATE", text)
            self.assertIn("movie/Control/Movie.commentary.srt", text)

    def test_special_is_not_orphan_when_special_video_is_registered(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "library.db"
            stamp = now_iso()
            with connect(db) as c:
                initialize_database(c)
                work = _insert_work(c, 1, "SP作品", "movie_jpn/SP Work", 1, 1)
                _insert_video(c, work, 1, "movie_jpn/SP Work/SP 1983 Fuyu.mkv", "スペシャル")
                _insert_subtitle(c, "movie_jpn/SP Work/Subs/SP 1983 Another Release.ass")
                c.execute(
                    """
                    INSERT INTO scan_runs(
                        started_at, completed_at, status, files_found, files_matched,
                        files_missing, files_new, subtitles_found, subtitles_matched,
                        subtitles_unmatched, probe_errors, errors, duration_ms, created_at
                    ) VALUES(?, ?, 'SUCCESS', 1, 1, 0, 0, 1, 0, 1, 0, 0, 10, ?)
                    """,
                    (stamp, stamp, stamp),
                )
                c.commit()
                value = scan_diagnostics(c)

            self.assertEqual(value["summary"]["orphanSubtitles"], 0)
            self.assertEqual(value["summary"]["unmatchedSubtitles"], 1)


if __name__ == "__main__":
    unittest.main()
