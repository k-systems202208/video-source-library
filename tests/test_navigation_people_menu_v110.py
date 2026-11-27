from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from database import connect  # noqa: E402
from library_service import list_people  # noqa: E402
from metadata_importer import import_metadata  # noqa: E402
from sample_metadata import build_metadata  # noqa: E402
from server import create_server  # noqa: E402

HTML = (SRC / "video-library.html").read_text(encoding="utf-8")
SERVER = (SRC / "server.py").read_text(encoding="utf-8")


class NavigationPeopleMenuSourceTests(unittest.TestCase):
    def test_sidebar_uses_real_routes(self) -> None:
        for route in (
            '#/home/continue',
            '#/home/next',
            '#/library',
            '#/people/directors',
            '#/people/cast',
        ):
            self.assertIn(f'data-route="{route}"', HTML)
        self.assertNotIn('data-scroll-target="continueSection"', HTML)
        self.assertNotIn('id="navScan"', HTML)
        self.assertNotIn('href="/diagnostics.html"', HTML)

    def test_people_directory_ui_and_routes_exist(self) -> None:
        self.assertIn('id="peopleDirectory"', HTML)
        self.assertIn('id="peopleDirectoryList"', HTML)
        self.assertIn("showPeopleDirectory(role)", HTML)
        self.assertIn("location.hash.match(/^#\\/people\\/(directors|cast)$/)", HTML)
        self.assertIn("/api/people?role=", HTML)
        self.assertIn("people-profile-media", HTML)
        self.assertIn("personProfileFallback", HTML)
        self.assertIn("p.profileUrl", HTML)
        self.assertIn("/tmdb-person-image/", SERVER)
        self.assertIn("NAVIGATION_PEOPLE_MENU_V2", HTML)

    def test_server_no_longer_auto_injects_diagnostics_link(self) -> None:
        self.assertNotIn('if "diagnostics.html" not in text:', SERVER)
        self.assertIn('if path == "/api/people":', SERVER)


class NavigationPeopleMenuServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "library.db"
        with connect(self.db_path) as connection:
            import_metadata(connection, build_metadata(work_count=4, video_count=12))
            rows = connection.execute("SELECT id FROM works ORDER BY id LIMIT 3").fetchall()
            connection.execute(
                "UPDATE works SET director_or_direction=?, main_cast_or_voice_actors=? WHERE id=?",
                ("堤幸彦、木村ひさし ほか", "仲間由紀恵、阿部寛", int(rows[0]["id"])),
            )
            connection.execute(
                "UPDATE works SET director_or_direction=?, main_cast_or_voice_actors=? WHERE id=?",
                ("堤幸彦", "仲間由紀恵、野際陽子", int(rows[1]["id"])),
            )
            connection.execute(
                "UPDATE works SET director_or_direction=?, main_cast_or_voice_actors=? WHERE id=?",
                ("別監督", "別俳優", int(rows[2]["id"])),
            )
            connection.commit()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_list_people_counts_and_normalizes_credits(self) -> None:
        with connect(self.db_path) as connection:
            directors = list_people(connection, role="director")
            cast = list_people(connection, role="cast")
        self.assertEqual(directors["role"], "director")
        self.assertEqual(directors["items"][0], {"name": "堤幸彦", "workCount": 2})
        self.assertIn({"name": "木村ひさし", "workCount": 1}, directors["items"])
        self.assertEqual(cast["items"][0], {"name": "仲間由紀恵", "workCount": 2})

    def test_people_http_endpoint(self) -> None:
        server = create_server(self.db_path, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(base + "/api/people?role=director", timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertEqual(payload["role"], "director")
            self.assertGreaterEqual(payload["total"], 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
