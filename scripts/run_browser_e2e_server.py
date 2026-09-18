from __future__ import annotations

import argparse
import base64
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from database import connect, now_iso
from metadata_importer import import_metadata
from sample_metadata import build_metadata
from server import create_server
from tmdb_images import cached_person_image_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the VideoLibrary Playwright E2E fixture server")
    parser.add_argument("--port", type=int, default=8876)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="video-library-e2e-") as temp:
        root = Path(temp)
        database = root / "library.db"
        video_root = root / "videos"
        video_root.mkdir(parents=True, exist_ok=True)

        with connect(database) as connection:
            result = import_metadata(
                connection,
                build_metadata(work_count=12, video_count=24),
            )
            first_work_id = int(
                connection.execute("SELECT id FROM works ORDER BY external_work_no LIMIT 1").fetchone()[0]
            )
            connection.execute(
                "UPDATE works SET main_cast_or_voice_actors='テスト出演者、写真なし出演者' WHERE id=?",
                (first_work_id,),
            )
            stamp = now_iso()
            connection.execute(
                """
                INSERT INTO tmdb_people(
                    tmdb_person_id,display_name,original_name,profile_path,known_for_department,
                    synced_at,created_at,updated_at
                ) VALUES(9001,'テスト出演者','テスト出演者','/e2e-profile.png','Acting',?,?,?)
                """,
                (stamp, stamp, stamp),
            )
            connection.execute(
                """
                INSERT INTO tmdb_work_people(
                    work_id,role,local_name,tmdb_person_id,billing_order,created_at,updated_at
                ) VALUES(?,'CAST','テスト出演者',9001,0,?,?)
                """,
                (first_work_id, stamp, stamp),
            )
            connection.commit()

        person_image = cached_person_image_path(root / "TMDbImages", 9001, "/e2e-profile.png")
        person_image.parent.mkdir(parents=True, exist_ok=True)
        person_image.write_bytes(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            )
        )

        server = create_server(
            database,
            host="127.0.0.1",
            port=args.port,
            video_root=video_root,
            data_root=root,
        )
        print(
            f"Playwright E2E fixture: http://127.0.0.1:{server.server_port}/ "
            f"({result['works']} works / {result['videos']} videos)",
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
