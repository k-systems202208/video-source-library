from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from database import connect, foreign_key_error_count, quick_check  # noqa: E402
from metadata_importer import import_file  # noqa: E402
from sample_metadata import build_metadata  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        metadata = temp_root / "fixture.json"
        database = temp_root / "library.db"
        metadata.write_text(json.dumps(build_metadata(), ensure_ascii=False), encoding="utf-8")

        result = import_file(metadata, database)
        with connect(database) as connection:
            report = {
                "works": connection.execute("SELECT COUNT(*) FROM works").fetchone()[0],
                "videos": connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0],
                "videoFiles": connection.execute("SELECT COUNT(*) FROM video_files").fetchone()[0],
                "quickCheck": quick_check(connection),
                "foreignKeyErrors": foreign_key_error_count(connection),
                "importResult": result,
            }

        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if (
            report["works"] == 440
            and report["videos"] == 4869
            and report["videoFiles"] == 4869
            and str(report["quickCheck"]).casefold() == "ok"
            and report["foreignKeyErrors"] == 0
        ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
