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
from scan_diagnostics import scan_diagnostics
from scan_runner import scan_library


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="VideoLibrary real-machine validation")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--video-root", type=Path, required=True)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--expected-works", type=int, default=440)
    parser.add_argument("--expected-videos", type=int, default=4869)
    parser.add_argument("--expected-subtitles", type=int, default=1234)
    parser.add_argument("--expected-matched-subtitles", type=int, default=1227)
    parser.add_argument("--expected-orphan-subtitles", type=int, default=7)
    parser.add_argument("--expected-unsupported-subtitles", type=int, default=3)
    parser.add_argument("--ffprobe", type=Path)
    return parser


def collect_validation_failures(
    result: dict,
    args: argparse.Namespace,
    *,
    ffprobe_enabled: bool,
) -> list[str]:
    failures: list[str] = []
    counts = result["counts"]
    diagnostics = result["diagnostics"]

    if result["quickCheck"].casefold() != "ok":
        failures.append("SQLite quick_check failed")
    if result["foreignKeyErrors"] != 0:
        failures.append("foreign key errors found")
    if counts["works"] != args.expected_works:
        failures.append("work count mismatch")
    if counts["videos"] != args.expected_videos:
        failures.append("video count mismatch")
    if counts["available_videos"] != args.expected_videos:
        failures.append("not all registered videos are available")
    if args.expected_subtitles >= 0 and counts["subtitles"] != args.expected_subtitles:
        failures.append("subtitle count mismatch")
    if (
        args.expected_matched_subtitles >= 0
        and counts["matched_subtitles"] != args.expected_matched_subtitles
    ):
        failures.append("matched subtitle count mismatch")
    if (
        args.expected_orphan_subtitles >= 0
        and diagnostics["orphanSubtitles"] != args.expected_orphan_subtitles
    ):
        failures.append("orphan subtitle count mismatch")
    if (
        args.expected_unsupported_subtitles >= 0
        and diagnostics["unsupportedSubtitles"] != args.expected_unsupported_subtitles
    ):
        failures.append("unsupported subtitle count mismatch")
    if diagnostics["unmatchedSubtitles"] != 0:
        failures.append("ambiguous unmatched subtitles remain")
    if diagnostics["missing"] != 0:
        failures.append("missing registered videos remain")
    if diagnostics["newFiles"] != 0:
        failures.append("new unregistered videos remain")
    if diagnostics["errors"] != 0:
        failures.append("scan diagnostic errors remain")

    judged_subtitles = counts["matched_subtitles"] + diagnostics["orphanSubtitles"]
    if args.expected_subtitles >= 0 and judged_subtitles != args.expected_subtitles:
        failures.append("not all supported subtitles are judged")

    if ffprobe_enabled and counts["probe_errors"]:
        failures.append("ffprobe errors remain")
    return failures


def main() -> int:
    args = build_parser().parse_args()

    if args.metadata:
        import_file(args.metadata, args.database)

    ffprobe = find_ffprobe(args.ffprobe)
    with connect(args.database) as connection:
        initialize_database(connection)
        scan = scan_library(connection, args.video_root, ffprobe_path=ffprobe)
        diagnostics = scan_diagnostics(connection, run_id=int(scan["runId"]))
        counts = connection.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM works) works,
              (SELECT COUNT(*) FROM videos) videos,
              (SELECT COUNT(*) FROM video_files WHERE is_available=1) available_videos,
              (SELECT COUNT(*) FROM subtitles WHERE is_available=1) subtitles,
              (SELECT COUNT(*) FROM subtitles WHERE is_available=1 AND video_id IS NOT NULL) matched_subtitles,
              (SELECT COUNT(*) FROM subtitles WHERE is_available=1 AND video_id IS NULL) unlinked_subtitles,
              (SELECT COUNT(*) FROM video_files WHERE probe_status='OK') probed_videos,
              (SELECT COUNT(*) FROM video_files WHERE probe_status='ERROR') probe_errors
            """
        ).fetchone()
        result = {
            "quickCheck": quick_check(connection),
            "foreignKeyErrors": foreign_key_error_count(connection),
            "ffprobe": str(ffprobe) if ffprobe else None,
            "scan": scan,
            "diagnostics": diagnostics["summary"],
            "counts": {key: int(counts[key]) for key in counts.keys()},
            "expected": {
                "works": args.expected_works,
                "videos": args.expected_videos,
                "subtitles": args.expected_subtitles,
                "matchedSubtitles": args.expected_matched_subtitles,
                "orphanSubtitles": args.expected_orphan_subtitles,
                "unsupportedSubtitles": args.expected_unsupported_subtitles,
            },
        }

    print(json.dumps(result, ensure_ascii=False, indent=2))

    failures = collect_validation_failures(
        result,
        args,
        ffprobe_enabled=ffprobe is not None,
    )
    if failures:
        print("FAILED:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("PASS: real library validation completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
