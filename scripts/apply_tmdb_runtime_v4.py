from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, got {count}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    sync = ROOT / "windows-installer" / "src" / "tmdb_sync.py"
    replace_once(sync, "from database import connect, now_iso\n", "from app_version import APP_VERSION\nfrom database import connect, now_iso\n")
    replace_once(sync, '_MATCHER_VERSION = 3\n', '_MATCHER_VERSION = 4\n')
    replace_once(
        sync,
        '            row = {\n                "workId": int(work["id"]),\n',
        '            row = {\n                "appVersion": APP_VERSION,\n                "matcherVersion": _MATCHER_VERSION,\n                "workId": int(work["id"]),\n',
    )
    replace_once(
        sync,
        '    fields = [\n        "workId", "title", "category", "yearOrPeriod", "status", "confidence", "mediaType",\n',
        '    fields = [\n        "appVersion", "matcherVersion", "workId", "title", "category", "yearOrPeriod", "status", "confidence", "mediaType",\n',
    )
    replace_once(
        sync,
        '    summary = {\n        "total": len(rows),\n',
        '    summary = {\n        "appVersion": APP_VERSION,\n        "matcherVersion": _MATCHER_VERSION,\n        "total": len(rows),\n',
    )

    for rel in (
        "tests/test_tmdb_combined_media_v110.py",
        "tests/test_tmdb_matcher_v3_v110.py",
    ):
        path = ROOT / rel
        text = path.read_text(encoding="utf-8")
        updated = text.replace('\\"version\\":3', '\\"version\\":4')
        if updated == text:
            raise RuntimeError(f"{rel}: matcher marker assertion was not updated")
        path.write_text(updated, encoding="utf-8")

    readme = ROOT / "README.md"
    note = "\n### TMDb監査ランタイム識別（1.1.0）\n\nTMDb監査JSON/CSVには `appVersion` と `matcherVersion` を記録します。matcher更新時は内部version差分で既存MATCHEDを一度だけ再評価し、実機監査ファイルだけで実行ロジックを識別できます。\n"
    text = readme.read_text(encoding="utf-8")
    if "TMDb監査ランタイム識別（1.1.0）" not in text:
        readme.write_text(text.rstrip() + "\n" + note, encoding="utf-8")


if __name__ == "__main__":
    main()
