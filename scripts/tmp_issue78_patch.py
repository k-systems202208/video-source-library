from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"marker not found: {path}: {old!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


launcher = "windows-installer/src/launcher.py"
replace_once(
    launcher,
    "from server import create_server\n",
    "from server import create_server\nfrom tmdb_matcher import audit_tmdb_library\n",
)
replace_once(
    launcher,
    'PLAYBACK_AUDIT_OUTPUT_PATH = DATA_ROOT / "diagnostics"\n',
    'PLAYBACK_AUDIT_OUTPUT_PATH = DATA_ROOT / "diagnostics"\nTMDB_MATCH_OUTPUT_PATH = DATA_ROOT / "diagnostics"\n',
)
replace_once(
    launcher,
    "        self.audit_thread: threading.Thread | None = None\n        self.audit_started_monotonic: float | None = None\n",
    "        self.audit_thread: threading.Thread | None = None\n        self.tmdb_thread: threading.Thread | None = None\n        self.audit_started_monotonic: float | None = None\n        self.tmdb_started_monotonic: float | None = None\n",
)
replace_once(
    launcher,
    '        ttk.Button(operations_frame, text="TMDb設定", command=self.open_tmdb_settings).pack(side="left", padx=(0, 8))\n',
    '        self.tmdb_settings_button = ttk.Button(operations_frame, text="TMDb設定", command=self.open_tmdb_settings)\n        self.tmdb_settings_button.pack(side="left", padx=(0, 8))\n',
)
replace_once(launcher, '        dialog.geometry("520x245")\n', '        dialog.geometry("520x300")\n')
replace_once(
    launcher,
    '        ttk.Button(buttons, text="保存", command=save_local).pack(side="left")\n        ttk.Button(buttons, text="ローカル設定を削除", command=clear_local).pack(side="left", padx=8)\n        ttk.Button(buttons, text="閉じる", command=dialog.destroy).pack(side="right")\n',
    '        ttk.Button(buttons, text="保存", command=save_local).pack(side="left")\n        ttk.Button(buttons, text="ローカル設定を削除", command=clear_local).pack(side="left", padx=8)\n        ttk.Button(buttons, text="閉じる", command=dialog.destroy).pack(side="right")\n\n        match_frame = ttk.Frame(frame)\n        match_frame.pack(fill="x", pady=(14, 0))\n        ttk.Label(\n            match_frame,\n            text="作品名・年・種別を使って候補を照合し、低信頼／複数候補は自動確定しません。",\n            font=SMALL_FONT,\n            wraplength=330,\n        ).pack(side="left", fill="x", expand=True)\n\n        def start_matching() -> None:\n            dialog.destroy()\n            self.start_tmdb_match_audit()\n\n        ttk.Button(match_frame, text="TMDb作品照合", command=start_matching).pack(side="right", padx=(10, 0))\n',
)

insert_marker = "\n\n    def refresh_cache_status(self) -> None:\n"
methods = r'''

    def start_tmdb_match_audit(self) -> None:
        if self.server is not None or self.scan_thread is not None or self.audit_thread is not None or self.tmdb_thread is not None:
            messagebox.showinfo(APP_NAME, "TMDb作品照合の前にライブラリを停止してください。")
            return
        if not DATABASE_PATH.is_file():
            messagebox.showerror(APP_NAME, "ライブラリDBが見つかりません。")
            return
        token = configured_tmdb_token(config_path=CONFIG_PATH)
        if not token:
            messagebox.showinfo(APP_NAME, "先に「TMDb設定」でAPI Read Access Tokenを設定してください。")
            return
        works, _ = database_counts()
        if not messagebox.askyesno(
            APP_NAME,
            f"登録済み {works:,} 作品をTMDbと照合します。\n"
            "作品名・年・種別で判定し、低信頼や複数候補は自動確定しません。\n"
            "ネットワーク状況により時間がかかる場合があります。開始しますか？",
        ):
            return

        self._set_busy(True)
        self.tmdb_started_monotonic = time.monotonic()
        self.status.set("TMDb作品照合を実行中です")
        self.scan_status.set("TMDb照合中 — 作品候補を確認しています")
        self.scan_counts.set("MATCHED 0 / 要確認 0 / 候補 0 / 未一致 0 / エラー 0")
        self.scan_current.set("現在処理中: —")
        self.scan_elapsed.set("経過: 0:00")
        self.scan_progress.configure(mode="determinate", maximum=max(1, works))
        self.scan_progress["value"] = 0
        self._append_log("=" * 72)
        self._append_log("TMDb作品照合を開始します。低信頼・複数候補は自動確定しません。")
        self.tmdb_thread = threading.Thread(
            target=self._tmdb_match_worker,
            args=(token,),
            daemon=True,
            name="VideoLibraryTmdbMatchAudit",
        )
        self.tmdb_thread.start()

    def _tmdb_match_worker(self, token: str) -> None:
        try:
            report = audit_tmdb_library(
                DATABASE_PATH,
                token,
                TMDB_MATCH_OUTPUT_PATH,
                progress_callback=self._tmdb_progress_from_worker,
            )
        except Exception as exc:
            self.after(0, lambda e=exc: self._tmdb_match_failed(e))
            return
        self.after(0, lambda r=report: self._tmdb_match_succeeded(r))

    def _tmdb_progress_from_worker(self, progress: dict[str, Any]) -> None:
        snapshot = dict(progress)
        self.after(0, lambda p=snapshot: self._apply_tmdb_progress(p))

    def _apply_tmdb_progress(self, progress: dict[str, Any]) -> None:
        current = int(progress.get("current") or 0)
        total = int(progress.get("total") or 0)
        matched = int(progress.get("matched") or 0)
        review = int(progress.get("review") or 0)
        candidate = int(progress.get("candidate") or 0)
        unmatched = int(progress.get("unmatched") or 0)
        errors = int(progress.get("errors") or 0)
        self.scan_status.set(f"TMDb照合中 — {current:,} / {total:,}")
        self.scan_counts.set(
            f"MATCHED {matched:,} / 要確認 {review:,} / 候補 {candidate:,} / 未一致 {unmatched:,} / エラー {errors:,}"
        )
        self.scan_current.set(f"現在処理中: {progress.get('currentItem') or '—'}")
        self.scan_progress.configure(mode="determinate", maximum=max(1, total))
        self.scan_progress["value"] = min(current, total)
        if self.tmdb_started_monotonic is not None:
            seconds = max(0, int(time.monotonic() - self.tmdb_started_monotonic))
            self.scan_elapsed.set(f"経過: {seconds // 60}:{seconds % 60:02d}")
        if current and (current % 25 == 0 or current == total):
            self._append_log(
                f"TMDb {current:,}/{total:,}: MATCHED {matched:,} / 要確認 {review:,} / "
                f"候補 {candidate:,} / 未一致 {unmatched:,} / エラー {errors:,}"
            )

    def _tmdb_match_succeeded(self, report: dict[str, Any]) -> None:
        self.tmdb_thread = None
        summary = report.get("summary") or {}
        total = int(summary.get("total") or 0)
        matched = int(summary.get("matched") or 0)
        review = int(summary.get("review") or 0)
        candidate = int(summary.get("candidate") or 0)
        unmatched = int(summary.get("unmatched") or 0)
        errors = int(summary.get("errors") or 0)
        self.scan_progress.configure(mode="determinate", maximum=max(1, total))
        self.scan_progress["value"] = total
        self.scan_status.set("完了 — TMDb作品照合が完了しました")
        self.scan_counts.set(
            f"MATCHED {matched:,} / 要確認 {review:,} / 候補 {candidate:,} / 未一致 {unmatched:,} / エラー {errors:,}"
        )
        self.scan_current.set("現在処理中: 完了")
        self.status.set("TMDb作品照合が完了しました")
        self._append_log(f"JSON: {report.get('jsonReport', '')}")
        self._append_log(f"CSV : {report.get('csvReport', '')}")
        self._set_busy(False)
        message = (
            f"TMDb作品照合が完了しました。\n\n"
            f"登録: {total:,}作品\n"
            f"自動確定: {matched:,}件\n"
            f"要確認: {review:,}件\n"
            f"低信頼候補: {candidate:,}件\n"
            f"未一致: {unmatched:,}件\n"
            f"通信等エラー: {errors:,}件\n\n"
            f"レポート: {TMDB_MATCH_OUTPUT_PATH}"
        )
        if review or candidate or unmatched or errors:
            messagebox.showinfo(APP_NAME, message + "\n\n自動確定しなかった作品はCSVで確認できます。")
        else:
            messagebox.showinfo(APP_NAME, message)

    def _tmdb_match_failed(self, exc: Exception) -> None:
        self.tmdb_thread = None
        self.status.set("TMDb作品照合に失敗しました")
        self.scan_status.set("失敗 — TMDb作品照合を完了できませんでした")
        self._append_log(f"TMDB ERROR: {type(exc).__name__}: {exc}")
        self._set_busy(False)
        messagebox.showerror(APP_NAME, f"TMDb作品照合に失敗しました。\n{exc}")
'''
replace_once(launcher, insert_marker, methods + insert_marker)
replace_once(
    launcher,
    "        if self.server is not None or self.scan_thread is not None or self.audit_thread is not None:\n            messagebox.showinfo(APP_NAME, \"全件再生監査の前にライブラリを停止してください。\")\n",
    "        if self.server is not None or self.scan_thread is not None or self.audit_thread is not None or self.tmdb_thread is not None:\n            messagebox.showinfo(APP_NAME, \"全件再生監査の前にライブラリを停止してください。\")\n",
)
replace_once(
    launcher,
    "        self.audit_button.configure(state=state)\n",
    "        self.audit_button.configure(state=state)\n        self.tmdb_settings_button.configure(state=state)\n",
)

readme = "README.md"
replace_once(
    readme,
    "- 作品自動マッチング、人物ID、ポスター／背景画像、レトロ映画館UIは次段階で追加\n",
    "- 作品名・公開年・種別を使ったTMDb候補照合を追加し、高信頼かつ候補差が十分な場合だけ自動確定\n"
    "- 自動確定時はTMDb ID、media type、confidence、poster/backdrop参照、overviewをSQLiteへ保存\n"
    "- 低信頼・複数候補は `REVIEW` / `CANDIDATE` として残し、440作品向けJSON/CSV監査レポートを出力\n"
    "- 人物ID統合、画像のWeb UI表示、レトロ映画館UIは次段階で追加\n",
)
replace_once(
    readme,
    "- [1.1.0 TMDb連携基盤](docs/41-1.1.0-tmdb-foundation.md)\n",
    "- [1.1.0 TMDb連携基盤](docs/41-1.1.0-tmdb-foundation.md)\n"
    "- [1.1.0 TMDb作品マッチングと監査](docs/42-1.1.0-tmdb-matching.md)\n",
)
