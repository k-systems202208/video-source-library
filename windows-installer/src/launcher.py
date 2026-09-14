from __future__ import annotations

import json
import secrets
import shutil
import threading
import tkinter as tk
import urllib.parse
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app_config import load_config, save_config
from backup_restore import apply_pending_restore, create_manual_backup
from database import connect, initialize_database
from local_auth import create_bootstrap_token
from media_probe import find_ffprobe
from metadata_importer import import_file
from paths import CONFIG_PATH, DATABASE_PATH, DATA_ROOT, RUNTIME_PATH
from remote_access import disable_remote_access, enable_remote_access, get_remote_status
from server import create_server

APP_NAME = "自宅動画ライブラリ"
APP_VERSION = "0.6.2"
DEFAULT_PORT = 8765
METADATA_PATH = DATA_ROOT / "metadata" / "video_library.json"


def atomic_write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def request_local_owner_browser_url(page_url: str, control_secret: str) -> str:
    parsed = urllib.parse.urlsplit(page_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("owner authentication endpoint must be localhost HTTP")

    # Launcher and server share the same per-process control secret. Generate a
    # signed one-time token in-process instead of registering it over localhost
    # HTTP. This avoids interception by Windows/corporate local web filters.
    token = create_bootstrap_token(control_secret, ttl_seconds=60)
    exchange = urllib.parse.urljoin(page_url, "/api/local-auth/exchange")
    return exchange + "?" + urllib.parse.urlencode({"token": token})


def database_counts() -> tuple[int, int]:
    if not DATABASE_PATH.is_file():
        return 0, 0
    with connect(DATABASE_PATH) as connection:
        initialize_database(connection)
        works = int(connection.execute("SELECT COUNT(*) FROM works").fetchone()[0])
        videos = int(connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0])
    return works, videos


class VideoLibraryLauncher(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("780x500")
        self.minsize(700, 460)
        self.server = None
        self.server_thread: threading.Thread | None = None
        self.control_secret = ""
        config = load_config(CONFIG_PATH)
        default_metadata = str(METADATA_PATH) if METADATA_PATH.is_file() else ""
        self.video_root = tk.StringVar(value=str(config.get("videoRoot") or ""))
        self.metadata_path = tk.StringVar(value=str(config.get("metadataPath") or default_metadata))
        self.status = tk.StringVar(value="停止中")
        self.metadata_status = tk.StringVar(value="メタデータ未確認")
        self.probe_status = tk.StringVar(value="ffprobe未確認")
        self.remote = tk.StringVar(value="未確認")
        self._build()
        self.after(200, self.refresh_local_status)
        self.after(300, self.refresh_remote)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=18); frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=APP_NAME, font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(frame, textvariable=self.status).pack(anchor="w", pady=(2, 16))

        row = ttk.Frame(frame); row.pack(fill="x", pady=3)
        ttk.Label(row, text="動画フォルダー", width=16).pack(side="left")
        ttk.Entry(row, textvariable=self.video_root).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row, text="参照", command=self.choose_root).pack(side="right")

        meta_row = ttk.Frame(frame); meta_row.pack(fill="x", pady=3)
        ttk.Label(meta_row, text="メタデータJSON", width=16).pack(side="left")
        ttk.Entry(meta_row, textvariable=self.metadata_path).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(meta_row, text="参照", command=self.choose_metadata).pack(side="right")
        ttk.Button(meta_row, text="取込", command=self.import_metadata).pack(side="right", padx=(0, 8))

        ttk.Label(frame, textvariable=self.metadata_status).pack(anchor="w", pady=(4, 0))
        ttk.Label(frame, textvariable=self.probe_status).pack(anchor="w", pady=(2, 0))

        buttons = ttk.Frame(frame); buttons.pack(fill="x", pady=18)
        ttk.Button(buttons, text="開始", command=self.start_server).pack(side="left")
        ttk.Button(buttons, text="ブラウザで開く", command=self.open_browser).pack(side="left", padx=8)
        ttk.Button(buttons, text="停止", command=self.stop_server).pack(side="left")
        ttk.Separator(frame).pack(fill="x", pady=8)

        remote_row = ttk.Frame(frame); remote_row.pack(fill="x", pady=8)
        ttk.Label(remote_row, text="Tailscale: ").pack(side="left")
        ttk.Label(remote_row, textvariable=self.remote).pack(side="left")
        ttk.Button(remote_row, text="外部接続を有効化", command=self.enable_remote).pack(side="right")
        ttk.Button(remote_row, text="無効化", command=self.disable_remote).pack(side="right", padx=8)

        bottom = ttk.Frame(frame); bottom.pack(fill="x", pady=14)
        ttk.Button(bottom, text="バックアップ作成", command=self.backup).pack(side="left")
        ttk.Button(bottom, text="Tailscale再確認", command=self.refresh_remote).pack(side="left", padx=8)
        ttk.Button(bottom, text="状態再確認", command=self.refresh_local_status).pack(side="left")
        ttk.Label(frame, text=f"データ保存先: {DATA_ROOT}").pack(anchor="w", pady=(18, 0))

    def _save_config(self) -> None:
        value = load_config(CONFIG_PATH)
        value["videoRoot"] = self.video_root.get().strip()
        value["metadataPath"] = self.metadata_path.get().strip()
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
        if self.server is not None:
            messagebox.showinfo(APP_NAME, "メタデータ取込前にライブラリを停止してください。")
            return
        source = Path(self.metadata_path.get()).expanduser()
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

    def start_server(self) -> None:
        if self.server is not None:
            return
        root = Path(self.video_root.get()).expanduser()
        if not root.is_dir():
            messagebox.showerror(APP_NAME, "動画フォルダーが見つかりません。")
            return
        try:
            works, videos = database_counts()
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"DBを確認できませんでした。\n{exc}")
            return
        if works == 0 or videos == 0:
            messagebox.showerror(APP_NAME, "先に監査済み video_library.json を取り込んでください。")
            return
        self._save_config()
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        restore = apply_pending_restore(DATA_ROOT)
        if restore and restore.get("state") == "error":
            messagebox.showwarning(APP_NAME, f"予約された復元に失敗しました。\n{restore.get('error', '')}")
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
            messagebox.showerror(APP_NAME, f"サーバーを開始できませんでした。\n{exc}")
            return
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        url = f"http://127.0.0.1:{self.server.server_port}/"
        atomic_write_json(RUNTIME_PATH, {"state": "running", "port": self.server.server_port, "url": url, "videoRoot": str(root)})
        self.status.set(f"実行中  {url}")
        self.open_browser()

    def open_browser(self) -> None:
        if self.server is None:
            self.start_server(); return
        base = f"http://127.0.0.1:{self.server.server_port}/"
        try:
            webbrowser.open(request_local_owner_browser_url(base, self.control_secret))
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"オーナーとしてブラウザを開けませんでした。\n{exc}")

    def stop_server(self) -> None:
        if self.server is not None:
            self.server.shutdown(); self.server.server_close(); self.server = None
        self.status.set("停止中")
        atomic_write_json(RUNTIME_PATH, {"state": "stopped"})

    def refresh_remote(self) -> None:
        status = get_remote_status()
        if not status.installed: self.remote.set("Tailscale未インストール")
        elif not status.logged_in: self.remote.set("未ログイン")
        elif status.serve_active: self.remote.set(f"有効  {status.serve_url}")
        else: self.remote.set("ログイン済み / Serve無効")

    def enable_remote(self) -> None:
        if self.server is None:
            messagebox.showinfo(APP_NAME, "先に動画ライブラリを開始してください。"); return
        ok, url, message = enable_remote_access(self.server.server_port); self.refresh_remote()
        messagebox.showinfo(APP_NAME, f"{message}\n{url}") if ok else messagebox.showerror(APP_NAME, message)

    def disable_remote(self) -> None:
        result = disable_remote_access(); self.refresh_remote()
        if result.returncode != 0: messagebox.showerror(APP_NAME, result.output)

    def backup(self) -> None:
        try:
            item = create_manual_backup(database_path=DATABASE_PATH, backup_dir=DATA_ROOT / "Backups")
            messagebox.showinfo(APP_NAME, f"バックアップを作成しました。\n{item['name']}")
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def close(self) -> None:
        self.stop_server(); self.destroy()


def main() -> int:
    VideoLibraryLauncher().mainloop(); return 0


if __name__ == "__main__":
    raise SystemExit(main())
