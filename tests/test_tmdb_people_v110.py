from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from database import connect, initialize_database, now_iso
from library_service import list_people
from server import create_server
from tmdb_client import TmdbClient
from tmdb_images import cached_person_image_path
from tmdb_people import mark_people_sync_complete, people_sync_required, person_name_queries, repair_reviewed_bad_work_links, split_local_people, sync_cast_people_for_work
from tmdb_people_reviewed_aliases import REVIEWED_PERSON_CREDIT_ALIASES
from tmdb_people_reviewed_overrides import REVIEWED_WORK_PERSON_OVERRIDES


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def close(self):
        pass


class CreditsClient:
    def __init__(self):
        self.movie_calls = 0
        self.tv_calls = 0

    def movie_credits(self, movie_id, *, language="ja-JP"):
        self.movie_calls += 1
        return {"cast": self._cast()}

    def tv_aggregate_credits(self, tv_id, *, language="ja-JP"):
        self.tv_calls += 1
        return {"cast": self._cast()}

    @staticmethod
    def _cast():
        return [
            {
                "id": 101,
                "name": "仲間由紀恵",
                "original_name": "仲間由紀恵",
                "profile_path": "/nakama.jpg",
                "known_for_department": "Acting",
                "roles": [{"character": "山田奈緒子", "order": 0}],
                "order": 0,
            },
            {
                "id": 102,
                "name": "阿部寛",
                "original_name": "阿部寛",
                "profile_path": "/abe.jpg",
                "known_for_department": "Acting",
                "roles": [{"character": "上田次郎", "order": 1}],
                "order": 1,
            },
        ]


class TmdbPeoplePhase1Tests(unittest.TestCase):
    def _database_with_work(self, root: Path, cast: str = "仲間由紀恵、阿部寛、未照合俳優"):
        db = root / "library.db"
        with connect(db) as connection:
            initialize_database(connection)
            stamp = now_iso()
            connection.execute(
                """
                INSERT INTO works(
                    external_work_no,category,official_title,main_cast_or_voice_actors,created_at,updated_at
                ) VALUES(1,'日本映画・ドラマ','TRICK',?,?,?)
                """,
                (cast, stamp, stamp),
            )
            work_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
            connection.commit()
        return db, work_id

    def test_client_uses_movie_credits_and_tv_aggregate_credits_endpoints(self):
        urls = []

        def opener(request, timeout):
            urls.append(request.full_url)
            return FakeResponse({"cast": []})

        client = TmdbClient("token", opener=opener, max_retries=0)
        client.movie_credits(123)
        client.tv_aggregate_credits(456)
        client.search_person("ジョン・トラボルタ")
        client.person_combined_credits(8891)
        client.person_details(8891)
        self.assertTrue(any("/movie/123/credits" in url for url in urls))
        self.assertTrue(any("/tv/456/aggregate_credits" in url for url in urls))
        self.assertTrue(any("/search/person" in url and "query=" in url for url in urls))
        self.assertTrue(any("/person/8891/combined_credits" in url for url in urls))
        self.assertTrue(any("/person/8891?" in url or url.endswith("/person/8891") for url in urls))

    def test_cast_names_are_matched_from_work_credits_and_profiles_are_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, work_id = self._database_with_work(root)
            images = root / "TMDbImages"
            client = CreditsClient()
            downloads = []

            def downloader(remote_path, destination, *, size):
                downloads.append((remote_path, size))
                target = Path(destination)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"profile-image")
                return target

            with connect(db) as connection:
                result = sync_cast_people_for_work(
                    connection,
                    client,
                    work_id=work_id,
                    media_type="tv",
                    tmdb_id=999,
                    local_cast="仲間由紀恵、阿部寛、未照合俳優",
                    image_root=images,
                    image_downloader=downloader,
                )
                links = connection.execute(
                    "SELECT local_name,tmdb_person_id FROM tmdb_work_people ORDER BY billing_order"
                ).fetchall()
                people = list_people(connection, role="cast")

            self.assertEqual(client.tv_calls, 1)
            self.assertEqual(result["matched"], 2)
            self.assertEqual(result["profileCached"], 2)
            self.assertEqual([(row["local_name"], row["tmdb_person_id"]) for row in links], [
                ("仲間由紀恵", 101),
                ("阿部寛", 102),
            ])
            self.assertEqual(downloads, [("/nakama.jpg", "w185"), ("/abe.jpg", "w185")])
            self.assertTrue(cached_person_image_path(images, 101, "/nakama.jpg").is_file())
            self.assertTrue(cached_person_image_path(images, 102, "/abe.jpg").is_file())

            by_name = {item["name"]: item for item in people["items"]}
            self.assertEqual(by_name["仲間由紀恵"]["profileUrl"], "/tmdb-person-image/101")
            self.assertEqual(by_name["阿部寛"]["tmdbPersonId"], 102)
            self.assertNotIn("profileUrl", by_name["未照合俳優"])

    def test_local_people_split_and_alias_queries_handle_real_fallback_patterns(self):
        self.assertEqual(
            split_local_people("戸次重幸／櫻井翔、小林薫 ほか（各話ゲスト）、櫻井孝宏（声）"),
            ["戸次重幸", "櫻井翔", "小林薫", "櫻井孝宏"],
        )
        self.assertEqual(
            person_name_queries("岡田健史（現・水上恒司）"),
            ["岡田健史（現・水上恒司）", "岡田健史", "水上恒司"],
        )
        self.assertEqual(
            person_name_queries("SAYAKA（神田沙也加）"),
            ["SAYAKA（神田沙也加）", "SAYAKA", "神田沙也加"],
        )

    def test_secondary_person_search_is_constrained_to_current_work_credits(self):
        class SearchClient:
            def movie_credits(self, movie_id, *, language="ja-JP"):
                return {
                    "cast": [
                        {
                            "id": 8891,
                            "name": "John Travolta",
                            "original_name": "John Travolta",
                            "profile_path": "/travolta.jpg",
                            "order": 0,
                        }
                    ]
                }

            def search_person(self, query, *, language="ja-JP"):
                if query == "ジョン・トラボルタ":
                    return {
                        "results": [
                            {
                                "id": 8891,
                                "name": "John Travolta",
                                "original_name": "John Travolta",
                                "profile_path": "/travolta.jpg",
                            }
                        ]
                    }
                return {"results": []}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, work_id = self._database_with_work(root, "ジョン・トラボルタ")
            downloads = []

            def downloader(remote_path, destination, *, size):
                downloads.append((remote_path, size))
                target = Path(destination)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"profile")
                return target

            with connect(db) as connection:
                result = sync_cast_people_for_work(
                    connection,
                    SearchClient(),
                    work_id=work_id,
                    media_type="movie",
                    tmdb_id=1,
                    local_cast="ジョン・トラボルタ",
                    image_root=root / "TMDbImages",
                    image_downloader=downloader,
                )
                link = connection.execute(
                    "SELECT local_name,tmdb_person_id FROM tmdb_work_people"
                ).fetchone()

            self.assertEqual(result["matched"], 1)
            self.assertEqual(result["matchedExact"], 0)
            self.assertEqual(result["matchedBySearch"], 1)
            self.assertEqual((link["local_name"], link["tmdb_person_id"]), ("ジョン・トラボルタ", 8891))
            self.assertEqual(downloads, [("/travolta.jpg", "w185")])

    def test_third_match_accepts_unique_search_person_whose_combined_credits_contain_work(self):
        class CombinedClient:
            def __init__(self):
                self.combined_calls = 0

            def tv_aggregate_credits(self, tv_id, *, language="ja-JP"):
                return {
                    "cast": [
                        {
                            "id": 777,
                            "name": "Different Credit Record",
                            "original_name": "Different Credit Record",
                            "profile_path": None,
                        }
                    ]
                }

            def search_person(self, query, *, language="ja-JP"):
                if query == "山田邦子":
                    return {
                        "results": [
                            {
                                "id": 1964804,
                                "name": "山田邦子",
                                "original_name": "山田邦子",
                                "profile_path": "/yamada.jpg",
                            }
                        ]
                    }
                return {"results": []}

            def person_combined_credits(self, person_id, *, language="ja-JP"):
                self.combined_calls += 1
                return {
                    "cast": [
                        {"id": 155375, "media_type": "tv", "name": "トップスチュワーデス物語"}
                    ]
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, work_id = self._database_with_work(root, "山田邦子")
            client = CombinedClient()

            def downloader(remote_path, destination, *, size):
                target = Path(destination)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"profile")
                return target

            with connect(db) as connection:
                result = sync_cast_people_for_work(
                    connection,
                    client,
                    work_id=work_id,
                    media_type="tv",
                    tmdb_id=155375,
                    local_cast="山田邦子",
                    image_root=root / "TMDbImages",
                    image_downloader=downloader,
                )
                link = connection.execute(
                    "SELECT local_name,tmdb_person_id FROM tmdb_work_people"
                ).fetchone()

            self.assertEqual(result["matched"], 1)
            self.assertEqual(result["matchedBySearch"], 0)
            self.assertEqual(result["matchedByCombinedCredits"], 1)
            self.assertEqual((link["local_name"], link["tmdb_person_id"]), ("山田邦子", 1964804))
            self.assertEqual(client.combined_calls, 1)
            self.assertTrue(cached_person_image_path(root / "TMDbImages", 1964804, "/yamada.jpg").is_file())

    def test_third_match_rejects_search_person_without_target_work_in_combined_credits(self):
        class CombinedRejectClient:
            def tv_aggregate_credits(self, tv_id, *, language="ja-JP"):
                return {"cast": [{"id": 777, "name": "Other", "original_name": "Other"}]}

            def search_person(self, query, *, language="ja-JP"):
                return {
                    "results": [
                        {"id": 1964804, "name": "山田邦子（別人）", "original_name": "山田邦子（別人）", "profile_path": "/wrong.jpg"}
                    ]
                }

            def person_combined_credits(self, person_id, *, language="ja-JP"):
                return {"cast": [{"id": 999999, "media_type": "tv", "name": "別作品"}]}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, work_id = self._database_with_work(root, "山田邦子")
            with connect(db) as connection:
                result = sync_cast_people_for_work(
                    connection,
                    CombinedRejectClient(),
                    work_id=work_id,
                    media_type="tv",
                    tmdb_id=155375,
                    local_cast="山田邦子",
                    image_root=root / "TMDbImages",
                    image_downloader=lambda *args, **kwargs: None,
                )
                count = int(connection.execute("SELECT COUNT(*) FROM tmdb_work_people").fetchone()[0])

            self.assertEqual(result["matched"], 0)
            self.assertEqual(result["matchedByCombinedCredits"], 0)
            self.assertEqual(count, 0)

    def test_third_match_runs_even_when_work_credits_are_empty(self):
        class EmptyCreditsCombinedClient:
            def tv_aggregate_credits(self, tv_id, *, language="ja-JP"):
                return {"cast": []}

            def search_person(self, query, *, language="ja-JP"):
                return {
                    "results": [
                        {
                            "id": 1964804,
                            "name": "山田邦子",
                            "original_name": "山田邦子",
                            "profile_path": "/yamada.jpg",
                        }
                    ]
                }

            def person_combined_credits(self, person_id, *, language="ja-JP"):
                return {"cast": [{"id": 155375, "media_type": "tv", "name": "トップスチュワーデス物語"}]}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, work_id = self._database_with_work(root, "山田邦子")

            def downloader(remote_path, destination, *, size):
                target = Path(destination)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"profile")
                return target

            with connect(db) as connection:
                result = sync_cast_people_for_work(
                    connection,
                    EmptyCreditsCombinedClient(),
                    work_id=work_id,
                    media_type="tv",
                    tmdb_id=155375,
                    local_cast="山田邦子",
                    image_root=root / "TMDbImages",
                    image_downloader=downloader,
                )

            self.assertEqual(result["matched"], 1)
            self.assertEqual(result["matchedByCombinedCredits"], 1)
            self.assertEqual(result["matchedByUniqueExactSearch"], 0)

    def test_fourth_match_accepts_only_one_exact_person_search_result(self):
        class UniqueExactClient:
            def tv_aggregate_credits(self, tv_id, *, language="ja-JP"):
                return {"cast": [{"id": 999, "name": "別の出演者", "original_name": "別の出演者"}]}

            def search_person(self, query, *, language="ja-JP"):
                return {
                    "results": [
                        {
                            "id": 1698670,
                            "name": "井森美幸",
                            "original_name": "井森美幸",
                            "profile_path": "/imori.jpg",
                        }
                    ]
                }

            def person_combined_credits(self, person_id, *, language="ja-JP"):
                return {"cast": []}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, work_id = self._database_with_work(root, "井森美幸")

            def downloader(remote_path, destination, *, size):
                target = Path(destination)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"profile")
                return target

            with connect(db) as connection:
                result = sync_cast_people_for_work(
                    connection,
                    UniqueExactClient(),
                    work_id=work_id,
                    media_type="tv",
                    tmdb_id=155375,
                    local_cast="井森美幸",
                    image_root=root / "TMDbImages",
                    image_downloader=downloader,
                )
                link = connection.execute(
                    "SELECT local_name,tmdb_person_id FROM tmdb_work_people"
                ).fetchone()

            self.assertEqual(result["matched"], 1)
            self.assertEqual(result["matchedByUniqueExactSearch"], 1)
            self.assertEqual((link["local_name"], link["tmdb_person_id"]), ("井森美幸", 1698670))

    def test_fourth_match_rejects_non_exact_or_multiple_exact_search_results(self):
        class SearchClient:
            def __init__(self, results):
                self.results = results

            def tv_aggregate_credits(self, tv_id, *, language="ja-JP"):
                return {"cast": [{"id": 999, "name": "別の出演者", "original_name": "別の出演者"}]}

            def search_person(self, query, *, language="ja-JP"):
                return {"results": list(self.results)}

            def person_combined_credits(self, person_id, *, language="ja-JP"):
                return {"cast": []}

        cases = [
            [{"id": 1, "name": "井森 美幸子", "original_name": "井森 美幸子", "profile_path": "/x.jpg"}],
            [
                {"id": 1, "name": "井森美幸", "original_name": "井森美幸", "profile_path": "/a.jpg"},
                {"id": 2, "name": "井森美幸", "original_name": "井森美幸", "profile_path": "/b.jpg"},
            ],
        ]
        for results in cases:
            with self.subTest(results=results), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                db, work_id = self._database_with_work(root, "井森美幸")
                with connect(db) as connection:
                    result = sync_cast_people_for_work(
                        connection,
                        SearchClient(results),
                        work_id=work_id,
                        media_type="tv",
                        tmdb_id=155375,
                        local_cast="井森美幸",
                        image_root=root / "TMDbImages",
                        image_downloader=lambda *args, **kwargs: None,
                    )
                    count = int(connection.execute("SELECT COUNT(*) FROM tmdb_work_people").fetchone()[0])
                self.assertEqual(result["matchedByUniqueExactSearch"], 0)
                self.assertEqual(count, 0)

    def test_fifth_match_accepts_exact_alias_from_person_details_within_work_credits(self):
        class AliasClient:
            def __init__(self):
                self.details_calls = 0

            def tv_aggregate_credits(self, tv_id, *, language="ja-JP"):
                return {
                    "cast": [
                        {
                            "id": 5001,
                            "name": "Yuki Kohara",
                            "original_name": "Yuki Kohara",
                            "profile_path": None,
                            "order": 2,
                        },
                        {
                            "id": 5002,
                            "name": "Other Actor",
                            "original_name": "Other Actor",
                            "profile_path": "/other.jpg",
                            "order": 1,
                        },
                    ]
                }

            def search_person(self, query, *, language="ja-JP"):
                return {"results": []}

            def person_combined_credits(self, person_id, *, language="ja-JP"):
                return {"cast": []}

            def person_details(self, person_id, *, language="ja-JP"):
                self.details_calls += 1
                if int(person_id) == 5001:
                    return {
                        "id": 5001,
                        "name": "Yuki Kohara",
                        "also_known_as": ["小原裕貴"],
                        "profile_path": "/kohara.jpg",
                        "known_for_department": "Acting",
                    }
                return {
                    "id": int(person_id),
                    "name": "Other Actor",
                    "also_known_as": [],
                    "profile_path": "/other.jpg",
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, work_id = self._database_with_work(root, "小原裕貴")
            client = AliasClient()

            def downloader(remote_path, destination, *, size):
                target = Path(destination)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"profile")
                return target

            with connect(db) as connection:
                result = sync_cast_people_for_work(
                    connection,
                    client,
                    work_id=work_id,
                    media_type="tv",
                    tmdb_id=83890,
                    local_cast="小原裕貴",
                    image_root=root / "TMDbImages",
                    image_downloader=downloader,
                )
                link = connection.execute(
                    "SELECT local_name,tmdb_person_id FROM tmdb_work_people"
                ).fetchone()

            self.assertEqual(result["matched"], 1)
            self.assertEqual(result["matchedByCreditAlias"], 1)
            self.assertEqual((link["local_name"], link["tmdb_person_id"]), ("小原裕貴", 5001))
            self.assertTrue(cached_person_image_path(root / "TMDbImages", 5001, "/kohara.jpg").is_file())
            self.assertEqual(client.details_calls, 2)

    def test_fifth_match_rejects_multiple_or_partial_alias_matches(self):
        class AliasClient:
            def __init__(self, aliases):
                self.aliases = aliases

            def movie_credits(self, movie_id, *, language="ja-JP"):
                return {
                    "cast": [
                        {"id": 1, "name": "Actor One", "original_name": "Actor One", "order": 0},
                        {"id": 2, "name": "Actor Two", "original_name": "Actor Two", "order": 1},
                    ]
                }

            def search_person(self, query, *, language="ja-JP"):
                return {"results": []}

            def person_combined_credits(self, person_id, *, language="ja-JP"):
                return {"cast": []}

            def person_details(self, person_id, *, language="ja-JP"):
                return {
                    "id": int(person_id),
                    "name": f"Actor {person_id}",
                    "also_known_as": list(self.aliases.get(int(person_id), [])),
                    "profile_path": "/x.jpg",
                }

        cases = [
            {1: ["対象人物"], 2: ["対象人物"]},
            {1: ["対象人物X"], 2: []},
        ]
        for aliases in cases:
            with self.subTest(aliases=aliases), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                db, work_id = self._database_with_work(root, "対象人物")
                with connect(db) as connection:
                    result = sync_cast_people_for_work(
                        connection,
                        AliasClient(aliases),
                        work_id=work_id,
                        media_type="movie",
                        tmdb_id=1,
                        local_cast="対象人物",
                        image_root=root / "TMDbImages",
                        image_downloader=lambda *args, **kwargs: None,
                    )
                    count = int(connection.execute("SELECT COUNT(*) FROM tmdb_work_people").fetchone()[0])
                self.assertEqual(result["matchedByCreditAlias"], 0)
                self.assertEqual(count, 0)

    def test_person_details_are_cached_across_repeat_alias_syncs(self):
        class AliasClient:
            def __init__(self):
                self.detail_calls = 0
                self.credit_calls = 0

            def movie_credits(self, movie_id, *, language="ja-JP"):
                self.credit_calls += 1
                return {
                    "cast": [
                        {"id": 7001, "name": "Romanized Name", "original_name": "Romanized Name", "order": 0}
                    ]
                }

            def search_person(self, query, *, language="ja-JP"):
                return {"results": []}

            def person_combined_credits(self, person_id, *, language="ja-JP"):
                return {"cast": []}

            def person_details(self, person_id, *, language="ja-JP"):
                self.detail_calls += 1
                return {
                    "id": 7001,
                    "name": "Romanized Name",
                    "also_known_as": ["日本語名"],
                    "profile_path": "/p.jpg",
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, work_id = self._database_with_work(root, "日本語名")
            client = AliasClient()

            def downloader(remote_path, destination, *, size):
                target = Path(destination)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"profile")
                return target

            with connect(db) as connection:
                for _ in range(2):
                    sync_cast_people_for_work(
                        connection,
                        client,
                        work_id=work_id,
                        media_type="movie",
                        tmdb_id=77,
                        local_cast="日本語名",
                        image_root=root / "TMDbImages",
                        image_downloader=downloader,
                    )

            self.assertEqual(client.credit_calls, 1)
            self.assertEqual(client.detail_calls, 1)

    def test_non_exact_person_search_result_outside_work_credits_is_rejected(self):
        class WrongSearchClient:
            def movie_credits(self, movie_id, *, language="ja-JP"):
                return {
                    "cast": [
                        {"id": 10, "name": "Actor Ten", "original_name": "Actor Ten", "profile_path": "/ten.jpg"}
                    ]
                }

            def search_person(self, query, *, language="ja-JP"):
                return {
                    "results": [
                        {"id": 999, "name": "別名俳優X", "original_name": "別名俳優X", "profile_path": "/wrong.jpg"}
                    ]
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, work_id = self._database_with_work(root, "別名俳優")
            with connect(db) as connection:
                result = sync_cast_people_for_work(
                    connection,
                    WrongSearchClient(),
                    work_id=work_id,
                    media_type="movie",
                    tmdb_id=1,
                    local_cast="別名俳優",
                    image_root=root / "TMDbImages",
                    image_downloader=lambda *args, **kwargs: None,
                )
                count = int(connection.execute("SELECT COUNT(*) FROM tmdb_work_people").fetchone()[0])

            self.assertEqual(result["matched"], 0)
            self.assertEqual(result["matchedBySearch"], 0)
            self.assertEqual(count, 0)

    def test_current_name_inside_annotation_can_match_credit_without_search(self):
        class CurrentNameClient:
            def movie_credits(self, movie_id, *, language="ja-JP"):
                return {
                    "cast": [
                        {
                            "id": 2151537,
                            "name": "水上恒司",
                            "original_name": "水上恒司",
                            "profile_path": "/mizukami.jpg",
                            "order": 0,
                        }
                    ]
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, work_id = self._database_with_work(root, "岡田健史（現・水上恒司）")
            with connect(db) as connection:
                result = sync_cast_people_for_work(
                    connection,
                    CurrentNameClient(),
                    work_id=work_id,
                    media_type="movie",
                    tmdb_id=1,
                    local_cast="岡田健史（現・水上恒司）",
                    image_root=root / "TMDbImages",
                    image_downloader=lambda remote_path, destination, *, size: Path(destination),
                )
                link = connection.execute(
                    "SELECT local_name,tmdb_person_id FROM tmdb_work_people"
                ).fetchone()

            self.assertEqual(result["matched"], 1)
            self.assertEqual(result["matchedExact"], 1)
            self.assertEqual(result["matchedBySearch"], 0)
            self.assertEqual(link["tmdb_person_id"], 2151537)

    def test_secondary_search_failure_preserves_existing_mapping(self):
        class FailingSearchClient:
            def movie_credits(self, movie_id, *, language="ja-JP"):
                return {
                    "cast": [
                        {
                            "id": 8891,
                            "name": "John Travolta",
                            "original_name": "John Travolta",
                            "profile_path": "/travolta.jpg",
                        }
                    ]
                }

            def search_person(self, query, *, language="ja-JP"):
                raise RuntimeError("temporary search failure")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, work_id = self._database_with_work(root, "ジョン・トラボルタ")
            with connect(db) as connection:
                stamp = now_iso()
                connection.execute(
                    """
                    INSERT INTO tmdb_people(
                        tmdb_person_id,display_name,original_name,profile_path,known_for_department,
                        synced_at,created_at,updated_at
                    ) VALUES(500,'Previous Actor','Previous Actor','/old.jpg','Acting',?,?,?)
                    """,
                    (stamp, stamp, stamp),
                )
                connection.execute(
                    """
                    INSERT INTO tmdb_work_people(
                        work_id,role,local_name,tmdb_person_id,created_at,updated_at
                    ) VALUES(?,'CAST','ジョン・トラボルタ',500,?,?)
                    """,
                    (work_id, stamp, stamp),
                )
                connection.commit()

                with self.assertRaises(RuntimeError):
                    sync_cast_people_for_work(
                        connection,
                        FailingSearchClient(),
                        work_id=work_id,
                        media_type="movie",
                        tmdb_id=1,
                        local_cast="ジョン・トラボルタ",
                        image_root=root / "TMDbImages",
                        image_downloader=lambda *args, **kwargs: None,
                    )

                row = connection.execute(
                    "SELECT tmdb_person_id FROM tmdb_work_people WHERE work_id=? AND local_name='ジョン・トラボルタ'",
                    (work_id,),
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(int(row["tmdb_person_id"]), 500)

    def test_people_directory_splits_compound_names_and_removes_role_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, work_id = self._database_with_work(
                root,
                "戸次重幸／櫻井翔、小林薫 ほか（各話ゲスト）、櫻井孝宏（声）",
            )
            with connect(db) as connection:
                people = list_people(connection, role="cast")
            names = {item["name"] for item in people["items"]}
            self.assertEqual(names, {"戸次重幸", "櫻井翔", "小林薫", "櫻井孝宏"})

    def test_credits_api_payload_is_cached_between_syncs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, work_id = self._database_with_work(root, "仲間由紀恵")
            client = CreditsClient()

            def downloader(remote_path, destination, *, size):
                target = Path(destination)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"profile")
                return target

            with connect(db) as connection:
                for _ in range(2):
                    sync_cast_people_for_work(
                        connection,
                        client,
                        work_id=work_id,
                        media_type="movie",
                        tmdb_id=1000,
                        local_cast="仲間由紀恵",
                        image_root=root / "TMDbImages",
                        image_downloader=downloader,
                    )
            self.assertEqual(client.movie_calls, 1)

    def test_sixth_match_uses_reviewed_alias_only_inside_current_work_credits(self):
        class ReviewedAliasClient:
            def movie_credits(self, movie_id, *, language="ja-JP"):
                return {
                    "cast": [
                        {
                            "id": 1201,
                            "name": "Simon Callow",
                            "original_name": "Simon Callow",
                            "profile_path": "/callow.jpg",
                            "order": 3,
                        },
                        {
                            "id": 1202,
                            "name": "Other Actor",
                            "original_name": "Other Actor",
                            "profile_path": "/other.jpg",
                            "order": 1,
                        },
                    ]
                }

            def search_person(self, query, *, language="ja-JP"):
                return {"results": []}

            def person_combined_credits(self, person_id, *, language="ja-JP"):
                return {"cast": []}

            def person_details(self, person_id, *, language="ja-JP"):
                if int(person_id) == 1201:
                    return {
                        "id": 1201,
                        "name": "Simon Callow",
                        "also_known_as": [],
                        "profile_path": "/callow.jpg",
                        "known_for_department": "Acting",
                    }
                return {
                    "id": int(person_id),
                    "name": "Other Actor",
                    "also_known_as": [],
                    "profile_path": "/other.jpg",
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, work_id = self._database_with_work(root, "サイモン・キャロウ")

            def downloader(remote_path, destination, *, size):
                target = Path(destination)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"profile")
                return target

            with connect(db) as connection:
                result = sync_cast_people_for_work(
                    connection,
                    ReviewedAliasClient(),
                    work_id=work_id,
                    media_type="movie",
                    tmdb_id=712,
                    local_cast="サイモン・キャロウ",
                    image_root=root / "TMDbImages",
                    image_downloader=downloader,
                )
                link = connection.execute(
                    "SELECT local_name,tmdb_person_id FROM tmdb_work_people"
                ).fetchone()

            self.assertEqual(result["matched"], 1)
            self.assertEqual(result["matchedByReviewedAlias"], 1)
            self.assertEqual((link["local_name"], link["tmdb_person_id"]), ("サイモン・キャロウ", 1201))
            self.assertTrue(cached_person_image_path(root / "TMDbImages", 1201, "/callow.jpg").is_file())

    def test_sixth_match_supports_reviewed_korean_and_romanized_credit_aliases(self):
        class Client:
            def movie_credits(self, movie_id, *, language="ja-JP"):
                if int(movie_id) == 670:
                    return {
                        "cast": [
                            {"id": 201, "name": "유지태", "original_name": "유지태", "profile_path": "/yoo.jpg", "order": 1}
                        ]
                    }
                return {
                    "cast": [
                        {"id": 202, "name": "Yuki Kohara", "original_name": "Yuki Kohara", "profile_path": "/kohara.jpg", "order": 4}
                    ]
                }

            def search_person(self, query, *, language="ja-JP"):
                return {"results": []}

            def person_combined_credits(self, person_id, *, language="ja-JP"):
                return {"cast": []}

            def person_details(self, person_id, *, language="ja-JP"):
                return {}

        cases = [
            ("ユ・ジテ", 670, 201),
            ("小原裕貴", 83890, 202),
        ]
        for local_name, tmdb_id, expected_id in cases:
            with self.subTest(local_name=local_name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                db, work_id = self._database_with_work(root, local_name)

                def downloader(remote_path, destination, *, size):
                    target = Path(destination)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b"profile")
                    return target

                with connect(db) as connection:
                    result = sync_cast_people_for_work(
                        connection,
                        Client(),
                        work_id=work_id,
                        media_type="movie",
                        tmdb_id=tmdb_id,
                        local_cast=local_name,
                        image_root=root / "TMDbImages",
                        image_downloader=downloader,
                    )
                    link = connection.execute(
                        "SELECT tmdb_person_id FROM tmdb_work_people"
                    ).fetchone()

                self.assertEqual(result["matchedByReviewedAlias"], 1)
                self.assertEqual(int(link["tmdb_person_id"]), expected_id)

    def test_sixth_match_rejects_multiple_reviewed_alias_person_ids(self):
        class Client:
            def movie_credits(self, movie_id, *, language="ja-JP"):
                return {
                    "cast": [
                        {"id": 1, "name": "ジョン・トラヴォルタ", "original_name": "ジョン・トラヴォルタ", "order": 0},
                        {"id": 2, "name": "John Travolta", "original_name": "John Travolta", "order": 1},
                    ]
                }

            def search_person(self, query, *, language="ja-JP"):
                return {"results": []}

            def person_combined_credits(self, person_id, *, language="ja-JP"):
                return {"cast": []}

            def person_details(self, person_id, *, language="ja-JP"):
                return {}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, work_id = self._database_with_work(root, "ジョン・トラボルタ")
            with connect(db) as connection:
                result = sync_cast_people_for_work(
                    connection,
                    Client(),
                    work_id=work_id,
                    media_type="movie",
                    tmdb_id=680,
                    local_cast="ジョン・トラボルタ",
                    image_root=root / "TMDbImages",
                    image_downloader=lambda *args, **kwargs: None,
                )
                count = int(connection.execute("SELECT COUNT(*) FROM tmdb_work_people").fetchone()[0])
            self.assertEqual(result["matchedByReviewedAlias"], 0)
            self.assertEqual(count, 0)

    def test_akane_reviewed_alias_uses_tmdb_credit_spelling(self):
        self.assertEqual(REVIEWED_PERSON_CREDIT_ALIASES["茜音"], ("紅音",))

    def test_reviewed_alias_map_covers_current_real_audit_credit_not_found_names(self):
        expected = {
            "千紗", "茜音",
            "サイモン・キャロウ", "ジョン・トラボルタ", "ウィリアム・サドラー", "ジェマ・ジョーンズ",
            "ジョー・ヴィテレリ", "ユ・ジテ", "カン・ヘジョン", "キム・ビョンオク",
            "ニッキー・ブロンスキー", "カム・ジガンデイ", "クロティルド・モレ",
            "F・マーレイ・エイブラハム", "アンダーズ・ホーム", "ブレット・カレン",
            "リンダ・メイ", "スワンキー", "ボブ・ウェルズ", "トルーマン・ハンクス",
            "キリアン・マーフィー", "ジェイデン・マーテル", "セイディ・ソヴラル",
            "ニコラス・ガリツィン", "増田康好", "渡辺千秋", "小原裕貴", "藤井萩花",
        }
        self.assertEqual(set(REVIEWED_PERSON_CREDIT_ALIASES), expected)

    def test_seventh_match_uses_reviewed_work_person_override_only_for_exact_work(self):
        class Client:
            def tv_aggregate_credits(self, tv_id, *, language="ja-JP"):
                return {"cast": []}

            def search_person(self, query, *, language="ja-JP"):
                return {"results": []}

            def person_combined_credits(self, person_id, *, language="ja-JP"):
                return {"cast": []}

            def person_details(self, person_id, *, language="ja-JP"):
                if int(person_id) == 107961:
                    return {
                        "id": 107961,
                        "name": "石坂浩二",
                        "original_name": "石坂浩二",
                        "profile_path": "/ishizaka.jpg",
                        "known_for_department": "Acting",
                    }
                return {}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, work_id = self._database_with_work(root, "石坂浩二")

            def downloader(remote_path, destination, *, size):
                target = Path(destination)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"profile")
                return target

            with connect(db) as connection:
                result = sync_cast_people_for_work(
                    connection,
                    Client(),
                    work_id=work_id,
                    media_type="tv",
                    tmdb_id=38041,
                    local_cast="石坂浩二",
                    image_root=root / "TMDbImages",
                    image_downloader=downloader,
                )
                link = connection.execute(
                    "SELECT local_name,tmdb_person_id FROM tmdb_work_people"
                ).fetchone()

            self.assertEqual(result["matchedByReviewedWorkPerson"], 1)
            self.assertEqual((link["local_name"], link["tmdb_person_id"]), ("石坂浩二", 107961))
            self.assertTrue(cached_person_image_path(root / "TMDbImages", 107961, "/ishizaka.jpg").is_file())

            with connect(db) as connection:
                result = sync_cast_people_for_work(
                    connection,
                    Client(),
                    work_id=work_id,
                    media_type="tv",
                    tmdb_id=999999,
                    local_cast="石坂浩二",
                    image_root=root / "TMDbImages",
                    image_downloader=downloader,
                )
            self.assertEqual(result["matchedByReviewedWorkPerson"], 0)

    def test_seventh_match_rejects_person_details_id_mismatch(self):
        class Client:
            def tv_aggregate_credits(self, tv_id, *, language="ja-JP"):
                return {"cast": []}

            def search_person(self, query, *, language="ja-JP"):
                return {"results": []}

            def person_combined_credits(self, person_id, *, language="ja-JP"):
                return {"cast": []}

            def person_details(self, person_id, *, language="ja-JP"):
                return {"id": 999999, "name": "石坂浩二", "profile_path": "/wrong.jpg"}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, work_id = self._database_with_work(root, "石坂浩二")
            with connect(db) as connection:
                result = sync_cast_people_for_work(
                    connection,
                    Client(),
                    work_id=work_id,
                    media_type="tv",
                    tmdb_id=38041,
                    local_cast="石坂浩二",
                    image_root=root / "TMDbImages",
                    image_downloader=lambda *args, **kwargs: None,
                )
                count = int(connection.execute("SELECT COUNT(*) FROM tmdb_work_people").fetchone()[0])
            self.assertEqual(result["matchedByReviewedWorkPerson"], 0)
            self.assertEqual(count, 0)

    def test_reviewed_work_person_map_covers_current_audited_overrides(self):
        self.assertEqual(
            REVIEWED_WORK_PERSON_OVERRIDES,
            {
                ("tv", 38041, "石坂浩二"): 107961,
                ("tv", 41756, "DAIGO"): 1111225,
                ("tv", 46107, "大泉洋"): 40450,
                ("tv", 83850, "春川恭亮"): 2661404,
                ("tv", 70214, "TAKAHIRO"): 1448214,
                ("tv", 63440, "郭智博"): 20345,
                ("tv", 109233, "EXILE NAOTO"): 2201144,
            },
        )
        self.assertEqual(REVIEWED_PERSON_CREDIT_ALIASES["千紗"], ("CHISA",))

    def test_half_moon_wrong_anime_link_is_repaired_before_people_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "library.db"
            with connect(db) as connection:
                initialize_database(connection)
                stamp = now_iso()
                connection.execute(
                    """
                    INSERT INTO works(
                        external_work_no,category,year_or_period,official_title,
                        main_cast_or_voice_actors,created_at,updated_at
                    ) VALUES(1,'日本映画・ドラマ','2006','半分の月がのぼる空','中山卓也',?,?)
                    """,
                    (stamp, stamp),
                )
                work_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
                connection.execute(
                    """
                    INSERT INTO tmdb_work_links(
                        work_id,media_type,tmdb_id,match_status,confidence,matched_title,matched_year,
                        created_at,updated_at
                    ) VALUES(?,'tv',34746,'MATCHED',1.0,'半分の月がのぼる空','2006',?,?)
                    """,
                    (work_id, stamp, stamp),
                )
                connection.execute(
                    """
                    INSERT INTO tmdb_people(
                        tmdb_person_id,display_name,profile_path,created_at,updated_at
                    ) VALUES(999,'誤人物','/wrong.jpg',?,?)
                    """,
                    (stamp, stamp),
                )
                connection.execute(
                    """
                    INSERT INTO tmdb_work_people(
                        work_id,role,local_name,tmdb_person_id,created_at,updated_at
                    ) VALUES(?,'CAST','中山卓也',999,?,?)
                    """,
                    (work_id, stamp, stamp),
                )
                connection.commit()

                self.assertEqual(repair_reviewed_bad_work_links(connection), 1)
                link = connection.execute(
                    "SELECT media_type,tmdb_id,match_status,matched_title FROM tmdb_work_links WHERE work_id=?",
                    (work_id,),
                ).fetchone()
                people_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM tmdb_work_people WHERE work_id=?",
                        (work_id,),
                    ).fetchone()[0]
                )

            self.assertEqual(link["match_status"], "UNMATCHED")
            self.assertIsNone(link["media_type"])
            self.assertIsNone(link["tmdb_id"])
            self.assertIsNone(link["matched_title"])
            self.assertEqual(people_count, 0)

    def test_ambiguous_same_name_is_not_auto_matched(self):
        class AmbiguousClient:
            def movie_credits(self, movie_id, *, language="ja-JP"):
                return {
                    "cast": [
                        {"id": 1, "name": "同名俳優", "original_name": "同名俳優", "profile_path": "/a.jpg"},
                        {"id": 2, "name": "同名俳優", "original_name": "同名俳優", "profile_path": "/b.jpg"},
                    ]
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, work_id = self._database_with_work(root, "同名俳優")
            with connect(db) as connection:
                result = sync_cast_people_for_work(
                    connection,
                    AmbiguousClient(),
                    work_id=work_id,
                    media_type="movie",
                    tmdb_id=10,
                    local_cast="同名俳優",
                    image_root=root / "TMDbImages",
                    image_downloader=lambda *args, **kwargs: None,
                )
                count = int(connection.execute("SELECT COUNT(*) FROM tmdb_work_people").fetchone()[0])
            self.assertEqual(result["matched"], 0)
            self.assertEqual(count, 0)

    def test_people_sync_v1_marker_requires_v2_resync(self):
        from tmdb_cache import put_cached_json

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            with connect(db) as connection:
                initialize_database(connection)
                put_cached_json(
                    connection,
                    "tmdb:people-sync-version",
                    {"version": 1},
                    fetched_at=now_iso(),
                    expires_at=None,
                )
                connection.commit()
                self.assertTrue(people_sync_required(connection))

    def test_people_sync_v2_marker_requires_v3_resync(self):
        from tmdb_cache import put_cached_json

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            with connect(db) as connection:
                initialize_database(connection)
                put_cached_json(
                    connection,
                    "tmdb:people-sync-version",
                    {"version": 2},
                    fetched_at=now_iso(),
                    expires_at=None,
                )
                connection.commit()
                self.assertTrue(people_sync_required(connection))

    def test_people_sync_v3_marker_requires_v4_resync(self):
        from tmdb_cache import put_cached_json

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            with connect(db) as connection:
                initialize_database(connection)
                put_cached_json(
                    connection,
                    "tmdb:people-sync-version",
                    {"version": 3},
                    fetched_at=now_iso(),
                    expires_at=None,
                )
                connection.commit()
                self.assertTrue(people_sync_required(connection))

    def test_people_sync_v4_marker_requires_v5_resync(self):
        from tmdb_cache import put_cached_json

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            with connect(db) as connection:
                initialize_database(connection)
                put_cached_json(
                    connection,
                    "tmdb:people-sync-version",
                    {"version": 4},
                    fetched_at=now_iso(),
                    expires_at=None,
                )
                connection.commit()
                self.assertTrue(people_sync_required(connection))

    def test_people_sync_v5_marker_requires_v6_resync(self):
        from tmdb_cache import put_cached_json

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            with connect(db) as connection:
                initialize_database(connection)
                put_cached_json(
                    connection,
                    "tmdb:people-sync-version",
                    {"version": 5},
                    fetched_at=now_iso(),
                    expires_at=None,
                )
                connection.commit()
                self.assertTrue(people_sync_required(connection))

    def test_people_sync_v6_marker_requires_v7_resync(self):
        from tmdb_cache import put_cached_json

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            with connect(db) as connection:
                initialize_database(connection)
                put_cached_json(
                    connection,
                    "tmdb:people-sync-version",
                    {"version": 6},
                    fetched_at=now_iso(),
                    expires_at=None,
                )
                connection.commit()
                self.assertTrue(people_sync_required(connection))

    def test_people_sync_v7_marker_requires_v8_resync(self):
        from tmdb_cache import put_cached_json

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            with connect(db) as connection:
                initialize_database(connection)
                put_cached_json(
                    connection,
                    "tmdb:people-sync-version",
                    {"version": 7},
                    fetched_at=now_iso(),
                    expires_at=None,
                )
                connection.commit()
                self.assertTrue(people_sync_required(connection))

    def test_people_sync_marker_is_one_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "library.db"
            with connect(db) as connection:
                initialize_database(connection)
                self.assertTrue(people_sync_required(connection))
                mark_people_sync_complete(connection)
                connection.commit()
                self.assertFalse(people_sync_required(connection))

    def test_launcher_starts_background_people_sync_after_browser_start(self):
        launcher = (SRC / "launcher.py").read_text(encoding="utf-8")
        self.assertIn("def _start_people_sync_if_needed", launcher)
        self.assertIn("sync_tmdb_people_library(", launcher)
        self.assertIn("self.open_browser()", launcher)
        self.assertIn("self._start_people_sync_if_needed()", launcher)
        self.assertIn("次回起動時に自動再試行します", launcher)

    def test_person_image_is_served_through_local_application_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, work_id = self._database_with_work(root, "仲間由紀恵")
            images = root / "TMDbImages"
            with connect(db) as connection:
                stamp = now_iso()
                connection.execute(
                    """
                    INSERT INTO tmdb_people(
                        tmdb_person_id,display_name,original_name,profile_path,known_for_department,
                        synced_at,created_at,updated_at
                    ) VALUES(101,'仲間由紀恵','仲間由紀恵','/nakama.png','Acting',?,?,?)
                    """,
                    (stamp, stamp, stamp),
                )
                connection.execute(
                    """
                    INSERT INTO tmdb_work_people(
                        work_id,role,local_name,tmdb_person_id,created_at,updated_at
                    ) VALUES(?,'CAST','仲間由紀恵',101,?,?)
                    """,
                    (work_id, stamp, stamp),
                )
                connection.commit()
            target = cached_person_image_path(images, 101, "/nakama.png")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"fake-png")

            server = create_server(db, port=0, data_root=root)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urlopen(
                    f"http://127.0.0.1:{server.server_port}/tmdb-person-image/101",
                    timeout=10,
                ) as response:
                    body = response.read()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers.get_content_type(), "image/png")
                    self.assertEqual(body, b"fake-png")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
