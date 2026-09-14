from __future__ import annotations

import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from matroska_audio import (
    EBML_ID_CRC32,
    EBML_ID_FLAG_DEFAULT,
    EBML_ID_LANGUAGE,
    EBML_ID_NAME,
    EBML_ID_SEGMENT,
    EBML_ID_TRACKS,
    EBML_ID_TRACK_ENTRY,
    EBML_ID_TRACK_NUMBER,
    EBML_ID_TRACK_TYPE,
    TRACK_TYPE_AUDIO,
    _iter_elements,
    _parse_track,
    apply_patch_to_chunk,
    preferred_japanese_audio_patch,
)

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


def _uint_element(element_id: int, value: int) -> bytes:
    width = max(1, (value.bit_length() + 7) // 8)
    return _element(element_id, value.to_bytes(width, "big"))


def _track(number: int, track_type: int, language: str, *, default: int | None, name: str = "") -> bytes:
    payload = _uint_element(EBML_ID_TRACK_NUMBER, number)
    payload += _uint_element(EBML_ID_TRACK_TYPE, track_type)
    if default is not None:
        payload += _uint_element(EBML_ID_FLAG_DEFAULT, default)
    payload += _element(EBML_ID_LANGUAGE, language.encode("ascii"))
    if name:
        payload += _element(EBML_ID_NAME, name.encode("utf-8"))
    return _element(EBML_ID_TRACK_ENTRY, payload)


def _tracks_payload(*tracks: bytes, crc: bool = False) -> bytes:
    body = b"".join(tracks)
    if not crc:
        return body
    placeholder = _element(EBML_ID_CRC32, b"\x00\x00\x00\x00")
    checksum = zlib.crc32(body) & 0xFFFFFFFF
    return _element(EBML_ID_CRC32, checksum.to_bytes(4, "little")) + body


def _mkv(tracks_payload: bytes, *, segment_crc: bool = False) -> bytes:
    tracks = _element(EBML_ID_TRACKS, tracks_payload)
    segment_payload = tracks + _element(CLUSTER, b"")
    if segment_crc:
        crc = zlib.crc32(segment_payload) & 0xFFFFFFFF
        segment_payload = _element(EBML_ID_CRC32, crc.to_bytes(4, "little")) + segment_payload
    return _element(EBML_HEADER, b"") + _element(EBML_ID_SEGMENT, segment_payload)


def _audio_infos(payload: bytes):
    values = []
    for child in _iter_elements(payload):
        if child.element_id != EBML_ID_TRACK_ENTRY:
            continue
        info = _parse_track(payload, child)
        if info.track_type != TRACK_TYPE_AUDIO:
            continue
        default = None
        if info.flag_default_payload is not None:
            start, end = info.flag_default_payload
            default = int.from_bytes(payload[start:end], "big")
        values.append((info.language, info.name, default, info.track_number))
    return values


class JapaneseAudioDefaultV078Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, name: str, data: bytes) -> Path:
        path = self.base / name
        path.write_bytes(data)
        return path

    def test_dual_audio_reorders_japanese_and_flips_explicit_defaults(self):
        original = _mkv(
            _tracks_payload(
                _track(1, 1, "und", default=1, name="Video"),
                _track(2, 2, "eng", default=1, name="English 5.1 FLAC"),
                _track(3, 2, "jpn", default=0, name="Japanese 2.0 FLAC"),
            )
        )
        path = self._write("dual.mkv", original)
        patch = preferred_japanese_audio_patch(path)
        self.assertIsNotNone(patch)
        self.assertEqual(patch.audio_track_count, 2)
        self.assertEqual(
            _audio_infos(patch.data),
            [
                ("jpn", "Japanese 2.0 FLAC", 1, 3),
                ("eng", "English 5.1 FLAC", 0, 2),
            ],
        )
        self.assertEqual(path.read_bytes(), original, "physical MKV must never be modified")

    def test_missing_default_flag_still_moves_japanese_to_first_audio_slot(self):
        path = self._write(
            "implicit.mkv",
            _mkv(
                _tracks_payload(
                    _track(1, 1, "und", default=1),
                    _track(2, 2, "eng", default=None, name="English"),
                    _track(3, 2, "jpn", default=None, name="Japanese"),
                )
            ),
        )
        patch = preferred_japanese_audio_patch(path)
        self.assertIsNotNone(patch)
        self.assertEqual([x[0] for x in _audio_infos(patch.data)], ["jpn", "eng"])

    def test_japanese_name_is_used_when_language_tag_is_missing(self):
        path = self._write(
            "name-fallback.mkv",
            _mkv(
                _tracks_payload(
                    _track(1, 2, "eng", default=1, name="English"),
                    _track(2, 2, "und", default=0, name="Japanese 2.0 FLAC"),
                )
            ),
        )
        patch = preferred_japanese_audio_patch(path)
        self.assertIsNotNone(patch)
        self.assertEqual(_audio_infos(patch.data)[0][1], "Japanese 2.0 FLAC")
        self.assertEqual(_audio_infos(patch.data)[0][2], 1)

    def test_single_audio_and_no_japanese_are_unchanged(self):
        single = self._write(
            "single.mkv",
            _mkv(_tracks_payload(_track(1, 1, "und", default=1), _track(2, 2, "jpn", default=1))),
        )
        english_only = self._write(
            "english.mkv",
            _mkv(_tracks_payload(_track(1, 2, "eng", default=1), _track(2, 2, "fra", default=0))),
        )
        self.assertIsNone(preferred_japanese_audio_patch(single))
        self.assertIsNone(preferred_japanese_audio_patch(english_only))

    def test_non_matroska_is_unchanged(self):
        path = self._write("movie.mp4", b"not-an-mkv")
        self.assertIsNone(preferred_japanese_audio_patch(path))

    def test_tracks_crc_is_recomputed(self):
        path = self._write(
            "crc.mkv",
            _mkv(
                _tracks_payload(
                    _track(1, 2, "eng", default=1),
                    _track(2, 2, "jpn", default=0),
                    crc=True,
                )
            ),
        )
        patch = preferred_japanese_audio_patch(path)
        self.assertIsNotNone(patch)
        children = list(_iter_elements(patch.data))
        self.assertEqual(children[0].element_id, EBML_ID_CRC32)
        crc = children[0]
        stored = int.from_bytes(patch.data[crc.payload_start:crc.payload_end], "little")
        self.assertEqual(stored, zlib.crc32(patch.data[crc.end:]) & 0xFFFFFFFF)

    def test_segment_level_crc_fails_safe_to_original_stream(self):
        path = self._write(
            "segment-crc.mkv",
            _mkv(
                _tracks_payload(_track(1, 2, "eng", default=1), _track(2, 2, "jpn", default=0)),
                segment_crc=True,
            ),
        )
        self.assertIsNone(preferred_japanese_audio_patch(path))

    def test_partial_range_overlay_only_changes_overlap(self):
        original = _mkv(
            _tracks_payload(_track(1, 2, "eng", default=1), _track(2, 2, "jpn", default=0))
        )
        path = self._write("range.mkv", original)
        patch = preferred_japanese_audio_patch(path)
        self.assertIsNotNone(patch)

        expected = bytearray(original)
        expected[patch.offset:patch.offset + len(patch.data)] = patch.data
        start = max(0, patch.offset - 3)
        end = min(len(original), patch.offset + 17)
        changed = apply_patch_to_chunk(original[start:end], start, patch)
        self.assertEqual(changed, bytes(expected[start:end]))

        untouched = apply_patch_to_chunk(original[-4:], len(original) - 4, patch)
        self.assertEqual(untouched, original[-4:])


if __name__ == "__main__":
    unittest.main()
