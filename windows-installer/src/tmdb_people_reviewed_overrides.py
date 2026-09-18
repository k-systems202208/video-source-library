from __future__ import annotations

# Human-reviewed work/person mappings from the real-library people audit.
#
# Safety rule:
# A mapping is used only when media_type, TMDb work id, and local person name
# all match exactly.  The TMDb person details endpoint must also return the
# same person id before the mapping is accepted.
REVIEWED_WORK_PERSON_OVERRIDES: dict[tuple[str, int, str], int] = {
    ("tv", 38041, "石坂浩二"): 107961,       # 東京湾景
    ("tv", 41756, "DAIGO"): 1111225,         # ラブシャッフル
    ("tv", 46107, "大泉洋"): 40450,           # 99年の愛〜JAPANESE AMERICANS〜
    ("tv", 83850, "春川恭亮"): 2661404,       # 青空の卵
    ("tv", 70214, "TAKAHIRO"): 1448214,       # HiGH&LOW〜THE STORY OF S.W.O.R.D.〜
    ("tv", 63440, "郭智博"): 20345,           # アカギ
    ("tv", 109233, "EXILE NAOTO"): 2201144,  # ブスの瞳に恋してる2019
}

# Existing work links that were found to point to a different production.
# These are repaired during the one-time people sync so users do not need to
# run the full TMDb work sync manually after an update.
REVIEWED_BAD_WORK_MATCHES: tuple[tuple[str, str, str, int], ...] = (
    ("半分の月がのぼる空", "2006", "tv", 34746),
)


# Local library entries intentionally representing multiple installments.
# A single TMDb movie/TV id must never be promoted to MATCHED for these rows.
REVIEWED_AGGREGATE_WORKS: set[tuple[str, str]] = {
    ("男はつらいよ", "1969-2019"),
    ("仁義なき戦い", "1973-1974"),
    ("福岡恋愛白書", "2011-2016"),
    ("殺人分析班シリーズ", "2016-2019"),
}

# Local/TMDb structures known not to have a safe one-to-one work mapping.
REVIEWED_SPECIAL_UNMATCHED_WORKS: set[tuple[str, str]] = {
    ("3年B組金八先生 第6シリーズ", "2001"),
    ("半分の月がのぼる空", "2006"),
}

# Cast members verified in primary/official material, but for whom the current
# TMDb work credits + person search do not provide a safely identifiable person
# id. These entries are diagnostic only and NEVER create a person link.
REVIEWED_MISSING_TMDB_PEOPLE: set[tuple[str, int, str]] = {
    ("tv", 89351, "渡辺千秋"),  # スケバン刑事 (1985)
}
