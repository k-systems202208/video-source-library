from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from database import initialize_database, now_iso
from user_state import continue_watching, next_up


class PosterUiPolishV110Tests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        initialize_database(self.connection)
        stamp = now_iso()
        self.connection.execute("INSERT INTO users(id,display_name,is_owner,is_active,created_at,updated_at) VALUES(1,'Owner',1,1,?,?)", (stamp, stamp))
        self.connection.execute("INSERT INTO works(id,external_work_no,category,official_title,media_file_count,created_at,updated_at) VALUES(1,1,'国内ドラマ','Poster Test',2,?,?)", (stamp, stamp))
        self.connection.execute("INSERT INTO videos(id,work_id,external_file_no,episode_or_type,episode_sort_key,episode_title,content_type,created_at,updated_at) VALUES(1,1,1,'第1話','0001','First','EPISODE',?,?)", (stamp, stamp))
        self.connection.execute("INSERT INTO videos(id,work_id,external_file_no,episode_or_type,episode_sort_key,episode_title,content_type,created_at,updated_at) VALUES(2,1,2,'第2話','0002','Second','EPISODE',?,?)", (stamp, stamp))
        self.connection.execute("INSERT INTO video_files(video_id,filename,relative_path,extension,is_available,created_at,updated_at) VALUES(1,'1.mp4','1.mp4','.mp4',1,?,?)", (stamp, stamp))
        self.connection.execute("INSERT INTO video_files(video_id,filename,relative_path,extension,is_available,created_at,updated_at) VALUES(2,'2.mp4','2.mp4','.mp4',1,?,?)", (stamp, stamp))
        self.connection.execute("INSERT INTO user_video_state(user_id,video_id,watched,position_ms,duration_ms,last_played_at,created_at,updated_at) VALUES(1,1,0,60000,120000,?,?,?)", (stamp, stamp, stamp))
        self.connection.execute("INSERT INTO tmdb_work_links(work_id,media_type,tmdb_id,match_status,poster_path,created_at,updated_at) VALUES(1,'tv',123,'MATCHED','/poster.jpg',?,?)", (stamp, stamp))
        self.connection.commit()

    def tearDown(self):
        self.connection.close()

    def test_continue_watching_exposes_local_cached_poster_url(self):
        item = continue_watching(self.connection, 1)["items"][0]
        self.assertEqual(item["posterUrl"], "/tmdb-image/poster/1")

    def test_next_up_exposes_local_cached_poster_url(self):
        item = next_up(self.connection, 1)["items"][0]
        self.assertEqual(item["videoId"], 2)
        self.assertEqual(item["posterUrl"], "/tmdb-image/poster/1")

    def test_ui_has_thumbnail_and_resilient_detail_fallback(self):
        html = (SRC / "video-library.html").read_text(encoding="utf-8")
        self.assertIn("mini-poster", html)
        self.assertIn("mini-poster-fallback", html)
        self.assertIn("hero-poster-fallback", html)
        self.assertIn("img.loading='lazy'", html)
        self.assertIn("card:hover .poster img", html)

    def test_existing_person_links_remain(self):
        html = (SRC / "video-library.html").read_text(encoding="utf-8")
        self.assertIn("#/person/${encodeURIComponent(name)}", html)
        self.assertIn("監督／演出", html)
        self.assertIn("主な出演者／声優", html)


if __name__ == "__main__":
    unittest.main()
