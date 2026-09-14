from __future__ import annotations

import os
from pathlib import Path

APP_ID = "VideoLibrary"


def data_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local).expanduser().resolve() / APP_ID
    return Path.home().resolve() / f".{APP_ID.casefold()}"


DATA_ROOT = data_root()
DATABASE_PATH = DATA_ROOT / "library.db"
CONFIG_PATH = DATA_ROOT / "config.json"
RUNTIME_PATH = DATA_ROOT / "runtime.json"
BACKUP_DIR = DATA_ROOT / "Backups"
LOG_DIR = DATA_ROOT / "Logs"
