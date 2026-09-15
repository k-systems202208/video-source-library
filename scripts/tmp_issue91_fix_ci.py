from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"marker not found: {path}: {old!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "tests/test_phase3.py",
    "initialize_database(c); self.assertEqual(c.execute('SELECT schema_version FROM schema_info').fetchone()[0],4); self.assertEqual(SCHEMA_VERSION,4);",
    "initialize_database(c); self.assertEqual(c.execute('SELECT schema_version FROM schema_info').fetchone()[0],5); self.assertEqual(SCHEMA_VERSION,5);",
)
replace_once(
    "tests/test_phase4.py",
    "self.assertEqual(SCHEMA_VERSION,4)",
    "self.assertEqual(SCHEMA_VERSION,5)",
)
replace_once(
    "windows-installer/src/backup_restore.py",
    "from paths import BACKUP_DIR, DATA_ROOT, DATABASE_PATH\n",
    "from database import SCHEMA_VERSION\nfrom paths import BACKUP_DIR, DATA_ROOT, DATABASE_PATH\n",
)
replace_once(
    "windows-installer/src/backup_restore.py",
    "SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2, 3, 4})",
    "SUPPORTED_SCHEMA_VERSIONS = frozenset(range(1, SCHEMA_VERSION + 1))",
)
