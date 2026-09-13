from __future__ import annotations

from typing import Any

ZERO_VIDEO_WORK_NOS = {42, 43, 59, 185}


def build_metadata(work_count: int = 440, video_count: int = 4869) -> dict[str, Any]:
    if work_count < len(ZERO_VIDEO_WORK_NOS):
        raise ValueError("work_count is too small")

    nonzero_work_nos = [n for n in range(1, work_count + 1) if n not in ZERO_VIDEO_WORK_NOS]
    if video_count < len(nonzero_work_nos):
        raise ValueError("video_count must allow at least one video per non-zero work")

    counts = {work_no: 1 for work_no in nonzero_work_nos}
    remaining = video_count - len(nonzero_work_nos)
    for index in range(remaining):
        work_no = nonzero_work_nos[index % len(nonzero_work_nos)]
        counts[work_no] += 1

    works: list[dict[str, Any]] = []
    file_no = 1
    for work_no in range(1, work_count + 1):
        files: list[dict[str, Any]] = []
        count = counts.get(work_no, 0)
        for episode_index in range(1, count + 1):
            filename = f"work-{work_no:03d}-ep-{episode_index:03d}.mp4"
            files.append(
                {
                    "file_no": file_no,
                    "subfolder": f"Season {((episode_index - 1) // 12) + 1}",
                    "filename": filename,
                    "extension": "MP4",
                    "relative_path": f"sample\\work-{work_no:03d}\\{filename}",
                    "official_japanese_title": f"テスト作品{work_no:03d}",
                    "series_or_season": f"テスト作品{work_no:03d} Season {((episode_index - 1) // 12) + 1}",
                    "episode_or_type": f"第{episode_index:02d}話",
                    "episode_title": f"テストエピソード{episode_index:03d}",
                    "verification": {
                        "url": "https://example.invalid/",
                        "status": "確認済",
                        "note": None,
                    },
                }
            )
            file_no += 1

        works.append(
            {
                "work_no": work_no,
                "category": "テスト",
                "year_or_period": "2026",
                "source_title": f"Test Work {work_no:03d}",
                "official_japanese_title": f"テスト作品{work_no:03d}",
                "media_file_count": count,
                "subtitle_file_count": 0,
                "subfolder_count": 0 if count == 0 else 1,
                "media_format": None if count == 0 else "MP4",
                "source_folder": f"work-{work_no:03d}",
                "relative_path": f"sample\\work-{work_no:03d}",
                "work_verification": {
                    "method": "CI synthetic fixture",
                    "note": "公開CI用の合成データ",
                    "url": "https://example.invalid/",
                },
                "credits": {
                    "director_or_direction": "テスト監督",
                    "main_cast_or_voice_actors": "テスト出演者",
                    "verification_note": "CI synthetic fixture",
                    "verification_url": "https://example.invalid/",
                    "verification_status": "確認済",
                },
                "files": files,
            }
        )

    return {
        "schema_version": "1.0",
        "generated_at": "2026-09-14T00:00:00+09:00",
        "source": {
            "file": "synthetic-ci-fixture.json",
            "source_version": "ci",
            "audit_status": "synthetic",
        },
        "summary": {
            "work_count": work_count,
            "media_file_count": video_count,
            "subtitle_file_count": 0,
            "categories": {"テスト": {"works": work_count, "media_files": video_count, "subtitle_files": 0}},
            "name_review_note_count": 0,
        },
        "works": works,
        "name_review_notes": [],
    }
