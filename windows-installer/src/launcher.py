from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import threading
import time
import tkinter as tk
import urllib.parse
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from app_config import configured_tmdb_token, load_config, save_config, save_tmdb_token, tmdb_token_source
from app_version import APP_VERSION
from backup_restore import apply_pending_restore, create_manual_backup
from database import connect, initialize_database, now_iso
from local_auth import create_bootstrap_token
from media_probe import find_ffprobe
from metadata_importer import import_file
from playback_audit import audit_real_library
from playback_cache import DEFAULT_CACHE_LIMIT_BYTES, clear_playback_cache, format_bytes, playback_cache_stats
from paths import CONFIG_PATH, DATABASE_PATH, DATA_ROOT, RUNTIME_PATH
from remote_access import disable_remote_access, enable_remote_access, get_remote_status
from scan_runner import scan_library
from server import create_server
from tmdb_sync import sync_tmdb_library

APP_NAME = "シネマ蔵書館"
# Music Library uses 8765. Keep Video Library on a different localhost origin
# so Service Worker, Cache Storage and PWA state cannot collide.
DEFAULT_PORT = 8876
METADATA_PATH = DATA_ROOT / "metadata" / "video_library.json"
PLAYBACK_CACHE_PATH = DATA_ROOT / "PlaybackCache"
PLAYBACK_AUDIT_OUTPUT_PATH = DATA_ROOT / "diagnostics"
TMDB_IMAGE_PATH = DATA_ROOT / "TMDbImages"
TMDB_REPORT_OUTPUT_PATH = DATA_ROOT / "diagnostics"

# Keep the Windows launcher visually aligned with mp3-source-music-library.
UI_FONT = "Yu Gothic UI"
WINDOW_GEOMETRY = "780x690"
WINDOW_MINSIZE = (700, 590)
TITLE_FONT = (UI_FONT, 20, "bold")
BODY_FONT = (UI_FONT, 10)
SMALL_FONT = (UI_FONT, 9)
STATUS_FONT = (UI_FONT, 10, "bold")
MONO_FONT = ("Consolas", 9)
MAIN_PADDING = 18


def atomic_write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def request_local_owner_browser_url(page_url: str, control_secret: str) -> str:
    parsed = urllib.parse.urlsplit(page_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("owner authentication endpoint must be localhost HTTP")

    token = create_bootstrap_token(control_secret, ttl_seconds=60)
    bootstrap = urllib.parse.urljoin(page_url, "/offline.html") + "?owner-bootstrap=1"
    return bootstrap + "#token=" + urllib.parse.quote(token, safe="")


def database_counts() -> tuple[int, int]:
    if not DATABASE_PATH.is_file():
        return 0, 0
    with connect(DATABASE_PATH) as connection:
        initialize_database(connection)
        works = int(connection.execute("SELECT COUNT(*) FROM works").fetchone()[0])
        videos = int(connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0])
    return works, videos


def recover_interrupted_scans(database_path: Path = DATABASE_PATH) -> int:
    """Mark scans left RUNNING by a previous process as interrupted."""
    if not database_path.is_file():
        return 0
    with connect(database_path) as connection:
        initialize_database(connection)
        stamp = now_iso()
        cursor = connection.execute(
            """
            UPDATE scan_runs
            SET status='INTERRUPTED',
                completed_at=COALESCE(completed_at, ?)
            WHERE status='RUNNING'
            """,
            (stamp,),
        )
        connection.commit()
        return max(0, int(cursor.rowcount or 0))


def run_startup_scan(
    database_path: Path,
    video_root: Path,
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run the same scan used by the browser before starting the HTTP server."""
    with connect(database_path) as connection:
        return scan_library(connection, video_root, progress_callback=progress_callback)


def _phase_text(value: str | None) -> str:
    return {
        "PREPARING": "準備中",
        "SCANNING": "動画を走査中",
        "PROBING": "ffprobe解析中",
        "SUBTITLES": "字幕を照合中",
        "FINALIZING": "結果を保存中",
        "SUCCESS": "完了",
        "FAILED": "失敗",
    }.get(str(value or ""), str(value or "処理中"))


class VideoLibraryLauncher(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry(WINDOW_GEOMETRY)
        self.minsize(*WINDOW_MINSIZE)

        style = ttk.Style(self)
        style.configure(".", font=BODY_FONT)

        self.server = None
        self.server_thread: threading.Thread | None = None
        self.scan_thread: threading.Thread | None = None
        self.audit_thread: threading.Thread | None = None
        self.tmdb_thread: threading.Thread | None = None
        self.audit_started_monotonic: float | None = None
        self.scan_started_monotonic: float | None = None
        self.control_secret = ""
        self._last_phase = ""
        self._last_logged_current = -1
        self._indeterminate = False

        config = load_config(CONFIG_PATH)
        default_metadata = str(METADATA_PATH) if METADATA_PATH.is_file() else ""
        self.video_root = tk.StringVar(value=str(config.get("videoRoot") or "未設定"))
        self.metadata_path = tk.StringVar(value=str(config.get("metadataPath") or default_metadata or "未設定"))
        self.status = tk.StringVar(value="準備完了")
        self.metadata_status = tk.StringVar(value="メタデータ未確認")
        self.probe_status = tk.StringVar(value="ffprobe未確認")
        self.remote = tk.StringVar(value="状態を確認しています…")
        self.cache_status = tk.StringVar(value="再生キャッシュ: 確認中…")
        self.remote_url = ""
        self.scan_status = tk.StringVar(value="起動スキャン待機中")
        self.scan_counts = tk.StringVar(value="MATCHED 0 / MISSING 0 / NEW_FILE 0 / 字幕 0 / ffprobe 0")
        self.scan_current = tk.StringVar(value="現在処理中: —")
        self.scan_elapsed = tk.StringVar(value="経過: —")

        self._build()
        self.after(200, self.refresh_local_status)
        self.after(300, self.refresh_remote)
        self.after(800, self._auto_start_if_ready)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _build(self) -> None:
        main = ttk.Frame(self, padding=MAIN_PADDING)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text=APP_NAME, font=TITLE_FONT).pack(anchor="w")
        ttk.Label(
            main,
            text="動画フォルダーを選ぶだけで、スキャン後にブラウザから検索・再生できます。",
            font=BODY_FONT,
        ).pack(anchor="w", pady=(2, 14))

        folder_frame = ttk.LabelFrame(main, text="動画フォルダー", padding=10)
        folder_frame.pack(fill="x")
        self.root_label = ttk.Label(
            folder_frame,
            textvariable=self.video_root,
            wraplength=610,
            font=SMALL_FONT,
        )
        self.root_label.pack(side="left", fill="x", expand=True)
        self.root_button = ttk.Button(folder_frame, text="変更", command=self.choose_root)
        self.root_button.pack(side="right", padx=(10, 0))

        metadata_frame = ttk.LabelFrame(main, text="メタデータJSON", padding=10)
        metadata_frame.pack(fill="x", pady=(10, 0))
        metadata_top = ttk.Frame(metadata_frame)
        metadata_top.pack(fill="x")
        self.meta_label = ttk.Label(
            metadata_top,
            textvariable=self.metadata_path,
            wraplength=500,
            font=SMALL_FONT,
        )
        self.meta_label.pack(side="left", fill="x", expand=True)
        self.meta_browse_button = ttk.Button(metadata_top, text="変更", command=self.choose_metadata)
        self.meta_browse_button.pack(side="right", padx=(8, 0))
        self.import_button = ttk.Button(metadata_top, text="取込", command=self.import_metadata)
        self.import_button.pack(side="right", padx=(8, 0))
        ttk.Label(metadata_frame, textvariable=self.metadata_status, font=SMALL_FONT).pack(anchor="w", pady=(6, 0))
        ttk.Label(metadata_frame, textvariable=self.probe_status, font=SMALL_FONT).pack(anchor="w", pady=(2, 0))

        button_frame = ttk.Frame(main)
        button_frame.pack(fill="x", pady=14)
        self.start_button = ttk.Button(button_frame, text="ライブラリを開始", command=self.start_library)
        self.start_button.pack(side="left")
        self.browser_button = ttk.Button(button_frame, text="ブラウザで開く", command=self.open_browser, state="disabled")
        self.browser_button.pack(side="left", padx=8)
        self.stop_button = ttk.Button(button_frame, text="停止", command=self.stop_server, state="disabled")
        self.stop_button.pack(side="left")
        ttk.Button(button_frame, text="データ保存先を開く", command=self.open_data_folder).pack(side="right")

        remote_frame = ttk.LabelFrame(main, text="外部接続（Tailscale）", padding=10)
        remote_frame.pack(fill="x", pady=(0, 12))
        ttk.Label(
            remote_frame,
            textvariable=self.remote,
            wraplength=710,
            font=SMALL_FONT,
        ).pack(anchor="w", fill="x")
        remote_buttons = ttk.Frame(remote_frame)
        remote_buttons.pack(fill="x", pady=(8, 0))
        self.remote_enable_button = ttk.Button(remote_buttons, text="外部接続を有効化", command=self.enable_remote)
        self.remote_enable_button.pack(side="left")
        self.remote_disable_button = ttk.Button(remote_buttons, text="外部接続を停止", command=self.disable_remote)
        self.remote_disable_button.pack(side="left", padx=8)
        self.remote_open_button = ttk.Button(remote_buttons, text="外部URLを開く", command=self.open_remote, state="disabled")
        self.remote_open_button.pack(side="left")
        ttk.Button(remote_buttons, text="Tailscale再確認", command=self.refresh_remote).pack(side="right")

        cache_frame = ttk.LabelFrame(main, text="再生キャッシュ", padding=10)
        cache_frame.pack(fill="x", pady=(0, 12))
        cache_top = ttk.Frame(cache_frame)
        cache_top.pack(fill="x")
        ttk.Label(cache_top, textvariable=self.cache_status, font=SMALL_FONT).pack(side="left", fill="x", expand=True)
        self.cache_clear_button = ttk.Button(cache_top, text="キャッシュをすべて削除", command=self.clear_playback_cache_files)
        self.cache_clear_button.pack(side="right")
        ttk.Button(cache_top, text="容量再確認", command=self.refresh_cache_status).pack(side="right", padx=(0, 8))
        ttk.Label(
            cache_frame,
            text="上限を超えると古い変換キャッシュから自動削除します。元動画は削除しません。",
            font=SMALL_FONT,
        ).pack(anchor="w", pady=(5, 0))

        operations_frame = ttk.Frame(main)
        operations_frame.pack(fill="x", pady=(0, 10))
        ttk.Button(operations_frame, text="バックアップ作成", command=self.backup).pack(side="left")
        self.audit_button = ttk.Button(
            operations_frame, text="全件再生監査", command=self.start_playback_audit
        )
        self.audit_button.pack(side="left", padx=8)
        ttk.Button(operations_frame, text="状態再確認", command=self.refresh_local_status).pack(side="left")
        self.tmdb_sync_button = ttk.Button(operations_frame, text="TMDb同期", command=self.start_tmdb_sync)
        self.tmdb_sync_button.pack(side="left", padx=(0, 8))
        ttk.Button(operations_frame, text="TMDb設定", command=self.open_tmdb_settings).pack(side="left", padx=(0, 8))
        ttk.Label(
            operations_frame,
            text="停止中に全件再生監査を実行できます。",
            font=SMALL_FONT,
        ).pack(side="right")

        ttk.Label(main, textvariable=self.status, font=STATUS_FONT).pack(anchor="w", pady=(0, 6))

        scan_box = ttk.LabelFrame(main, text="起動スキャン", padding=10)
        scan_box.pack(fill="both", expand=True)
        ttk.Label(scan_box, textvariable=self.scan_status, font=STATUS_FONT).pack(anchor="w")
        self.scan_progress = ttk.Progressbar(scan_box, mode="determinate", maximum=100)
        self.scan_progress.pack(fill="x", pady=(8, 5))
        ttk.Label(scan_box, textvariable=self.scan_counts, font=SMALL_FONT).pack(anchor="w")
        ttk.Label(scan_box, textvariable=self.scan_current, font=SMALL_FONT).pack(anchor="w", pady=(3, 0))
        ttk.Label(scan_box, textvariable=self.scan_elapsed, font=SMALL_FONT).pack(anchor="w", pady=(2, 6))
        self.log_text = tk.Text(scan_box, height=4, wrap="none", font=MONO_FONT, state="disabled")
        self.log_text.pack(fill="both", expand=True)


    def open_tmdb_settings(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("TMDb設定")
        dialog.geometry("520x245")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="TMDb API Read Access Token", font=STATUS_FONT).pack(anchor="w")
        source = tmdb_token_source(config_path=CONFIG_PATH)
        source_text = {
            "environment": "現在: 環境変数 VIDEO_LIBRARY_TMDB_TOKEN で設定済み",
            "config": "現在: ローカル設定に保存済み",
            "none": "現在: 未設定（TMDb未設定でも既存機能は利用できます）",
        }.get(source, "現在: 未設定")
        ttk.Label(frame, text=source_text, font=SMALL_FONT, wraplength=470).pack(anchor="w", pady=(6, 10))
        ttk.Label(
            frame,
            text="新しいトークンを入力して保存してください。保存済みトークンの値は画面へ再表示しません。",
            font=SMALL_FONT,
            wraplength=470,
        ).pack(anchor="w")
        token_value = tk.StringVar(value="")
        entry = ttk.Entry(frame, textvariable=token_value, show="*")
        entry.pack(fill="x", pady=(8, 12))

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")

        def save_local() -> None:
            value = token_value.get().strip()
            if not value:
                messagebox.showinfo(APP_NAME, "保存するトークンを入力してください。", parent=dialog)
                return
            save_tmdb_token(value, config_path=CONFIG_PATH)
            token_value.set("")
            messagebox.showinfo(APP_NAME, "TMDbトークンをローカル設定へ保存しました。", parent=dialog)
            dialog.destroy()

        def clear_local() -> None:
            save_tmdb_token(None, config_path=CONFIG_PATH)
            token_value.set("")
            if configured_tmdb_token(config_path=CONFIG_PATH):
                messagebox.showinfo(
                    APP_NAME,
                    "ローカル設定を削除しました。環境変数のTMDbトークンは引き続き有効です。",
                    parent=dialog,
                )
            else:
                messagebox.showinfo(APP_NAME, "ローカルのTMDb設定を削除しました。", parent=dialog)
            dialog.destroy()

        ttk.Button(buttons, text="保存", command=save_local).pack(side="left")
        ttk.Button(buttons, text="ローカル設定を削除", command=clear_local).pack(side="left", padx=8)
        ttk.Button(buttons, text="閉じる", command=dialog.destroy).pack(side="right")
        entry.focus_set()


    def start_tmdb_sync(self) -> None:
        if self.server is not None or self.scan_thread is not None or self.audit_thread is not None or self.tmdb_thread is not None:
            messagebox.showinfo(APP_NAME, "TMDb同期の前にライブラリを停止してください。")
            return
        if not DATABASE_PATH.is_file():
            messagebox.showerror(APP_NAME, "ライブラリDBが見つかりません。")
            return
        token = configured_tmdb_token(config_path=CONFIG_PATH)
        if not token:
            messagebox.showinfo(APP_NAME, "先に「TMDb設定」でAPI Read Access Tokenを設定してください。")
            return
        if not messagebox.askyesno(
            APP_NAME,
            "登録作品をTMDbと照合し、高信頼で一致した作品のポスター／背景画像を保存します。\n"
            "低信頼候補は自動確定しません。開始しますか？",
        ):
            return
        self._set_busy(True)
        self.status.set("TMDb作品情報を同期中です")
        self.scan_status.set("TMDb同期中 — 作品を照合しています")
        self.scan_counts.set("MATCHED 0 / REVIEW 0 / UNMATCHED 0")
        self.scan_current.set("現在処理中: —")
        self.scan_progress.configure(mode="determinate", maximum=1)
        self.scan_progress["value"] = 0
        self._append_log("=" * 72)
        self._append_log("TMDb作品照合を開始します。低信頼候補は自動確定しません。")
        self.tmdb_thread = threading.Thread(
            target=self._tmdb_sync_worker,
            args=(token,),
            daemon=True,
            name="VideoLibraryTmdbSync",
        )
        self.tmdb_thread.start()

    def _tmdb_sync_worker(self, token: str) -> None:
        try:
            report = sync_tmdb_library(
                DATABASE_PATH,
                TMDB_IMAGE_PATH,
                TMDB_REPORT_OUTPUT_PATH,
                token,
                progress_callback=self._tmdb_progress_from_worker,
            )
        except Exception as exc:
            self.after(0, lambda e=exc: self._tmdb_sync_failed(e))
            return
        self.after(0, lambda r=report: self._tmdb_sync_succeeded(r))

    def _tmdb_progress_from_worker(self, progress: dict[str, Any]) -> None:
        snapshot = dict(progress)
        self.after(0, lambda p=snapshot: self._apply_tmdb_progress(p))

    def _apply_tmdb_progress(self, progress: dict[str, Any]) -> None:
        current = int(progress.get("current") or 0)
        total = int(progress.get("total") or 0)
        matched = int(progress.get("matched") or 0)
        review = int(progress.get("review") or 0)
        unmatched = int(progress.get("unmatched") or 0)
        self.scan_status.set(f"TMDb同期中 — {current:,} / {total:,}")
        self.scan_counts.set(f"MATCHED {matched:,} / REVIEW {review:,} / UNMATCHED {unmatched:,}")
        self.scan_current.set(f"現在処理中: {progress.get('currentItem') or '—'}")
        self.scan_progress.configure(mode="determinate", maximum=max(1, total))
        self.scan_progress["value"] = min(current, total)
        if current and (current % 25 == 0 or current == total):
            self._append_log(
                f"TMDb {current:,}/{total:,}: MATCHED {matched:,} / REVIEW {review:,} / UNMATCHED {unmatched:,}"
            )

    def _tmdb_sync_succeeded(self, report: dict[str, Any]) -> None:
        self.tmdb_thread = None
        summary = report.get("summary") or {}
        total = int(summary.get("total") or 0)
        matched = int(summary.get("matched") or 0)
        review = int(summary.get("review") or 0)
        unmatched = int(summary.get("unmatched") or 0)
        posters = int(summary.get("posterCached") or 0)
        backdrops = int(summary.get("backdropCached") or 0)
        self.scan_progress.configure(mode="determinate", maximum=max(1, total))
        self.scan_progress["value"] = total
        self.scan_status.set("完了 — TMDb作品情報を同期しました")
        self.scan_counts.set(f"MATCHED {matched:,} / REVIEW {review:,} / UNMATCHED {unmatched:,}")
        self.scan_current.set("現在処理中: 完了")
        self.status.set("TMDb作品情報の同期が完了しました")
        self._append_log(
            f"TMDb同期完了: {total:,}作品 / MATCHED {matched:,} / REVIEW {review:,} / UNMATCHED {unmatched:,}"
        )
        self._append_log(f"ポスター {posters:,} / 背景 {backdrops:,} / JSON: {report.get('jsonReport', '')}")
        self._append_log(f"CSV : {report.get('csvReport', '')}")
        self._set_busy(False)
        messagebox.showinfo(
            APP_NAME,
            "TMDb同期が完了しました。\n\n"
            f"登録作品: {total:,}\nMATCHED: {matched:,}\nREVIEW: {review:,}\nUNMATCHED: {unmatched:,}\n"
            f"ポスター保存: {posters:,}\n背景保存: {backdrops:,}\n\n"
            "REVIEWは自動確定していません。診断CSVで確認できます。",
        )

    def _tmdb_sync_failed(self, exc: Exception) -> None:
        self.tmdb_thread = None
        self.status.set("TMDb同期に失敗しました")
        self.scan_status.set("失敗 — TMDb作品情報を同期できませんでした")
        self._append_log(f"TMDb ERROR: {type(exc).__name__}: {exc}")
        self._set_busy(False)
        messagebox.showerror(APP_NAME, f"TMDb同期に失敗しました。\n{exc}")


    def refresh_cache_status(self) -> None:
        stats = playback_cache_stats(PLAYBACK_CACHE_PATH)
        self.cache_status.set(
            f"再生キャッシュ: {format_bytes(stats.total_bytes)} / 上限 {format_bytes(DEFAULT_CACHE_LIMIT_BYTES)} "
            f"（{stats.file_count:,}ファイル）"
        )

    def clear_playback_cache_files(self) -> None:
        if self.server is not None or self.scan_thread is not None:
            messagebox.showinfo(APP_NAME, "キャッシュ削除前にライブラリを停止してください。")
            return
        stats = playback_cache_stats(PLAYBACK_CACHE_PATH)
        if stats.file_count == 0 and not PLAYBACK_CACHE_PATH.exists():
            self.refresh_cache_status()
            messagebox.showinfo(APP_NAME, "削除する再生キャッシュはありません。")
            return
        if not messagebox.askyesno(
            APP_NAME,
            f"再生キャッシュ {format_bytes(stats.total_bytes)} を削除しますか？\n元動画は削除されません。",
        ):
            return
        result = clear_playback_cache(PLAYBACK_CACHE_PATH)
        self.refresh_cache_status()
        if result.failed_files:
            messagebox.showwarning(
                APP_NAME,
                f"{result.removed_files}ファイルを削除しました。\n{result.failed_files}ファイルは削除できませんでした。",
            )
        else:
            messagebox.showinfo(
                APP_NAME,
                f"再生キャッシュを削除しました。\n{result.removed_files}ファイル / {format_bytes(result.removed_bytes)}",
            )

    def start_playback_audit(self) -> None:
        if self.server is not None or self.scan_thread is not None or self.audit_thread is not None:
            messagebox.showinfo(APP_NAME, "全件再生監査の前にライブラリを停止してください。")
            return
        root_text = self.video_root.get().strip()
        root = Path(root_text).expanduser() if root_text and root_text != "未設定" else Path()
        if not root.is_dir() or not DATABASE_PATH.is_file():
            messagebox.showerror(APP_NAME, "動画フォルダーまたはライブラリDBを確認してください。")
            return
        if find_ffprobe() is None:
            messagebox.showerror(APP_NAME, "ffprobeが見つからないため全件再生監査を実行できません。")
            return
        if not messagebox.askyesno(
            APP_NAME,
            "登録済み動画を全件ffprobe解析します。\n数分以上かかる場合があります。開始しますか？",
        ):
            return

        self._set_busy(True)
        self.audit_started_monotonic = time.monotonic()
        self.status.set("全件再生監査を実行中です")
        self.scan_status.set("再生監査中 — ffprobeで登録動画を確認しています")
        self.scan_counts.set("DIRECT 0 / 互換変換 0 / アプリ再生不可 0 / 元データ異常 0")
        self.scan_current.set("現在処理中: —")
        self.scan_elapsed.set("経過: 0:00")
        self.scan_progress.configure(mode="determinate", maximum=1)
        self.scan_progress["value"] = 0
        self._append_log("=" * 72)
        self._append_log("v1.0前 全件再生監査を開始します。元動画は変更しません。")
        self.audit_thread = threading.Thread(
            target=self._playback_audit_worker,
            args=(root,),
            daemon=True,
            name="VideoLibraryPlaybackAudit",
        )
        self.audit_thread.start()

    def _playback_audit_worker(self, root: Path) -> None:
        try:
            report = audit_real_library(
                DATABASE_PATH,
                root,
                PLAYBACK_AUDIT_OUTPUT_PATH,
                progress_callback=self._audit_progress_from_worker,
            )
        except Exception as exc:
            self.after(0, lambda e=exc: self._playback_audit_failed(e))
            return
        self.after(0, lambda r=report: self._playback_audit_succeeded(r))

    def _audit_progress_from_worker(self, progress: dict[str, Any]) -> None:
        snapshot = dict(progress)
        self.after(0, lambda p=snapshot: self._apply_audit_progress(p))

    def _apply_audit_progress(self, progress: dict[str, Any]) -> None:
        current = int(progress.get("current") or 0)
        total = int(progress.get("total") or 0)
        direct = int(progress.get("direct") or 0)
        transcode = int(progress.get("transcode") or 0)
        application_no_route = int(progress.get("applicationNoRoute") or 0)
        source_errors = int(progress.get("sourceDataErrors") or 0)
        current_item = str(progress.get("currentItem") or "—")
        self.scan_status.set(f"再生監査中 — {current:,} / {total:,}")
        self.scan_counts.set(
            f"DIRECT {direct:,} / 互換変換 {transcode:,} / "
            f"アプリ再生不可 {application_no_route:,} / 元データ異常 {source_errors:,}"
        )
        self.scan_current.set(f"現在処理中: {current_item}")
        self.scan_progress.configure(mode="determinate", maximum=max(1, total))
        self.scan_progress["value"] = min(current, total)
        if self.audit_started_monotonic is not None:
            seconds = max(0, int(time.monotonic() - self.audit_started_monotonic))
            self.scan_elapsed.set(f"経過: {seconds // 60}:{seconds % 60:02d}")
        if current and (current % 250 == 0 or current == total):
            self._append_log(
                f"監査 {current:,}/{total:,}: DIRECT {direct:,} / 互換変換 {transcode:,} / "
                f"アプリ再生不可 {application_no_route:,} / 元データ異常 {source_errors:,}"
            )

    def _playback_audit_succeeded(self, report: dict[str, Any]) -> None:
        self.audit_thread = None
        summary = report.get("summary") or {}
        total = int(summary.get("total") or 0)
        playable_total = int(summary.get("playableVideoTotal") or 0)
        direct = int(summary.get("direct") or 0)
        transcode = int(summary.get("transcode") or 0)
        application_no_route = int(summary.get("applicationNoRoute") or 0)
        source_errors = int(summary.get("sourceDataErrors") or 0)
        repair_with_candidates = int(summary.get("sourceDataErrorsWithCandidates") or 0)
        repair_without_candidates = int(summary.get("sourceDataErrorsWithoutCandidates") or 0)
        self.scan_progress.configure(mode="determinate", maximum=max(1, total))
        self.scan_progress["value"] = total
        self.scan_status.set("完了 — 全件再生監査が完了しました")
        self.scan_counts.set(
            f"DIRECT {direct:,} / 互換変換 {transcode:,} / "
            f"アプリ再生不可 {application_no_route:,} / 元データ異常 {source_errors:,}"
        )
        self.scan_current.set("現在処理中: 完了")
        self.status.set("全件再生監査が完了しました")
        self._append_log(
            f"全件再生監査完了: 登録 {total:,}件 / 実動画 {playable_total:,}件 / "
            f"DIRECT {direct:,} / 互換変換 {transcode:,} / "
            f"アプリ再生不可 {application_no_route:,} / 元データ異常 {source_errors:,}"
        )
        self._append_log(f"JSON: {report.get('jsonReport', '')}")
        self._append_log(f"CSV : {report.get('csvReport', '')}")
        self._append_log(
            f"元データ修復候補: 候補あり {repair_with_candidates:,}件 / 候補なし {repair_without_candidates:,}件"
        )
        self._append_log(f"元データ異常CSV: {report.get('sourceErrorsCsvReport', '')}")
        self._set_busy(False)
        message = (
            f"全件再生監査が完了しました。\n\n"
            f"登録: {total:,}件\n"
            f"実動画: {playable_total:,}件\n"
            f"DIRECT: {direct:,}件\n"
            f"互換変換: {transcode:,}件\n"
            f"アプリ再生不可: {application_no_route:,}件\n"
            f"元データ異常: {source_errors:,}件\n"
            f"修復候補あり: {repair_with_candidates:,}件\n"
            f"修復候補なし: {repair_without_candidates:,}件\n\n"
            f"レポート: {PLAYBACK_AUDIT_OUTPUT_PATH}"
        )
        if application_no_route:
            messagebox.showwarning(APP_NAME, message + "\n\nアプリ側の再生互換性に未解決項目があります。")
        elif source_errors:
            messagebox.showwarning(
                APP_NAME,
                message
                + "\n\n実動画の再生互換性は合格です。"
                + "\n元データ異常CSVの修復候補を確認し、元ファイルは手動で確認・差し替えてください。",
            )
        else:
            messagebox.showinfo(APP_NAME, message + "\n\nv1.0再生受入条件を満たしています。")

    def _playback_audit_failed(self, exc: Exception) -> None:
        self.audit_thread = None
        self.status.set("全件再生監査に失敗しました")
        self.scan_status.set("失敗 — 全件再生監査を完了できませんでした")
        self._append_log(f"AUDIT ERROR: {type(exc).__name__}: {exc}")
        self._set_busy(False)
        messagebox.showerror(APP_NAME, f"全件再生監査に失敗しました。\n{exc}")

    def open_data_folder(self) -> None:
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(DATA_ROOT))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["explorer", str(DATA_ROOT)])
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"データ保存先を開けませんでした。\n{exc}")

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.start_button.configure(state=state)
        self.root_button.configure(state=state)
        self.meta_browse_button.configure(state=state)
        self.import_button.configure(state=state)
        self.audit_button.configure(state=state)
        self.tmdb_sync_button.configure(state=state)
        if busy:
            self.browser_button.configure(state="disabled")
            self.stop_button.configure(state="disabled")
        else:
            self.browser_button.configure(state="normal" if self.server is not None else "disabled")
            self.stop_button.configure(state="normal" if self.server is not None else "disabled")

    def _save_config(self) -> None:
        value = load_config(CONFIG_PATH)
        root_value = self.video_root.get().strip()
        metadata_value = self.metadata_path.get().strip()
        value["videoRoot"] = "" if root_value == "未設定" else root_value
        value["metadataPath"] = "" if metadata_value == "未設定" else metadata_value
        save_config(value, CONFIG_PATH)

    def choose_root(self) -> None:
        selected = filedialog.askdirectory(title="動画フォルダーを選択")
        if selected:
            self.video_root.set(selected)
            self._save_config()

    def choose_metadata(self) -> None:
        selected = filedialog.askopenfilename(
            title="video_library.json を選択",
            filetypes=[("JSON", "*.json"), ("すべてのファイル", "*.*")],
        )
        if selected:
            self.metadata_path.set(selected)
            self._save_config()

    def import_metadata(self) -> None:
        if self.server is not None or self.scan_thread is not None:
            messagebox.showinfo(APP_NAME, "メタデータ取込前にライブラリを停止してください。")
            return
        source_text = self.metadata_path.get().strip()
        source = Path(source_text).expanduser() if source_text and source_text != "未設定" else Path()
        if not source.is_file():
            messagebox.showerror(APP_NAME, "メタデータJSONが見つかりません。")
            return
        try:
            METADATA_PATH.parent.mkdir(parents=True, exist_ok=True)
            if source.resolve() != METADATA_PATH.resolve():
                shutil.copy2(source, METADATA_PATH)
            import_file(METADATA_PATH, DATABASE_PATH)
            self.metadata_path.set(str(METADATA_PATH))
            self._save_config()
            self.refresh_local_status()
            works, videos = database_counts()
            messagebox.showinfo(APP_NAME, f"メタデータを取り込みました。\n{works}作品 / {videos}動画")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"メタデータを取り込めませんでした。\n{exc}")

    def refresh_local_status(self) -> None:
        try:
            works, videos = database_counts()
            self.metadata_status.set(f"メタデータ: {works}作品 / {videos}動画")
        except Exception as exc:
            self.metadata_status.set(f"メタデータ: エラー ({exc})")
        ffprobe = find_ffprobe()
        self.probe_status.set(f"ffprobe: {'利用可 - ' + str(ffprobe) if ffprobe else '未検出（動画解析のみ省略）'}")
        self.refresh_cache_status()

    def _auto_start_if_ready(self) -> None:
        if self.server is not None or self.scan_thread is not None:
            return
        root_text = self.video_root.get().strip()
        if not root_text or root_text == "未設定":
            self.status.set("動画フォルダーとメタデータを確認してください")
            return
        root = Path(root_text).expanduser()
        if not root.is_dir() or not DATABASE_PATH.is_file():
            self.status.set("動画フォルダーとメタデータを確認してください")
            return
        try:
            works, videos = database_counts()
        except Exception:
            return
        if works > 0 and videos > 0:
            self.start_library(auto=True)

    def start_library(self, auto: bool = False) -> None:
        if self.server is not None:
            self.open_browser()
            return
        if self.scan_thread is not None:
            return
        root_text = self.video_root.get().strip()
        root = Path(root_text).expanduser() if root_text and root_text != "未設定" else Path()
        if not root.is_dir():
            if auto:
                self.status.set("動画フォルダーを確認してください")
            else:
                messagebox.showerror(APP_NAME, "動画フォルダーが見つかりません。")
            return

        self._save_config()
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        restore = apply_pending_restore(DATA_ROOT)
        if restore and restore.get("state") == "error":
            messagebox.showwarning(APP_NAME, f"予約された復元に失敗しました。\n{restore.get('error', '')}")
        try:
            works, videos = database_counts()
            if works == 0 or videos == 0:
                raise RuntimeError("先に監査済み video_library.json を取り込んでください。")
            recovered = recover_interrupted_scans(DATABASE_PATH)
        except Exception as exc:
            if auto:
                self.status.set(f"起動準備エラー: {exc}")
            else:
                messagebox.showerror(APP_NAME, f"起動準備に失敗しました。\n{exc}")
            return

        self._set_busy(True)
        self.scan_started_monotonic = time.monotonic()
        self._last_phase = ""
        self._last_logged_current = -1
        self.status.set("動画ライブラリを準備中 — 起動スキャンを実行しています")
        self.scan_status.set("準備中 — スキャンを開始しています")
        self.scan_counts.set("MATCHED 0 / MISSING 0 / NEW_FILE 0 / 字幕 0 / ffprobe 0")
        self.scan_current.set("現在処理中: —")
        self.scan_elapsed.set("経過: 0:00")
        self.scan_progress.configure(mode="indeterminate")
        self.scan_progress.start(12)
        self._indeterminate = True
        self._append_log("=" * 72)
        self._append_log(f"{APP_NAME} {APP_VERSION}")
        self._append_log(f"動画フォルダー: {root}")
        if recovered:
            self._append_log(f"前回中断スキャン回収: {recovered}件")
        self._append_log("起動スキャンを開始します。ブラウザは完了後に開きます。")
        atomic_write_json(RUNTIME_PATH, {"state": "scanning", "videoRoot": str(root)})

        self.scan_thread = threading.Thread(
            target=self._startup_scan_worker,
            args=(root,),
            daemon=True,
            name="VideoLibraryStartupScan",
        )
        self.scan_thread.start()

    def _startup_scan_worker(self, root: Path) -> None:
        try:
            result = run_startup_scan(
                DATABASE_PATH,
                root,
                progress_callback=self._progress_from_worker,
            )
        except Exception as exc:
            self.after(0, lambda e=exc: self._startup_scan_failed(e))
            return
        self.after(0, lambda r=result, p=root: self._startup_scan_succeeded(p, r))

    def _progress_from_worker(self, progress: dict[str, Any]) -> None:
        snapshot = dict(progress)
        self.after(0, lambda p=snapshot: self._apply_scan_progress(p))

    def _apply_scan_progress(self, progress: dict[str, Any]) -> None:
        phase = str(progress.get("phase") or "")
        message = str(progress.get("message") or _phase_text(phase))
        current = int(progress.get("current") or 0)
        total = int(progress.get("total") or 0)
        matched = int(progress.get("filesMatched") or 0)
        missing = int(progress.get("filesMissing") or 0)
        new_file = int(progress.get("filesNew") or 0)
        subtitles = int(progress.get("subtitlesFound") or 0)
        probed = int(progress.get("filesProbed") or 0)
        current_item = str(progress.get("currentItem") or "—")

        self.scan_status.set(f"{_phase_text(phase)} — {message}")
        self.scan_counts.set(
            f"MATCHED {matched:,} / MISSING {missing:,} / NEW_FILE {new_file:,} / "
            f"字幕 {subtitles:,} / ffprobe {probed:,}"
        )
        self.scan_current.set(f"現在処理中: {current_item}")
        if self.scan_started_monotonic is not None:
            seconds = max(0, int(time.monotonic() - self.scan_started_monotonic))
            self.scan_elapsed.set(f"経過: {seconds // 60}:{seconds % 60:02d}")

        if total > 0:
            if self._indeterminate:
                self.scan_progress.stop()
                self._indeterminate = False
            self.scan_progress.configure(mode="determinate", maximum=max(1, total))
            self.scan_progress["value"] = min(current, total)
        elif not self._indeterminate:
            self.scan_progress.configure(mode="indeterminate")
            self.scan_progress.start(12)
            self._indeterminate = True

        if phase != self._last_phase:
            self._append_log(f"[{_phase_text(phase)}] {message}")
            self._last_phase = phase
        if current > 0 and (current >= self._last_logged_current + 250 or (total > 0 and current == total)):
            suffix = f" / {total:,}" if total else ""
            self._append_log(f"  {current:,}{suffix}  {current_item}")
            self._last_logged_current = current

    def _startup_scan_succeeded(self, root: Path, result: dict[str, Any]) -> None:
        self.scan_thread = None
        if self._indeterminate:
            self.scan_progress.stop()
            self._indeterminate = False
        self.scan_progress.configure(mode="determinate", maximum=100)
        self.scan_progress["value"] = 100
        self.scan_status.set("完了 — 起動スキャンが完了しました")
        self.scan_counts.set(
            f"MATCHED {int(result.get('filesMatched') or 0):,} / "
            f"MISSING {int(result.get('filesMissing') or 0):,} / "
            f"NEW_FILE {int(result.get('filesNew') or 0):,} / "
            f"字幕 {int(result.get('subtitlesFound') or 0):,} / "
            f"ffprobe {int(result.get('filesProbed') or 0):,}"
        )
        self.scan_current.set("現在処理中: 完了")
        elapsed_ms = int(result.get("durationMs") or 0)
        self.scan_elapsed.set(f"経過: {elapsed_ms // 60000}:{(elapsed_ms // 1000) % 60:02d}")
        self._append_log(
            "スキャン完了: "
            f"一致 {result.get('filesMatched', 0):,} / 欠落 {result.get('filesMissing', 0):,} / "
            f"新規 {result.get('filesNew', 0):,} / 字幕 {result.get('subtitlesFound', 0):,}"
        )
        repaired = int(result.get("pathsRepaired") or 0)
        if repaired:
            self._append_log(f"文字化けパス修復: {repaired:,}件")
        unsupported = int(result.get("unsupportedSubtitles") or 0)
        if unsupported:
            self._append_log(f"未対応字幕: {unsupported:,}件（IDX/SUB/SMI・診断のみ）")
        self.status.set("スキャン完了 — ブラウザを起動しています")
        if not self._start_http_server(root):
            self._set_busy(False)
            return
        self._set_busy(False)
        self.open_browser()

    def _startup_scan_failed(self, exc: Exception) -> None:
        self.scan_thread = None
        if self._indeterminate:
            self.scan_progress.stop()
            self._indeterminate = False
        self.scan_progress.configure(mode="determinate", maximum=100)
        self.scan_progress["value"] = 0
        self.scan_status.set("失敗 — 起動スキャンを完了できませんでした")
        self.status.set("起動スキャンに失敗しました。ブラウザは起動していません。")
        self.scan_current.set("現在処理中: —")
        self._append_log(f"ERROR: {type(exc).__name__}: {exc}")
        atomic_write_json(RUNTIME_PATH, {"state": "error", "message": str(exc)})
        self._set_busy(False)
        messagebox.showerror(APP_NAME, f"起動スキャンに失敗しました。\n{exc}")

    def _start_http_server(self, root: Path) -> bool:
        self.control_secret = secrets.token_urlsafe(48)
        try:
            self.server = create_server(
                DATABASE_PATH,
                host="127.0.0.1",
                port=DEFAULT_PORT,
                video_root=root,
                owner_control_secret=self.control_secret,
                data_root=DATA_ROOT,
            )
        except Exception as exc:
            self.server = None
            self.status.set("サーバーを開始できませんでした")
            self._append_log(f"SERVER ERROR: {exc}")
            messagebox.showerror(APP_NAME, f"サーバーを開始できませんでした。\n{exc}")
            return False
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        url = f"http://127.0.0.1:{self.server.server_port}/"
        atomic_write_json(
            RUNTIME_PATH,
            {"state": "running", "port": self.server.server_port, "url": url, "videoRoot": str(root)},
        )
        self.status.set(f"実行中 — ブラウザで利用できます  {url}")
        self._append_log(f"ブラウザURL: {url}")
        return True

    def open_browser(self) -> None:
        if self.server is None:
            self.start_library()
            return
        base = f"http://127.0.0.1:{self.server.server_port}/"
        try:
            webbrowser.open(request_local_owner_browser_url(base, self.control_secret))
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"オーナーとしてブラウザを開けませんでした。\n{exc}")

    def stop_server(self) -> None:
        if self.scan_thread is not None:
            messagebox.showinfo(APP_NAME, "起動スキャン中です。終了する場合はこのウィンドウを閉じてください。")
            return
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        self.status.set("停止中")
        self.browser_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")
        self.start_button.configure(state="normal")
        atomic_write_json(RUNTIME_PATH, {"state": "stopped"})

    def refresh_remote(self) -> None:
        status = get_remote_status()
        self.remote_url = status.serve_url if status.serve_active else ""
        self.remote_open_button.configure(state="normal" if self.remote_url else "disabled")
        if not status.installed:
            self.remote.set("Tailscale未インストール")
        elif not status.logged_in:
            self.remote.set("未ログイン")
        elif status.serve_active:
            self.remote.set(f"動画版の外部接続は有効です： {status.serve_url}")
        else:
            self.remote.set("Tailscaleログイン済み / 動画版の外部接続は停止中")

    def open_remote(self) -> None:
        if not self.remote_url:
            self.refresh_remote()
        if not self.remote_url:
            messagebox.showinfo(APP_NAME, "動画版の外部接続を先に有効化してください。")
            return
        try:
            webbrowser.open(self.remote_url)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"外部URLを開けませんでした。\n{exc}")

    def enable_remote(self) -> None:
        if self.server is None:
            messagebox.showinfo(APP_NAME, "先に動画ライブラリを開始してください。")
            return
        ok, url, message = enable_remote_access(self.server.server_port)
        self.refresh_remote()
        messagebox.showinfo(APP_NAME, f"{message}\n{url}") if ok else messagebox.showerror(APP_NAME, message)

    def disable_remote(self) -> None:
        result = disable_remote_access()
        self.refresh_remote()
        if result.returncode != 0:
            messagebox.showerror(APP_NAME, result.output)

    def backup(self) -> None:
        try:
            item = create_manual_backup(database_path=DATABASE_PATH, backup_dir=DATA_ROOT / "Backups")
            messagebox.showinfo(APP_NAME, f"バックアップを作成しました。\n{item['name']}")
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def close(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        atomic_write_json(RUNTIME_PATH, {"state": "stopped"})
        self.destroy()


def main() -> int:
    VideoLibraryLauncher().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())