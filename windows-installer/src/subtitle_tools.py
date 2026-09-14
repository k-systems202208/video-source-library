from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath

SUPPORTED_SUBTITLE_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa"}
UNSUPPORTED_SUBTITLE_EXTENSIONS = {".idx", ".sub", ".smi"}

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
_PREFIX_BOUNDARIES = {".", " ", "_", "-", "[", "(", "（"}
# The existing product intentionally refuses semantic alternate tracks such as
# movie.commentary.srt. Keep that guarantee even when a work has one video.
_NON_PRIMARY_TOKENS = {"commentary"}


@dataclass(frozen=True)
class SubtitleMatch:
    video_relative_path: str | None
    language: str | None
    is_forced: bool
    is_default: bool
    match_method: str


def _path(value: str) -> PurePosixPath:
    return PurePosixPath(value.replace("\\", "/"))


def _normalized_text(value: str) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).casefold().strip()


def _normalized_stem(value: str) -> str:
    return _normalized_text(_path(value).stem)


def _work_root(value: str) -> tuple[str, ...]:
    parts = _path(value).parts
    if len(parts) >= 2:
        return tuple(_normalized_text(part) for part in parts[:2])
    return tuple(_normalized_text(part) for part in parts[:-1])


def _suffix_tokens(value: str) -> list[str]:
    return [
        token.casefold()
        for token in re.split(r"[.\s_\-\[\]()（）]+", value)
        if token
    ]


def _metadata_from_suffix(suffix: str) -> tuple[str | None, bool, bool]:
    tokens = _suffix_tokens(suffix)
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


def _single(values: list[str]) -> str | None:
    unique = list(dict.fromkeys(values))
    return unique[0] if len(unique) == 1 else None


def _same_parent(subtitle: PurePosixPath, video_relative: str) -> bool:
    return _normalized_text(str(_path(video_relative).parent)) == _normalized_text(str(subtitle.parent))


def _work_videos(subtitle_relative_path: str, video_relative_paths: list[str]) -> list[str]:
    root = _work_root(subtitle_relative_path)
    return [video for video in video_relative_paths if _work_root(video) == root]


def _prefix_remainder(subtitle_stem: str, video_stem: str) -> str | None:
    if not video_stem or subtitle_stem == video_stem or not subtitle_stem.startswith(video_stem):
        return None
    if len(subtitle_stem) <= len(video_stem):
        return None
    if subtitle_stem[len(video_stem)] not in _PREFIX_BOUNDARIES:
        return None
    return subtitle_stem[len(video_stem) :]


def _is_non_primary_track(subtitle_stem: str, work_videos: list[str]) -> bool:
    for video in work_videos:
        remainder = _prefix_remainder(subtitle_stem, _normalized_stem(video))
        if remainder is not None and any(token in _NON_PRIMARY_TOKENS for token in _suffix_tokens(remainder)):
            return True
    return False


def _episode_key(value: str) -> tuple[int | None, int] | None:
    """Extract conservative season/episode identifiers from one library path.

    Strong filename forms are preferred over directory names so a misplaced
    subtitle file such as ``episode 1/...S04E13.srt`` still resolves to E13.
    Season may be ``None`` for single-season shows; the caller must still require
    a unique candidate inside the same work root.
    """
    normalized_path = unicodedata.normalize("NFKC", value.replace("\\", "/"))
    basename = _path(normalized_path).stem

    patterns = (
        r"(?i)s(?:eason)?[\s._-]*(\d{1,2})[\s._-]*e(?:p(?:isode)?)?[\s._-]*(\d{1,2})",
        r"(?i)(?<!\d)(\d{1,2})\s*x\s*(\d{1,2})(?!\d)",
        r"(?i)(?:^|[^a-z0-9])s(\d{1,2})[\s._-]+(\d{1,2})(?:[^0-9]|$)",
        r"(?i)(?:^|[^a-z0-9])ep(\d)(\d{2})(?:[^0-9]|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, basename)
        if match:
            return int(match.group(1)), int(match.group(2))

    season = None
    season_match = re.search(
        r"(?i)(?:^|[/ _.-])season[\s._-]*(\d{1,2})(?:[/ _.-]|$)",
        normalized_path,
    )
    if season_match:
        season = int(season_match.group(1))

    episode_patterns = (
        r"(?i)(?:^|[^a-z0-9])e(?:p(?:isode)?)?[\s._-]*(\d{1,2})(?:[^0-9]|$)",
        r"(?i)(?:^|[^a-z0-9])ep[\s._-]*(\d{1,2})(?:[^0-9]|$)",
        r"第\s*(\d{1,2})\s*話",
    )
    for pattern in episode_patterns:
        match = re.search(pattern, basename)
        if match:
            return season, int(match.group(1))

    # Use an explicit episode directory only when the filename itself had no
    # identifier. This is intentionally last because real subtitle packs can
    # contain a wrongly placed file.
    directory_episode = re.search(
        r"(?i)(?:^|[/ _.-])episode[\s._-]*(\d{1,2})(?:[/ _.-]|$)",
        normalized_path,
    )
    if directory_episode:
        return season, int(directory_episode.group(1))
    return None


def _metadata_for_match(subtitle_stem: str, suffix: str = "") -> tuple[str | None, bool, bool]:
    # Prefer an explicit suffix, but also inspect the subtitle stem so names like
    # ``jpn.srt`` in a one-video work still keep the language metadata.
    language, is_forced, is_default = _metadata_from_suffix(suffix)
    stem_language, stem_forced, stem_default = _metadata_from_suffix(subtitle_stem)
    language = language or stem_language
    is_forced = is_forced or stem_forced
    is_default = is_default or stem_default
    return language, is_forced, is_default


def match_subtitle_to_video(
    subtitle_relative_path: str,
    video_relative_paths: list[str],
) -> SubtitleMatch:
    subtitle = _path(subtitle_relative_path)
    subtitle_stem = _normalized_stem(subtitle_relative_path)

    # 1. Preserve the original strict behavior first: same folder + exact stem,
    # then the known language/default/forced suffix forms.
    strict_candidates: list[tuple[int, str, str, str]] = []
    for video_relative in video_relative_paths:
        if not _same_parent(subtitle, video_relative):
            continue
        video_stem = _normalized_stem(video_relative)
        if subtitle_stem == video_stem:
            strict_candidates.append((len(video_stem), video_relative, "EXACT_STEM", ""))
            continue
        prefix = video_stem + "."
        if subtitle_stem.startswith(prefix):
            remainder = subtitle_stem[len(prefix) :]
            tokens = [token for token in remainder.split(".") if token]
            if tokens and all(token in LANGUAGE_ALIASES or token in FLAG_TOKENS for token in tokens):
                strict_candidates.append((len(video_stem), video_relative, "LANGUAGE_SUFFIX", remainder))

    if strict_candidates:
        strict_candidates.sort(key=lambda item: (-item[0], item[1].casefold()))
        longest = strict_candidates[0][0]
        best = [item for item in strict_candidates if item[0] == longest]
        if len(best) != 1:
            return SubtitleMatch(None, None, False, False, "AMBIGUOUS")
        _, video_relative, method, suffix = best[0]
        language, is_forced, is_default = _metadata_for_match(subtitle_stem, suffix)
        return SubtitleMatch(video_relative, language, is_forced, is_default, method)

    work_videos = _work_videos(subtitle_relative_path, video_relative_paths)
    if not work_videos:
        return SubtitleMatch(None, None, False, False, "UNMATCHED")

    # Semantic alternate tracks remain manual even when another structural rule
    # below could otherwise identify a single video.
    if _is_non_primary_track(subtitle_stem, work_videos):
        return SubtitleMatch(None, None, False, False, "UNMATCHED")

    # 2. Subtitle packs are commonly stored under Subs/Subtitles/SubsExtracted.
    # Search only inside the same top-level work and require a unique exact stem.
    exact = _single([
        video for video in work_videos
        if _normalized_stem(video) == subtitle_stem
    ])
    if exact is not None:
        language, is_forced, is_default = _metadata_for_match(subtitle_stem)
        return SubtitleMatch(exact, language, is_forced, is_default, "WORK_EXACT_STEM")

    # 3. Allow a subtitle filename to add release/language text after the entire
    # video stem, but only at an explicit separator boundary and only if unique.
    prefix_candidates: list[tuple[str, str]] = []
    for video in work_videos:
        video_stem = _normalized_stem(video)
        remainder = _prefix_remainder(subtitle_stem, video_stem)
        if remainder is not None:
            prefix_candidates.append((video, remainder))
    prefix_video = _single([video for video, _ in prefix_candidates])
    if prefix_video is not None:
        suffix = next(remainder for video, remainder in prefix_candidates if video == prefix_video)
        language, is_forced, is_default = _metadata_for_match(subtitle_stem, suffix)
        return SubtitleMatch(prefix_video, language, is_forced, is_default, "WORK_STEM_PREFIX")

    # 4. A work containing exactly one registered video cannot be confused with
    # another episode inside that work. Multiple subtitles may safely target it.
    only_video = _single(work_videos)
    if only_video is not None:
        language, is_forced, is_default = _metadata_for_match(subtitle_stem)
        return SubtitleMatch(only_video, language, is_forced, is_default, "WORK_SINGLE_VIDEO")

    # 5. Finally normalize common season/episode forms. Season is optional for
    # single-season shows, but the resulting episode candidate must be unique in
    # the same work. A conflicting explicit season is never accepted.
    subtitle_episode = _episode_key(subtitle_relative_path)
    if subtitle_episode is not None:
        subtitle_season, subtitle_number = subtitle_episode
        episode_candidates: list[str] = []
        for video in work_videos:
            video_episode = _episode_key(video)
            if video_episode is None:
                continue
            video_season, video_number = video_episode
            if video_number != subtitle_number:
                continue
            if (
                subtitle_season is not None
                and video_season is not None
                and subtitle_season != video_season
            ):
                continue
            episode_candidates.append(video)
        episode_video = _single(episode_candidates)
        if episode_video is not None:
            language, is_forced, is_default = _metadata_for_match(subtitle_stem)
            return SubtitleMatch(episode_video, language, is_forced, is_default, "EPISODE_NUMBER")

    return SubtitleMatch(None, None, False, False, "UNMATCHED")
