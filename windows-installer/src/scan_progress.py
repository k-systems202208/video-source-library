from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class ScanProgressStore:
    """Thread-safe in-memory progress for one active library scan.

    Detailed progress is intentionally runtime-only. Durable scan results remain
    in scan_runs, while this store exists only to make a long-running scan
    observable by the browser without writing SQLite for every file.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started_perf: float | None = None
        self._state = self._empty_state()

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "running": False,
            "phase": "IDLE",
            "message": "",
            "startedAt": None,
            "completedAt": None,
            "current": 0,
            "total": 0,
            "filesFound": 0,
            "filesMatched": 0,
            "filesMissing": 0,
            "filesNew": 0,
            "filesProbed": 0,
            "subtitlesFound": 0,
            "subtitlesProcessed": 0,
            "subtitlesMatched": 0,
            "subtitlesUnmatched": 0,
            "probeErrors": 0,
            "errors": 0,
            "currentItem": None,
            "error": None,
        }

    def start(self) -> None:
        with self._lock:
            self._started_perf = time.monotonic()
            self._state = self._empty_state()
            self._state.update(
                running=True,
                phase="PREPARING",
                message="初期化中（DB・動画フォルダーを確認しています）",
                startedAt=_now_iso(),
            )

    def update(self, values: dict[str, Any]) -> None:
        with self._lock:
            if not self._state["running"]:
                return
            for key, value in values.items():
                if key in self._state and key not in {"running", "startedAt", "completedAt", "error"}:
                    self._state[key] = value

    def complete(self, result: dict[str, Any]) -> None:
        with self._lock:
            for key in (
                "filesFound", "filesMatched", "filesMissing", "filesNew", "filesProbed",
                "subtitlesFound", "subtitlesMatched", "subtitlesUnmatched", "probeErrors", "errors",
            ):
                if key in result:
                    self._state[key] = result[key]
            self._state.update(
                running=False,
                phase="SUCCESS",
                message="再スキャンが完了しました",
                completedAt=_now_iso(),
                currentItem=None,
                error=None,
            )

    def fail(self, message: str) -> None:
        with self._lock:
            self._state.update(
                running=False,
                phase="FAILED",
                message="再スキャンに失敗しました",
                completedAt=_now_iso(),
                currentItem=None,
                error=message[:1000],
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            value = dict(self._state)
            started_perf = self._started_perf
        elapsed_ms = 0
        if started_perf is not None:
            elapsed_ms = max(0, int((time.monotonic() - started_perf) * 1000))
        current = int(value.get("current") or 0)
        total = int(value.get("total") or 0)
        percent = min(100, max(0, round(current * 100 / total))) if total > 0 else 0
        eta_ms = None
        if value["running"] and current > 0 and total > current and elapsed_ms > 0:
            eta_ms = int(elapsed_ms * (total - current) / current)
        if value["running"] and value.get("phase") == "PREPARING" and elapsed_ms >= 5000:
            value["message"] = "初期化中（ネットワークドライブまたはDBの応答を待っています）"
        value["elapsedMs"] = elapsed_ms
        value["percent"] = percent
        value["etaMs"] = eta_ms
        return value
