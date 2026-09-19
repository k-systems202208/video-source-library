from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "windows-installer" / "src" / "video-library.html"


class CinemaLibraryDetailV2V110Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML.read_text(encoding="utf-8")

    def test_detail_v2_marker_and_mockup_hierarchy_exist(self):
        self.assertIn("CINEMA_LIBRARY_DETAIL_V2", self.html)
        self.assertIn("FEATURE PRESENTATION", self.html)
        self.assertIn("上映プログラム", self.html)
        self.assertIn("PROGRAM", self.html)
        self.assertIn("上映目録", self.html)
        self.assertIn("SCREENING LIST", self.html)

    def test_poster_title_and_episode_visual_classes_exist(self):
        self.assertIn("grid-template-columns:205px minmax(0,1fr)", self.html)
        self.assertIn("hero-title-block", self.html)
        self.assertIn("favorite-action", self.html)
        self.assertIn("episode-title", self.html)
        self.assertIn("program-section", self.html)
        self.assertIn("screening-list", self.html)

    def test_existing_behavior_hooks_are_preserved(self):
        self.assertIn("/favorite`,jo('PUT'", self.html)
        self.assertIn("#/person/${encodeURIComponent(name)}", self.html)
        self.assertIn("loadEpisodes(w.id,x.id)", self.html)
        self.assertIn("r.onclick=()=>showVideo(v.id)", self.html)
        self.assertIn("/playback/progress", self.html)

    def test_existing_image_and_detail_ids_are_preserved(self):
        for value in ("workDetail", "episodes", "videoDetail", "playerModal", "back"):
            self.assertIn(value, self.html)
        self.assertIn("w.backdropUrl", self.html)
        self.assertIn("w.posterUrl", self.html)

    def test_display_version_matches_current_release(self):
        version = (ROOT / "windows-installer" / "src" / "app_version.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "1.2.1"', version)


if __name__ == "__main__":
    unittest.main()
