from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paths import BACKUP_DIR, DATA_ROOT, DATABASE_PATH

RESTORE_REQUEST_FILENAME = "restore-request.json"
RESTORE_STATUS_FILENAME = "restore-status.json"
BACKUP_NAME_PATTERN = re.compile(r"^library-[A-Za-z0-9._-]+\.db$")
SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2, 3, 4})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _schema_version(connection: sqlite3.Connection) -> int:
    if not _table_exists(connection, "schema_info"):
        return 0
    row = connection.execute("SELECT schema_version FROM schema_info ORDER BY rowid LIMIT 1").fetchone()
    try:
        return int(row[0]) if row else 0
    except (TypeError, ValueError):
        return 0


def _count_rows(connection: sqlite3.Connection, table: str) -> int:
    if not _table_exists(connection, table):
        return 0
    return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def inspect_database(path: Path) -> dict[str, Any]:
    target = Path(path)
    result = {"exists": target.is_file(), "valid": False, "quickCheck": "missing", "schemaVersion": 0,
              "workCount": 0, "videoCount": 0, "userCount": 0, "error": ""}
    if not target.is_file() or target.stat().st_size <= 0:
        result["error"] = "ファイルが存在しないか、空です。"
        return result
    connection = None
    try:
        connection = sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True, timeout=15.0)
        quick = connection.execute("PRAGMA quick_check").fetchone()
        quick_text = str(quick[0] if quick else "unknown")
        schema = _schema_version(connection)
        result.update({
            "quickCheck": quick_text,
            "schemaVersion": schema,
            "workCount": _count_rows(connection, "works"),
            "videoCount": _count_rows(connection, "videos"),
            "userCount": _count_rows(connection, "users"),
            "valid": quick_text.casefold() == "ok" and schema in SUPPORTED_SCHEMA_VERSIONS,
        })
        if quick_text.casefold() != "ok":
            result["error"] = f"SQLite整合性検査: {quick_text}"
        elif schema not in SUPPORTED_SCHEMA_VERSIONS:
            result["error"] = f"対応外のDBスキーマです: {schema}"
    except sqlite3.Error as exc:
        result["quickCheck"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if connection is not None:
            connection.close()
    return result


def _safe_backup_path(name: str, backup_dir: Path = BACKUP_DIR) -> Path:
    text = str(name or "").strip()
    if not BACKUP_NAME_PATTERN.fullmatch(text):
        raise ValueError("バックアップ名が不正です。")
    root = Path(backup_dir).resolve()
    candidate = (root / text).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("バックアップ保存先の外は指定できません。") from exc
    return candidate


def _backup_item(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "sizeBytes": int(stat.st_size),
        "modifiedAt": datetime.fromtimestamp(stat.st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        **inspect_database(path),
    }


def list_backups(backup_dir: Path = BACKUP_DIR) -> list[dict[str, Any]]:
    root = Path(backup_dir)
    root.mkdir(parents=True, exist_ok=True)
    paths = [p for p in root.glob("library-*.db") if p.is_file()]
    paths.sort(key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
    return [_backup_item(p) for p in paths]


def _sqlite_backup(source_path: Path, destination_path: Path) -> None:
    source = sqlite3.connect(source_path, timeout=30.0)
    target = sqlite3.connect(destination_path, timeout=30.0)
    try:
        source.backup(target)
    finally:
        target.close(); source.close()


def create_manual_backup(*, database_path: Path = DATABASE_PATH, backup_dir: Path = BACKUP_DIR) -> dict[str, Any]:
    source = Path(database_path)
    if not source.is_file():
        raise FileNotFoundError("library.db が見つかりません。")
    root = Path(backup_dir); root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = root / f"library-manual-{stamp}.db"
    sequence = 1
    while destination.exists():
        destination = root / f"library-manual-{stamp}-{sequence:02d}.db"; sequence += 1
    _sqlite_backup(source, destination)
    item = _backup_item(destination)
    if not item["valid"]:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"作成したバックアップの検証に失敗しました: {item['error']}")
    return item


def pending_restore(data_root: Path = DATA_ROOT) -> dict[str, Any] | None:
    value = _read_json(Path(data_root) / RESTORE_REQUEST_FILENAME)
    return value or None


def restore_status(data_root: Path = DATA_ROOT) -> dict[str, Any] | None:
    value = _read_json(Path(data_root) / RESTORE_STATUS_FILENAME)
    return value or None


def schedule_restore(backup_name: str, *, data_root: Path = DATA_ROOT, backup_dir: Path = BACKUP_DIR) -> dict[str, Any]:
    path = _safe_backup_path(backup_name, backup_dir)
    if not path.is_file():
        raise FileNotFoundError("選択したバックアップが見つかりません。")
    inspection = inspect_database(path)
    if not inspection["valid"]:
        raise ValueError(f"復元できないバックアップです: {inspection['error']}")
    request = {"formatVersion": 1, "backupName": path.name, "requestedAt": _utc_now_iso(), "schemaVersion": inspection["schemaVersion"]}
    _atomic_write_json(Path(data_root) / RESTORE_REQUEST_FILENAME, request)
    return request


def cancel_restore(data_root: Path = DATA_ROOT) -> bool:
    try:
        (Path(data_root) / RESTORE_REQUEST_FILENAME).unlink(); return True
    except FileNotFoundError:
        return False


def apply_pending_restore(data_root: Path = DATA_ROOT) -> dict[str, Any] | None:
    root = Path(data_root).resolve()
    request_path = root / RESTORE_REQUEST_FILENAME
    request = _read_json(request_path)
    if not request:
        return None
    backup_dir = root / "Backups"; database_path = root / "library.db"; status_path = root / RESTORE_STATUS_FILENAME
    started = _utc_now_iso(); backup_name = str(request.get("backupName") or "")
    pre_restore: Path | None = None
    try:
        selected = _safe_backup_path(backup_name, backup_dir)
        inspection = inspect_database(selected)
        if not selected.is_file() or not inspection["valid"]:
            raise ValueError("復元対象のバックアップが無効です。")
        backup_dir.mkdir(parents=True, exist_ok=True)
        if database_path.is_file():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            pre_restore = backup_dir / f"library-pre-restore-{stamp}.db"
            _sqlite_backup(database_path, pre_restore)
            if not inspect_database(pre_restore)["valid"]:
                raise RuntimeError("復元前バックアップの検証に失敗しました。")
        temp = root / "library.restore.tmp.db"
        temp.unlink(missing_ok=True)
        _sqlite_backup(selected, temp)
        if not inspect_database(temp)["valid"]:
            raise RuntimeError("復元用DBの検証に失敗しました。")
        for suffix in ("-wal", "-shm"):
            Path(str(database_path) + suffix).unlink(missing_ok=True)
        os.replace(temp, database_path)
        restored = inspect_database(database_path)
        if not restored["valid"]:
            raise RuntimeError("復元後DBの検証に失敗しました。")
        status = {"state": "restored", "backupName": selected.name,
                  "preRestoreBackupName": pre_restore.name if pre_restore else "",
                  "startedAt": started, "finishedAt": _utc_now_iso(),
                  "schemaVersion": restored["schemaVersion"], "workCount": restored["workCount"], "videoCount": restored["videoCount"]}
        _atomic_write_json(status_path, status); request_path.unlink(missing_ok=True); return status
    except Exception as exc:
        rolled_back = False
        if pre_restore and pre_restore.is_file():
            try:
                rollback = root / "library.rollback.tmp.db"; rollback.unlink(missing_ok=True)
                _sqlite_backup(pre_restore, rollback)
                if inspect_database(rollback)["valid"]:
                    os.replace(rollback, database_path); rolled_back = True
            except Exception:
                pass
        status = {"state": "error", "backupName": backup_name, "startedAt": started, "finishedAt": _utc_now_iso(),
                  "error": f"{type(exc).__name__}: {exc}", "rolledBack": rolled_back}
        _atomic_write_json(status_path, status); request_path.unlink(missing_ok=True); return status
