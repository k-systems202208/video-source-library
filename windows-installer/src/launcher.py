from __future__ import annotations

import json
import secrets
import threading
import tkinter as tk
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app_config import load_config, save_config
from backup_restore import apply_pending_restore, create_manual_backup
from paths import CONFIG_PATH, DATABASE_PATH, DATA_ROOT, RUNTIME_PATH
from remote_access import disable_remote_access, enable_remote_access, get_remote_status
from server import create_server

APP_NAME = "自宅動画ライブラリ"
APP_VERSION = "0.5.0"
DEFAULT_PORT = 8765
CONTROL_HEADER = "X-Video-Library-Control-Secret"


def atomic_write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def request_local_owner_browser_url(page_url: str, control_secret: str) -> str:
    token = secrets.token_urlsafe(32)
    endpoint = urllib.parse.urljoin(page_url, "/api/local-auth/token")
    payload = json.dumps({"token": token, "expiresInSeconds": 60}).encode("utf-8")
    req = urllib.request.Request(endpoint, data=payload, method="POST", headers={"Content-Type": "application/json", CONTROL_HEADER: control_secret})
    with urllib.request.urlopen(req, timeout=3.0) as response:
        if response.status != 201:
            raise RuntimeError("owner token registration failed")
    return urllib.parse.urljoin(page_url, "/api/local-auth/exchange?") + urllib.parse.urlencode({"token": token})


class VideoLibraryLauncher(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("720x390")
        self.minsize(650, 360)
        self.server = None
        self.server_thread: threading.Thread | None = None
        self.control_secret = ""
        config = load_config(CONFIG_PATH)
        self.video_root = tk.StringVar(value=str(config.get("videoRoot") or ""))
        self.status = tk.StringVar(value="停止中")
        self.remote = tk.StringVar(value="未確認")
        self._build()
        self.after(300, self.refresh_remote)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=18); frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=APP_NAME, font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(frame, textvariable=self.status).pack(anchor="w", pady=(2, 16))
        row = ttk.Frame(frame); row.pack(fill="x")
        ttk.Label(row, text="動画フォルダー").pack(side="left")
        ttk.Entry(row, textvariable=self.video_root).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row, text="参照", command=self.choose_root).pack(side="right")
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
        ttk.Label(frame, text=f"データ保存先: {DATA_ROOT}").pack(anchor="w", pady=(18, 0))

    def choose_root(self) -> None:
        selected = filedialog.askdirectory(title="動画フォルダーを選択")
        if selected:
            self.video_root.set(selected)

    def start_server(self) -> None:
        if self.server is not None:
            return
        root = Path(self.video_root.get()).expanduser()
        if not root.is_dir():
            messagebox.showerror(APP_NAME, "動画フォルダーが見つかりません。")
            return
        save_config({"videoRoot": str(root)}, CONFIG_PATH)
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        restore = apply_pending_restore(DATA_ROOT)
        if restore and restore.get("state") == "error":
            messagebox.showwarning(APP_NAME, f"予約された復元に失敗しました。\n{restore.get('error', '')}")
        self.control_secret = secrets.token_urlsafe(48)
        try:
            self.server = create_server(DATABASE_PATH, host="127.0.0.1", port=DEFAULT_PORT, video_root=root,
                                        owner_control_secret=self.control_secret, data_root=DATA_ROOT)
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
