from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "windows-installer" / "src" / "video-library.html").read_text(encoding="utf-8")


class HomeResetPersonFilterTests(unittest.TestCase):
    def test_both_cinema_brand_names_are_reset_buttons(self):
        self.assertIn('id="cinemaNavBrandReset"', HTML)
        self.assertIn('id="headerBrandReset"', HTML)
        self.assertIn("history.replaceState(null,'',location.pathname+location.search);location.reload()", HTML)
        self.assertIn("$('cinemaNavBrandReset').onclick=resetCinemaHome", HTML)
        self.assertIn("$('headerBrandReset').onclick=resetCinemaHome", HTML)

    def test_person_filter_is_cleared_before_returning_to_library(self):
        self.assertIn('function clearPersonSearchFilter()', HTML)
        self.assertIn("state.person='';state.q='';$('search').value='';return true", HTML)
        self.assertNotIn("$('headerSearch').value=''", HTML)
        self.assertIn("async function showLibraryRoute(target='catalog',scrollTarget=true){leaveVisibilityMode();clearPersonSearchFilter();", HTML)
        self.assertIn("await loadHome();await loadWorks(true);updateCinemaNavActive();", HTML)
        self.assertNotIn("if(!works.children.length)await loadWorks(true)", HTML)

    def test_people_directory_also_releases_previous_person_filter(self):
        self.assertIn("async function showPeopleDirectory(role){leaveVisibilityMode();const isDirector=role==='directors';clearPersonSearchFilter();", HTML)


if __name__ == '__main__':
    unittest.main()
