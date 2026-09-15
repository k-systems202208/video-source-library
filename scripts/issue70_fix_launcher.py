from __future__ import annotations

import re
from pathlib import Path

path = Path("windows-installer/src/launcher.py")
text = path.read_text(encoding="utf-8")
new_code = r'''    def _playback_audit_succeeded(self, report: dict[str, Any]) -> None:
        self.audit_thread = None
        summary = report.get("summary") or {}
        total = int(summary.get("total") or 0)
        playable_total = int(summary.get("playableVideoTotal") or 0)
        direct = int(summary.get("direct") or 0)
        transcode = int(summary.get("transcode") or 0)
        application_no_route = int(summary.get("applicationNoRoute") or 0)
        source_errors = int(summary.get("sourceDataErrors") or 0)
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
        self._append_log(f"元データ異常CSV: {report.get('sourceErrorsCsvReport', '')}")
        self._set_busy(False)
        message = (
            f"全件再生監査が完了しました。\n\n"
            f"登録: {total:,}件\n"
            f"実動画: {playable_total:,}件\n"
            f"DIRECT: {direct:,}件\n"
            f"互換変換: {transcode:,}件\n"
            f"アプリ再生不可: {application_no_route:,}件\n"
            f"元データ異常: {source_errors:,}件\n\n"
            f"レポート: {PLAYBACK_AUDIT_OUTPUT_PATH}"
        )
        if application_no_route:
            messagebox.showwarning(APP_NAME, message + "\n\nアプリ側の再生互換性に未解決項目があります。")
        elif source_errors:
            messagebox.showwarning(
                APP_NAME,
                message
                + "\n\n実動画の再生互換性は合格です。"
                + "\n元データ異常は専用CSVを確認し、元ファイルを差し替えてください。",
            )
        else:
            messagebox.showinfo(APP_NAME, message + "\n\nv1.0再生受入条件を満たしています。")
'''
pattern = r"^    def _playback_audit_succeeded\b.*?(?=^    def _playback_audit_failed\b)"
updated, count = re.subn(pattern, new_code.rstrip() + "\n\n", text, count=1, flags=re.MULTILINE | re.DOTALL)
if count != 1:
    raise SystemExit("_playback_audit_succeeded block not found")
path.write_text(updated, encoding="utf-8")

for cleanup in [Path(".github/workflows/issue-70-fix-launcher.yml"), Path("scripts/issue70_fix_launcher.py")]:
    if cleanup.exists():
        cleanup.unlink()
