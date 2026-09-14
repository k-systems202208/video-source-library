from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

SUPPORTED_SUBTITLE_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa"}

LANGUAGE_ALIASES = {
    "ja": "ja",
    "jp": "ja",
    "jpn": "ja",
    "japanese": "ja",
    "en": "en",
    "eng": "en",
    "english": "en",
}
FLAG_TOKENS = {"forced", "default", "sdh", "cc"}


@dataclass(frozen=True)
class SubtitleMatch:
    video_relative_path: str | None
    language: str | None
    is_forced: bool
    is_default: bool
    match_method: str


def _path(value: str) -> PurePosixPath:
    return PurePosixPath(value.replace("\\", "/"))


def _metadata_from_suffix(suffix: str) -> tuple[str | None, bool, bool]:
    tokens = [token.casefold() for token in suffix.split(".") if token]
    language = None
    is_forced = False
    is_default = False
    for token in tokens:
        if token in LANGUAGE_ALIASES:
            language = LANGUAGE_ALIASES[token]
        elif token == "forced":
            is_forced = True
        elif token == "default":
            is_default = True
    return language, is_forced, is_default


def match_subtitle_to_video(
    subtitle_relative_path: str,
    video_relative_paths: list[str],
) -> SubtitleMatch:
    subtitle = _path(subtitle_relative_path)
    subtitle_dir = str(subtitle.parent).casefold()
    subtitle_stem = subtitle.stem.casefold()

    candidates: list[tuple[int, str, str]] = []
    for video_relative in video_relative_paths:
        video = _path(video_relative)
        if str(video.parent).casefold() != subtitle_dir:
            continue
        video_stem = video.stem.casefold()
        if subtitle_stem == video_stem:
            candidates.append((len(video_stem), video_relative, "EXACT_STEM"))
            continue
        prefix = video_stem + "."
        if subtitle_stem.startswith(prefix):
            remainder = subtitle_stem[len(prefix) :]
            tokens = [token for token in remainder.split(".") if token]
            if tokens and all(token in LANGUAGE_ALIASES or token in FLAG_TOKENS for token in tokens):
                candidates.append((len(video_stem), video_relative, "LANGUAGE_SUFFIX"))

    if not candidates:
        return SubtitleMatch(None, None, False, False, "UNMATCHED")

    candidates.sort(key=lambda item: (-item[0], item[1].casefold()))
    longest = candidates[0][0]
    best = [item for item in candidates if item[0] == longest]
    if len(best) != 1:
        return SubtitleMatch(None, None, False, False, "AMBIGUOUS")

    _, video_relative, method = best[0]
    video_stem = _path(video_relative).stem.casefold()
    suffix = "" if subtitle_stem == video_stem else subtitle_stem[len(video_stem) + 1 :]
    language, is_forced, is_default = _metadata_from_suffix(suffix)
    return SubtitleMatch(video_relative, language, is_forced, is_default, method)
