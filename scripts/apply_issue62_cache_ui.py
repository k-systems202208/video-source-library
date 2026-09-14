from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {text.count(old)}")
    return text.replace(old, new, 1)


root = Path(__file__).resolve().parents[1]
launcher_path = root / "windows-installer" / "src" / "launcher.py"
launcher = launcher_path.read_text(encoding="utf-8")

launcher = replace_once(
    launcher,
    "from metadata_importer import import_file\n",
    "from metadata_importer import import_file\nfrom playback_cache import DEFAULT_CACHE_LIMIT_BYTES, clear_playback_cache, format_bytes, playback_cache_stats\n",
    "cache import",
)
launcher = replace_once(
    launcher,
    'METADATA_PATH = DATA_ROOT / "metadata" / "video_library.json"\n',
    'METADATA_PATH = DATA_ROOT / "metadata" / "video_library.json"\nPLAYBACK_CACHE_PATH = DATA_ROOT / "PlaybackCache"\n',
    "cache path",
)
launcher = replace_once(launcher, 'WINDOW_GEOMETRY = "780x690"', 'WINDOW_GEOMETRY = "780x760"', "geometry")
launcher = replace_once(launcher, 'WINDOW_MINSIZE = (700, 590)', 'WINDOW_MINSIZE = (700, 650)', "minsize")
launcher = replace_once(
    launcher,
    '        self.remote = tk.StringVar(value="状態を確認しています…")\n',
    '        self.remote = tk.StringVar(value="状態を確認しています…")\n        self.cache_status = tk.StringVar(value="再生キャッシュ: 確認中…")\n',
    "cache stringvar",
)

ui_anchor = '        ttk.Button(remote_buttons, text="Tailscale再確認", command=self.refresh_remote).pack(side="right")\n\n        ttk.Label(main, textvariable=self.status, font=STATUS_FONT).pack(anchor="w", pady=(0, 6))\n'
ui_replacement = '''        ttk.Button(remote_buttons, text="Tailscale再確認", command=self.refresh_remote).pack(side="right")

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

        ttk.Label(main, textvariable=self.status, font=STATUS_FONT).pack(anchor="w", pady=(0, 6))
'''
launcher = replace_once(launcher, ui_anchor, ui_replacement, "cache UI")

method_anchor = '    def open_data_folder(self) -> None:\n'
methods = '''    def refresh_cache_status(self) -> None:
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
            f"再生キャッシュ {format_bytes(stats.total_bytes)} を削除しますか？\\n元動画は削除されません。",
        ):
            return
        result = clear_playback_cache(PLAYBACK_CACHE_PATH)
        self.refresh_cache_status()
        if result.failed_files:
            messagebox.showwarning(
                APP_NAME,
                f"{result.removed_files}ファイルを削除しました。\\n{result.failed_files}ファイルは削除できませんでした。",
            )
        else:
            messagebox.showinfo(
                APP_NAME,
                f"再生キャッシュを削除しました。\\n{result.removed_files}ファイル / {format_bytes(result.removed_bytes)}",
            )

    def open_data_folder(self) -> None:
'''
launcher = replace_once(launcher, method_anchor, methods, "cache methods")

probe_line = '        self.probe_status.set(f"ffprobe: {\'利用可 - \' + str(ffprobe) if ffprobe else \'未検出（動画解析のみ省略）\'}")\n'
launcher = replace_once(
    launcher,
    probe_line,
    probe_line + '        self.refresh_cache_status()\n',
    "refresh cache status",
)
launcher_path.write_text(launcher, encoding="utf-8")

readme_path = root / "README.md"
readme = readme_path.read_text(encoding="utf-8")
readme_anchor = '- プレイヤーをモーダル化し、変換中の経過表示と再生準備失敗の明示エラーを追加\n\n対象動画拡張子:'
readme_replacement = '''- プレイヤーをモーダル化し、変換中の経過表示と再生準備失敗の明示エラーを追加

### 0.9.1: 再生キャッシュ容量管理
- WindowsランチャーにPlaybackCacheの現在容量・ファイル数・20GB上限を表示
- 20GBを超えた場合は最終利用時刻が古い変換キャッシュから自動削除
- キャッシュを再利用したときは最終利用時刻を更新し、最近使った動画を優先して保持
- ライブラリ停止中に「キャッシュをすべて削除」できる
- 手動削除・自動整理とも `%LOCALAPPDATA%\\VideoLibrary\\PlaybackCache` だけを対象とし、元動画・字幕・SQLite・メタデータは変更しない

対象動画拡張子:'''
readme = replace_once(readme, readme_anchor, readme_replacement, "README 0.9.1")
readme_path.write_text(readme, encoding="utf-8")
