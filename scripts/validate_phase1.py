from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from database import connect, foreign_key_error_count, quick_check  # noqa: E402
from metadata_importer import import_file, load_metadata  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("metadata", nargs="?", type=Path, default=ROOT / "metadata" / "video_library.json")
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()

    payload = load_metadata(args.metadata)
    expected_works = int(payload["summary"]["work_count"])
    expected_videos = int(payload["summary"]["media_file_count"])

    if args.database:
        database = args.database
        temporary = None
    else:
        temporary = tempfile.TemporaryDirectory()
        database = Path(temporary.name) / "library.db"

    result = import_file(args.metadata, database)
    with connect(database) as connection:
        works = connection.execute("SELECT COUNT(*) FROM works").fetchone()[0]
        videos = connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        files = connection.execute("SELECT COUNT(*) FROM video_files").fetchone()[0]
        zero_video_works = connection.execute(
            """
            SELECT w.external_work_no
            FROM works w
            LEFT JOIN videos v ON v.work_id = w.id
            GROUP BY w.id
            HAVING COUNT(v.id) = 0
            ORDER BY w.external_work_no
            """
        ).fetchall()
        check = quick_check(connection)
        fk_errors = foreign_key_error_count(connection)

    report = {
        "expected": {"works": expected_works, "videos": expected_videos},
        "database": {"works": works, "videos": videos, "videoFiles": files},
        "zeroVideoWorks": len(zero_video_works),
        "quickCheck": check,
        "foreignKeyErrors": fk_errors,
        "importResult": result,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

    ok = (
        works == expected_works
        and videos == expected_videos
        and files == expected_videos
        and check.casefold() == "ok"
        and fk_errors == 0
    )
    if temporary is not None:
        temporary.cleanup()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
