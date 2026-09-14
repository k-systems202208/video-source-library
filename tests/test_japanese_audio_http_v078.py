from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from database import connect
from matroska_audio import (
    EBML_ID_FLAG_DEFAULT,
    EBML_ID_LANGUAGE,
    EBML_ID_NAME,
    EBML_ID_SEGMENT,
    EBML_ID_TRACKS,
    EBML_ID_TRACK_ENTRY,
    EBML_ID_TRACK_NUMBER,
    EBML_ID_TRACK_TYPE,
    preferred_japanese_audio_patch,
)
from metadata_importer import import_file
from sample_metadata import build_metadata
from server import create_server

EBML_HEADER = 0x1A45DFA3
CLUSTER = 0x1F43B675


def _id(value: int) -> bytes:
    return value.to_bytes((value.bit_length() + 7) // 8, "big")


def _size(value: int) -> bytes:
    for length in range(1, 9):
        if value <= (1 << (7 * length)) - 2:
            return ((1 << (7 * length)) | value).to_bytes(length, "big")
    raise ValueError("too large")


def _element(element_id: int, payload: bytes) -> bytes:
    return _id(element_id) + _size(len(payload)) + payload


def _uint(element_id: int, value: int) -> bytes:
    width = max(1, (value.bit_length() + 7) // 8)
    return _element(element_id, value.to_bytes(width, "big"))


def _track(number: int, track_type: int, language: str, default: int, name: str) -> bytes:
    payload = _uint(EBML_ID_TRACK_NUMBER, number)
    payload += _uint(EBML_ID_TRACK_TYPE, track_type)
    payload += _uint(EBML_ID_FLAG_DEFAULT, default)
    payload += _element(EBML_ID_LANGUAGE, language.encode("ascii"))
    payload += _element(EBML_ID_NAME, name.encode("utf-8"))
    return _element(EBML_ID_TRACK_ENTRY, payload)


def _dual_audio_mkv() -> bytes:
    tracks = _element(
        EBML_ID_TRACKS,
        _track(1, 1, "und", 1, "Video")
        + _track(2, 2, "eng", 1, "English 5.1 FLAC")
        + _track(3, 2, "jpn", 0, "Japanese 2.0 FLAC"),
    )
    return _element(EBML_HEADER, b"") + _element(
        EBML_ID_SEGMENT,
        tracks + _element(CLUSTER, b"0123456789abcdef"),
    )


class JapaneseAudioHttpV078Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.db_path = base / "library.db"
        self.video_root = base / "videos"
        self.video_root.mkdir()
        metadata_path = base / "fixture.json"
        payload = build_metadata(work_count=1, video_count=1)
        metadata_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        import_file(metadata_path, self.db_path)

        self.media = self.video_root / "dual.mkv"
        self.original = _dual_audio_mkv()
        self.media.write_bytes(self.original)
        stat = self.media.stat()
        with connect(self.db_path) as connection:
            row = connection.execute("SELECT id FROM videos ORDER BY id LIMIT 1").fetchone()
            self.video_id = int(row["id"])
            connection.execute(
                """
                UPDATE video_files
                SET relative_path='dual.mkv', filename='dual.mkv', extension='MKV',
                    file_size=?, modified_time_ns=?, is_available=1, scan_status='MATCHED'
                WHERE video_id=?
                """,
                (int(stat.st_size), int(stat.st_mtime_ns), self.video_id),
            )
            connection.commit()

        self.patch = preferred_japanese_audio_patch(self.media)
        self.assertIsNotNone(self.patch)
        expected = bytearray(self.original)
        expected[self.patch.offset:self.patch.offset + len(self.patch.data)] = self.patch.data
        self.expected = bytes(expected)

        self.server = create_server(
            self.db_path,
            host="127.0.0.1",
            port=0,
            video_root=self.video_root,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def test_full_delivery_prefers_japanese_without_touching_source_file(self):
        with urlopen(f"{self.base_url}/video/{self.video_id}") as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get("X-Video-Library-Audio-Preference"), "ja")
            self.assertEqual(response.read(), self.expected)
        self.assertEqual(self.media.read_bytes(), self.original)

    def test_range_overlapping_tracks_returns_patched_bytes_at_same_offsets(self):
        start = max(0, self.patch.offset - 3)
        end = min(len(self.original) - 1, self.patch.offset + 25)
        request = Request(
            f"{self.base_url}/video/{self.video_id}",
            headers={"Range": f"bytes={start}-{end}"},
        )
        with urlopen(request) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.headers.get("Content-Range"), f"bytes {start}-{end}/{len(self.original)}")
            self.assertEqual(response.headers.get("Content-Length"), str(end - start + 1))
            self.assertEqual(response.headers.get("X-Video-Library-Audio-Preference"), "ja")
            self.assertEqual(response.read(), self.expected[start:end + 1])

    def test_range_outside_tracks_is_byte_identical(self):
        start = len(self.original) - 8
        end = len(self.original) - 1
        request = Request(
            f"{self.base_url}/video/{self.video_id}",
            headers={"Range": f"bytes={start}-{end}"},
        )
        with urlopen(request) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), self.original[start:end + 1])


if __name__ == "__main__":
    unittest.main()
