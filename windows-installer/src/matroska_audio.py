from __future__ import annotations

import functools
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator

# EBML / Matroska element IDs used by the conservative header-only patcher.
EBML_ID_SEGMENT = 0x18538067
EBML_ID_TRACKS = 0x1654AE6B
EBML_ID_TRACK_ENTRY = 0xAE
EBML_ID_TRACK_NUMBER = 0xD7
EBML_ID_TRACK_TYPE = 0x83
EBML_ID_FLAG_DEFAULT = 0x88
EBML_ID_LANGUAGE = 0x22B59C
EBML_ID_LANGUAGE_IETF = 0x22B59D
EBML_ID_NAME = 0x536E
EBML_ID_CRC32 = 0xBF

TRACK_TYPE_AUDIO = 2
MAX_HEADER_SCAN = 64 * 1024 * 1024
MAX_TRACKS_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class ElementSlice:
    element_id: int
    start: int
    payload_start: int
    payload_end: int
    end: int


@dataclass(frozen=True)
class TrackInfo:
    element: ElementSlice
    track_type: int | None
    track_number: int | None
    language: str
    name: str
    flag_default_payload: tuple[int, int] | None


@dataclass(frozen=True)
class MatroskaAudioPatch:
    """Same-length replacement for the Matroska Tracks payload."""

    offset: int
    data: bytes
    audio_track_count: int
    preferred_language: str = "ja"


def _vint_length(first: int, *, max_length: int) -> int:
    if first <= 0:
        raise ValueError("invalid EBML VINT")
    mask = 0x80
    for length in range(1, max_length + 1):
        if first & mask:
            return length
        mask >>= 1
    raise ValueError("EBML VINT is too long")


def _decode_size(raw: bytes) -> int | None:
    if not raw:
        raise ValueError("missing EBML size")
    length = len(raw)
    marker = 1 << (8 - length)
    value = raw[0] & (marker - 1)
    for byte in raw[1:]:
        value = (value << 8) | byte
    if value == (1 << (7 * length)) - 1:
        return None
    return value


def _parse_element(data: bytes, offset: int, limit: int | None = None) -> ElementSlice:
    end_limit = len(data) if limit is None else min(limit, len(data))
    if offset < 0 or offset >= end_limit:
        raise ValueError("element offset outside buffer")

    id_length = _vint_length(data[offset], max_length=4)
    id_end = offset + id_length
    if id_end >= end_limit:
        raise ValueError("truncated EBML element ID")
    element_id = int.from_bytes(data[offset:id_end], "big")

    size_length = _vint_length(data[id_end], max_length=8)
    size_end = id_end + size_length
    if size_end > end_limit:
        raise ValueError("truncated EBML element size")
    size = _decode_size(data[id_end:size_end])
    if size is None:
        raise ValueError("unknown-sized child element is not safe to rewrite")

    payload_end = size_end + size
    if payload_end > end_limit:
        raise ValueError("truncated EBML element payload")
    return ElementSlice(element_id, offset, size_end, payload_end, payload_end)


def _iter_elements(data: bytes, start: int = 0, end: int | None = None) -> Iterator[ElementSlice]:
    limit = len(data) if end is None else min(end, len(data))
    position = start
    while position < limit:
        element = _parse_element(data, position, limit)
        yield element
        if element.end <= position:
            raise ValueError("invalid zero-progress EBML element")
        position = element.end
    if position != limit:
        raise ValueError("EBML children do not exactly fill parent payload")


def _read_header_at(handle: BinaryIO, offset: int) -> tuple[int, int | None, int]:
    handle.seek(offset)
    first_raw = handle.read(1)
    if not first_raw:
        raise ValueError("missing EBML element")
    first = first_raw[0]
    id_length = _vint_length(first, max_length=4)
    id_raw = first_raw + handle.read(id_length - 1)
    if len(id_raw) != id_length:
        raise ValueError("truncated EBML element ID")

    size_first_raw = handle.read(1)
    if not size_first_raw:
        raise ValueError("truncated EBML element size")
    size_length = _vint_length(size_first_raw[0], max_length=8)
    size_raw = size_first_raw + handle.read(size_length - 1)
    if len(size_raw) != size_length:
        raise ValueError("truncated EBML element size")

    return int.from_bytes(id_raw, "big"), _decode_size(size_raw), id_length + size_length


def _uint(data: bytes) -> int | None:
    if not data:
        return 0
    if len(data) > 8:
        return None
    return int.from_bytes(data, "big")


def _text(data: bytes) -> str:
    return data.rstrip(b"\x00").decode("utf-8", errors="replace").strip()


def _parse_track(payload: bytes, entry: ElementSlice) -> TrackInfo:
    track_type: int | None = None
    track_number: int | None = None
    language = "eng"  # Matroska default when Language is omitted.
    language_ietf = ""
    name = ""
    flag_default: tuple[int, int] | None = None

    for child in _iter_elements(payload, entry.payload_start, entry.payload_end):
        value = payload[child.payload_start:child.payload_end]
        if child.element_id == EBML_ID_TRACK_TYPE:
            track_type = _uint(value)
        elif child.element_id == EBML_ID_TRACK_NUMBER:
            track_number = _uint(value)
        elif child.element_id == EBML_ID_LANGUAGE:
            language = _text(value) or language
        elif child.element_id == EBML_ID_LANGUAGE_IETF:
            language_ietf = _text(value)
        elif child.element_id == EBML_ID_NAME:
            name = _text(value)
        elif child.element_id == EBML_ID_FLAG_DEFAULT:
            flag_default = (child.payload_start, child.payload_end)

    return TrackInfo(
        element=entry,
        track_type=track_type,
        track_number=track_number,
        language=language_ietf or language,
        name=name,
        flag_default_payload=flag_default,
    )


def _is_japanese(track: TrackInfo) -> bool:
    language = track.language.casefold().replace("_", "-").strip()
    if language in {"ja", "jpn", "jp", "japanese"} or language.startswith(("ja-", "jpn-")):
        return True
    name = track.name.casefold()
    return "japanese" in name or "日本語" in track.name


def _recompute_crc32(parent_payload: bytearray) -> None:
    """Refresh an optional first-child EBML CRC-32 after an in-memory rewrite."""
    try:
        children = list(_iter_elements(bytes(parent_payload)))
    except ValueError:
        return
    if not children or children[0].element_id != EBML_ID_CRC32:
        return
    crc = children[0]
    if crc.payload_end - crc.payload_start != 4:
        return
    # RFC 8794: CRC covers parent element data except the CRC element itself
    # and is stored little-endian.
    checksum = zlib.crc32(parent_payload[crc.end:]) & 0xFFFFFFFF
    parent_payload[crc.payload_start:crc.payload_end] = checksum.to_bytes(4, "little")


def _set_track_default(raw_entry: bytes, desired: bool) -> bytes:
    try:
        entry = _parse_element(raw_entry, 0)
        if entry.element_id != EBML_ID_TRACK_ENTRY or entry.end != len(raw_entry):
            return raw_entry
        info = _parse_track(raw_entry, entry)
    except ValueError:
        return raw_entry
    if info.flag_default_payload is None:
        return raw_entry
    start, end = info.flag_default_payload
    width = end - start
    if width <= 0:
        return raw_entry
    value = 1 if desired else 0
    if value >= (1 << (8 * width)):
        return raw_entry
    changed = bytearray(raw_entry)
    changed[start:end] = value.to_bytes(width, "big")

    # TrackEntry can itself contain a CRC-32 as its first child.
    payload = bytearray(changed[entry.payload_start:entry.payload_end])
    _recompute_crc32(payload)
    changed[entry.payload_start:entry.payload_end] = payload
    return bytes(changed)


def _rewrite_tracks_payload(payload: bytes) -> tuple[bytes, int] | None:
    """Prefer Japanese among multiple audio TrackEntry children without changing size."""
    try:
        children = list(_iter_elements(payload))
    except ValueError:
        return None

    parsed: dict[int, TrackInfo] = {}
    audio_children: list[tuple[int, TrackInfo, bytes]] = []
    for index, child in enumerate(children):
        if child.element_id != EBML_ID_TRACK_ENTRY:
            continue
        try:
            info = _parse_track(payload, child)
        except ValueError:
            return None
        parsed[index] = info
        if info.track_type == TRACK_TYPE_AUDIO:
            audio_children.append((index, info, payload[child.start:child.end]))

    if len(audio_children) < 2:
        return None
    japanese = [item for item in audio_children if _is_japanese(item[1])]
    if not japanese:
        return None

    # Make every explicit FlagDefault deterministic. Missing FlagDefault means
    # Matroska's implicit default=true; ordering Japanese first is the fallback.
    preferred_ids = {id(item[1]) for item in japanese}
    rewritten_audio: list[tuple[int, TrackInfo, bytes]] = []
    for index, info, raw in audio_children:
        rewritten_audio.append((index, info, _set_track_default(raw, id(info) in preferred_ids)))

    ordered_audio = [item for item in rewritten_audio if _is_japanese(item[1])] + [
        item for item in rewritten_audio if not _is_japanese(item[1])
    ]
    ordered_raw = iter(item[2] for item in ordered_audio)

    rebuilt = bytearray()
    for index, child in enumerate(children):
        if index in parsed and parsed[index].track_type == TRACK_TYPE_AUDIO:
            rebuilt.extend(next(ordered_raw))
        else:
            rebuilt.extend(payload[child.start:child.end])

    if len(rebuilt) != len(payload):
        return None
    _recompute_crc32(rebuilt)
    if bytes(rebuilt) == payload:
        return None
    return bytes(rebuilt), len(audio_children)


def _find_tracks_payload(path: Path) -> tuple[int, bytes] | None:
    file_size = path.stat().st_size
    with path.open("rb") as handle:
        # Find the Segment root after the EBML header.
        position = 0
        segment_start: int | None = None
        segment_size: int | None = None
        while position < min(file_size, 1024 * 1024):
            element_id, size, header_size = _read_header_at(handle, position)
            payload_start = position + header_size
            if element_id == EBML_ID_SEGMENT:
                segment_start = payload_start
                segment_size = size
                break
            if size is None:
                return None
            position = payload_start + size
        if segment_start is None:
            return None

        segment_end = file_size if segment_size is None else min(file_size, segment_start + segment_size)
        scan_end = min(segment_end, segment_start + MAX_HEADER_SCAN)
        position = segment_start
        segment_crc_seen = False
        first_child = True
        while position < scan_end:
            element_id, size, header_size = _read_header_at(handle, position)
            payload_start = position + header_size
            if first_child and element_id == EBML_ID_CRC32:
                # Changing Tracks would invalidate a Segment-level CRC; fail safe.
                segment_crc_seen = True
            first_child = False
            if element_id == EBML_ID_TRACKS:
                if segment_crc_seen or size is None or size > MAX_TRACKS_BYTES:
                    return None
                payload_end = payload_start + size
                if payload_end > file_size:
                    return None
                handle.seek(payload_start)
                payload = handle.read(size)
                if len(payload) != size:
                    return None
                return payload_start, payload
            if size is None:
                return None
            next_position = payload_start + size
            if next_position <= position:
                return None
            position = next_position
    return None


@functools.lru_cache(maxsize=512)
def _cached_patch(path_text: str, file_size: int, modified_time_ns: int) -> MatroskaAudioPatch | None:
    del file_size, modified_time_ns  # only used as cache-key invalidators
    path = Path(path_text)
    try:
        found = _find_tracks_payload(path)
        if found is None:
            return None
        offset, payload = found
        rewritten = _rewrite_tracks_payload(payload)
        if rewritten is None:
            return None
        data, count = rewritten
        return MatroskaAudioPatch(offset=offset, data=data, audio_track_count=count)
    except (OSError, ValueError, OverflowError):
        return None


def preferred_japanese_audio_patch(path: Path | str) -> MatroskaAudioPatch | None:
    """Return an in-memory same-size Tracks patch for an MKV/WebM file.

    The physical media is never modified. Unsupported or unusual EBML layouts
    deliberately fall back to the original byte stream.
    """
    source = Path(path)
    if source.suffix.casefold() not in {".mkv", ".webm"}:
        return None
    try:
        stat = source.stat()
        resolved = source.resolve()
    except OSError:
        return None
    return _cached_patch(str(resolved), int(stat.st_size), int(stat.st_mtime_ns))


def apply_patch_to_chunk(chunk: bytes, chunk_start: int, patch: MatroskaAudioPatch | None) -> bytes:
    if patch is None or not chunk:
        return chunk
    chunk_end = chunk_start + len(chunk)
    patch_start = patch.offset
    patch_end = patch.offset + len(patch.data)
    start = max(chunk_start, patch_start)
    end = min(chunk_end, patch_end)
    if start >= end:
        return chunk
    changed = bytearray(chunk)
    changed[start - chunk_start:end - chunk_start] = patch.data[start - patch_start:end - patch_start]
    return bytes(changed)
