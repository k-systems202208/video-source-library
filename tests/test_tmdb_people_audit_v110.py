from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from database import connect, initialize_database, now_iso
from tmdb_people import (
    audit_tmdb_people_profiles,
    mark_people_audit_complete,
    people_audit_required,
)


class AuditClient:
    def __init__(self):
        self.credits = {}
        self.search = {}

    def movie_credits(self, movie_id, *, language="ja-JP"):
        return self.credits.get(("movie", int(movie_id)), {"cast": []})

    def tv_aggregate_credits(self, tv_id, *, language="ja-JP"):
        return self.credits.get(("tv", int(tv_id)), {"cast": []})

    def search_person(self, query, *, language="ja-JP"):
        return {"results": list(self.search.get(query, []))}


class TmdbPeopleAuditTests(unittest.TestCase):
    def _db(self, root: Path) -> Path:
        db = root / "library.db"
        with connect(db) as connection:
            initialize_database(connection)
        return db

    def _insert_work(
        self,
        connection: sqlite3.Connection,
        *,
        external_no: int,
        title: str,
        cast: str,
        year: str = "",
        status: str | None = None,
        media_type: str | None = None,
        tmdb_id: int | None = None,
    ) -> int:
        stamp = now_iso()
        connection.execute(
            """
            INSERT INTO works(
                external_work_no,category,year_or_period,official_title,
                main_cast_or_voice_actors,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (external_no, "日本映画・ドラマ", year, title, cast, stamp, stamp),
        )
        work_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        if status is not None:
            connection.execute(
                """
                INSERT INTO tmdb_work_links(
                    work_id,media_type,tmdb_id,match_status,created_at,updated_at
                ) VALUES(?,?,?,?,?,?)
                """,
                (work_id, media_type, tmdb_id, status, stamp, stamp),
            )
        connection.commit()
        return work_id

    def _link_person(
        self,
        connection: sqlite3.Connection,
        *,
        work_id: int,
        local_name: str,
        person_id: int,
        profile_path: str | None,
    ) -> None:
        stamp = now_iso()
        connection.execute(
            """
            INSERT INTO tmdb_people(
                tmdb_person_id,display_name,original_name,profile_path,known_for_department,
                synced_at,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (person_id, local_name, local_name, profile_path, "Acting", stamp, stamp, stamp),
        )
        connection.execute(
            """
            INSERT INTO tmdb_work_people(
                work_id,role,local_name,tmdb_person_id,created_at,updated_at
            ) VALUES(?,'CAST',?,?,?,?)
            """,
            (work_id, local_name, person_id, stamp, stamp),
        )
        connection.commit()

    def test_audit_classifies_ready_no_profile_and_no_matched_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = self._db(root)
            with connect(db) as connection:
                ready_work = self._insert_work(
                    connection,
                    external_no=1,
                    title="Ready Work",
                    cast="写真あり俳優",
                    status="MATCHED",
                    media_type="movie",
                    tmdb_id=101,
                )
                no_photo_work = self._insert_work(
                    connection,
                    external_no=2,
                    title="No Photo Work",
                    cast="写真なし俳優",
                    status="MATCHED",
                    media_type="movie",
                    tmdb_id=102,
                )
                self._insert_work(
                    connection,
                    external_no=3,
                    title="Unmatched Work",
                    cast="作品未照合俳優",
                    status="UNMATCHED",
                )
                self._link_person(
                    connection,
                    work_id=ready_work,
                    local_name="写真あり俳優",
                    person_id=1001,
                    profile_path="/ready.jpg",
                )
                self._link_person(
                    connection,
                    work_id=no_photo_work,
                    local_name="写真なし俳優",
                    person_id=1002,
                    profile_path=None,
                )

            report = audit_tmdb_people_profiles(
                db,
                root / "diagnostics",
                "token",
                client=AuditClient(),
            )
            self.assertTrue(Path(report["jsonReport"]).is_file())
            self.assertTrue(Path(report["csvReport"]).is_file())
            summary = report["summary"]
            self.assertEqual(summary["profileReady"], 1)
            self.assertEqual(summary["personNoProfile"], 1)
            self.assertEqual(summary["noMatchedWork"], 1)
            self.assertEqual(summary["needsReview"], 1)

            payload = json.loads(Path(report["jsonReport"]).read_text(encoding="utf-8"))
            by_name = {item["name"]: item for item in payload["items"]}
            self.assertEqual(by_name["写真あり俳優"]["reason"], "PROFILE_READY")
            self.assertEqual(by_name["写真なし俳優"]["reason"], "PERSON_NO_PROFILE")
            self.assertEqual(by_name["写真なし俳優"]["resolution"], "TMDB_PROFILE_MISSING")
            self.assertEqual(by_name["作品未照合俳優"]["reason"], "NO_MATCHED_WORK")
            self.assertEqual(by_name["作品未照合俳優"]["resolution"], "")
            self.assertEqual(by_name["作品未照合俳優"]["localWorks"], ["Unmatched Work [UNMATCHED]"])
            self.assertEqual(by_name["写真あり俳優"]["localWorks"], ["Ready Work [MATCHED movie:101]"])
            csv_header = Path(report["csvReport"]).read_text(encoding="utf-8-sig").splitlines()[0]
            self.assertIn("localWorks", csv_header)
            self.assertIn("resolution", csv_header)

    def test_audit_marks_reviewed_residuals_without_forcing_person_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = self._db(root)
            with connect(db) as connection:
                self._insert_work(
                    connection,
                    external_no=1,
                    title="男はつらいよ",
                    year="1969-2019",
                    cast="渥美清",
                    status="REVIEW",
                    media_type="movie",
                    tmdb_id=125271,
                )
                self._insert_work(
                    connection,
                    external_no=2,
                    title="半分の月がのぼる空",
                    year="2006",
                    cast="橋本淳",
                    status="UNMATCHED",
                )
                self._insert_work(
                    connection,
                    external_no=3,
                    title="スケバン刑事",
                    year="1985",
                    cast="渡辺千秋",
                    status="MATCHED",
                    media_type="tv",
                    tmdb_id=89351,
                )

            report = audit_tmdb_people_profiles(
                db,
                root / "diagnostics",
                "token",
                client=AuditClient(),
            )
            payload = json.loads(Path(report["jsonReport"]).read_text(encoding="utf-8"))
            by_name = {item["name"]: item for item in payload["items"]}

            self.assertEqual(by_name["渥美清"]["reason"], "NO_MATCHED_WORK")
            self.assertEqual(
                by_name["渥美清"]["resolution"],
                "INTENTIONAL_AGGREGATE_REVIEW",
            )
            self.assertEqual(by_name["橋本淳"]["reason"], "NO_MATCHED_WORK")
            self.assertEqual(
                by_name["橋本淳"]["resolution"],
                "INTENTIONAL_STRUCTURE_UNMATCHED",
            )
            self.assertEqual(by_name["渡辺千秋"]["reason"], "CREDIT_PERSON_NOT_FOUND")
            self.assertEqual(
                by_name["渡辺千秋"]["resolution"],
                "VERIFIED_CAST_TMDB_PERSON_UNAVAILABLE",
            )
            self.assertEqual(report["summary"]["needsReview"], 0)

    def test_audit_classifies_credit_mismatch_search_outside_and_ambiguous(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = self._db(root)
            client = AuditClient()
            with connect(db) as connection:
                self._insert_work(
                    connection,
                    external_no=1,
                    title="Alias Work",
                    cast="別名俳優",
                    status="MATCHED",
                    media_type="movie",
                    tmdb_id=201,
                )
                self._insert_work(
                    connection,
                    external_no=2,
                    title="Outside Work",
                    cast="作品外俳優",
                    status="MATCHED",
                    media_type="movie",
                    tmdb_id=202,
                )
                self._insert_work(
                    connection,
                    external_no=3,
                    title="Ambiguous Work",
                    cast="曖昧俳優",
                    status="MATCHED",
                    media_type="movie",
                    tmdb_id=203,
                )
                self._insert_work(
                    connection,
                    external_no=4,
                    title="Missing Work",
                    cast="候補なし俳優",
                    status="MATCHED",
                    media_type="movie",
                    tmdb_id=204,
                )

            client.credits[("movie", 201)] = {
                "cast": [{"id": 2001, "name": "Alias Actor", "original_name": "Alias Actor"}]
            }
            client.search["別名俳優"] = [{"id": 2001, "name": "Alias Actor"}]

            client.credits[("movie", 202)] = {
                "cast": [{"id": 2002, "name": "Credit Actor", "original_name": "Credit Actor"}]
            }
            client.search["作品外俳優"] = [{"id": 9999, "name": "Wrong Actor"}]

            client.credits[("movie", 203)] = {
                "cast": [
                    {"id": 2003, "name": "Actor A", "original_name": "Actor A"},
                    {"id": 2004, "name": "Actor B", "original_name": "Actor B"},
                ]
            }
            client.search["曖昧俳優"] = [
                {"id": 2003, "name": "Actor A"},
                {"id": 2004, "name": "Actor B"},
            ]

            client.credits[("movie", 204)] = {
                "cast": [{"id": 2005, "name": "Other Actor", "original_name": "Other Actor"}]
            }
            client.search["候補なし俳優"] = []

            report = audit_tmdb_people_profiles(
                db,
                root / "diagnostics",
                "token",
                client=client,
            )
            payload = json.loads(Path(report["jsonReport"]).read_text(encoding="utf-8"))
            by_name = {item["name"]: item for item in payload["items"]}
            self.assertEqual(by_name["別名俳優"]["reason"], "CREDIT_NAME_MISMATCH")
            self.assertEqual(by_name["作品外俳優"]["reason"], "PERSON_SEARCH_NOT_IN_CREDITS")
            self.assertEqual(by_name["曖昧俳優"]["reason"], "AMBIGUOUS")
            self.assertEqual(by_name["候補なし俳優"]["reason"], "CREDIT_PERSON_NOT_FOUND")
            self.assertEqual(by_name["別名俳優"]["constrainedSearchIds"], [2001])
            self.assertEqual(by_name["作品外俳優"]["searchResultIds"], [9999])

    def test_people_audit_v1_marker_requires_v2_reaudit(self):
        from tmdb_cache import put_cached_json

        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(Path(tmp))
            with connect(db) as connection:
                put_cached_json(
                    connection,
                    "tmdb:people-audit-version",
                    {"version": 1},
                    fetched_at=now_iso(),
                    expires_at=None,
                )
                connection.commit()
                self.assertTrue(people_audit_required(connection))

    def test_people_audit_v2_marker_requires_v3_reaudit(self):
        from tmdb_cache import put_cached_json

        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(Path(tmp))
            with connect(db) as connection:
                put_cached_json(
                    connection,
                    "tmdb:people-audit-version",
                    {"version": 2},
                    fetched_at=now_iso(),
                    expires_at=None,
                )
                connection.commit()
                self.assertTrue(people_audit_required(connection))

    def test_people_audit_v3_marker_requires_v4_reaudit(self):
        from tmdb_cache import put_cached_json

        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(Path(tmp))
            with connect(db) as connection:
                put_cached_json(
                    connection,
                    "tmdb:people-audit-version",
                    {"version": 3},
                    fetched_at=now_iso(),
                    expires_at=None,
                )
                connection.commit()
                self.assertTrue(people_audit_required(connection))

    def test_people_audit_v4_marker_requires_v5_reaudit(self):
        from tmdb_cache import put_cached_json

        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(Path(tmp))
            with connect(db) as connection:
                put_cached_json(
                    connection,
                    "tmdb:people-audit-version",
                    {"version": 4},
                    fetched_at=now_iso(),
                    expires_at=None,
                )
                connection.commit()
                self.assertTrue(people_audit_required(connection))

    def test_people_audit_v5_marker_requires_v6_reaudit(self):
        from tmdb_cache import put_cached_json

        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(Path(tmp))
            with connect(db) as connection:
                put_cached_json(
                    connection,
                    "tmdb:people-audit-version",
                    {"version": 5},
                    fetched_at=now_iso(),
                    expires_at=None,
                )
                connection.commit()
                self.assertTrue(people_audit_required(connection))

    def test_people_audit_v6_marker_requires_v7_reaudit(self):
        from tmdb_cache import put_cached_json

        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(Path(tmp))
            with connect(db) as connection:
                put_cached_json(
                    connection,
                    "tmdb:people-audit-version",
                    {"version": 6},
                    fetched_at=now_iso(),
                    expires_at=None,
                )
                connection.commit()
                self.assertTrue(people_audit_required(connection))

    def test_people_audit_v7_marker_requires_v8_reaudit(self):
        from tmdb_cache import put_cached_json

        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(Path(tmp))
            with connect(db) as connection:
                put_cached_json(
                    connection,
                    "tmdb:people-audit-version",
                    {"version": 7},
                    fetched_at=now_iso(),
                    expires_at=None,
                )
                connection.commit()
                self.assertTrue(people_audit_required(connection))

    def test_people_audit_v8_marker_requires_v9_reaudit(self):
        from tmdb_cache import put_cached_json

        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(Path(tmp))
            with connect(db) as connection:
                put_cached_json(
                    connection,
                    "tmdb:people-audit-version",
                    {"version": 8},
                    fetched_at=now_iso(),
                    expires_at=None,
                )
                connection.commit()
                self.assertTrue(people_audit_required(connection))

    def test_people_audit_version_is_independent_from_people_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(Path(tmp))
            with connect(db) as connection:
                self.assertTrue(people_audit_required(connection))
                mark_people_audit_complete(connection)
                connection.commit()
                self.assertFalse(people_audit_required(connection))

    def test_launcher_supports_audit_only_background_run(self):
        launcher = (SRC / "launcher.py").read_text(encoding="utf-8")
        self.assertIn("people_audit_required", launcher)
        self.assertIn("audit_tmdb_people_profiles", launcher)
        self.assertIn("if not sync_required and not audit_required", launcher)
        self.assertIn("出演者／声優の顔写真監査をバックグラウンド実行します。", launcher)

    def test_manual_tmdb_sync_returns_people_audit(self):
        sync_source = (SRC / "tmdb_sync.py").read_text(encoding="utf-8")
        self.assertIn("audit_tmdb_people_profiles(", sync_source)
        self.assertIn('"peopleAudit": people_audit', sync_source)


if __name__ == "__main__":
    unittest.main()
