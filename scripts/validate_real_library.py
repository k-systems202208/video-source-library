from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from database import connect, foreign_key_error_count, initialize_database, quick_check
from media_probe import find_ffprobe
from metadata_importer import import_file
from scanner import scan_library


def main() -> int:
    parser = argparse.ArgumentParser(description="VideoLibrary real-machine validation")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--video-root", type=Path, required=True)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--expected-works", type=int, default=440)
    parser.add_argument("--expected-videos", type=int, default=4869)
    parser.add_argument("--expected-subtitles", type=int, default=1237)
    parser.add_argument("--ffprobe", type=Path)
    args = parser.parse_args()

    if args.metadata:
        import_file(args.metadata, args.database)

    ffprobe = find_ffprobe(args.ffprobe)
    with connect(args.database) as connection:
        initialize_database(connection)
        scan = scan_library(connection, args.video_root, ffprobe_path=ffprobe)
        counts = connection.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM works) works,
              (SELECT COUNT(*) FROM videos) videos,
              (SELECT COUNT(*) FROM video_files WHERE is_available=1) available_videos,
              (SELECT COUNT(*) FROM subtitles WHERE is_available=1) subtitles,
              (SELECT COUNT(*) FROM subtitles WHERE is_available=1 AND video_id IS NOT NULL) matched_subtitles,
              (SELECT COUNT(*) FROM subtitles WHERE is_available=1 AND video_id IS NULL) unmatched_subtitles,
              (SELECT COUNT(*) FROM video_files WHERE probe_status='OK') probed_videos,
              (SELECT COUNT(*) FROM video_files WHERE probe_status='ERROR') probe_errors
            """
        ).fetchone()
        result = {
            "quickCheck": quick_check(connection),
            "foreignKeyErrors": foreign_key_error_count(connection),
            "ffprobe": str(ffprobe) if ffprobe else None,
            "scan": scan,
            "counts": {key: int(counts[key]) for key in counts.keys()},
            "expected": {
                "works": args.expected_works,
                "videos": args.expected_videos,
                "subtitles": args.expected_subtitles,
            },
        }

    print(json.dumps(result, ensure_ascii=False, indent=2))

    failures: list[str] = []
    if result["quickCheck"].casefold() != "ok":
        failures.append("SQLite quick_check failed")
    if result["foreignKeyErrors"] != 0:
        failures.append("foreign key errors found")
    if result["counts"]["works"] != args.expected_works:
        failures.append("work count mismatch")
    if result["counts"]["videos"] != args.expected_videos:
        failures.append("video count mismatch")
    if result["counts"]["available_videos"] != args.expected_videos:
        failures.append("not all registered videos are available")
    if args.expected_subtitles >= 0 and result["counts"]["subtitles"] != args.expected_subtitles:
        failures.append("subtitle count mismatch")
    if result["counts"]["unmatched_subtitles"]:
        failures.append("unmatched subtitles remain")
    if ffprobe is not None and result["counts"]["probe_errors"]:
        failures.append("ffprobe errors remain")

    if failures:
        print("FAILED:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("PASS: real library validation completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
