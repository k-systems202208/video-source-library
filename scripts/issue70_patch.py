from __future__ import annotations

import re
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected text not found: {path}: {old[:80]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_function(path: str, name: str, next_name: str, new_code: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    pattern = rf"^def {re.escape(name)}\b.*?(?=^def {re.escape(next_name)}\b)"
    updated, count = re.subn(pattern, new_code.rstrip() + "\n\n\n", text, count=1, flags=re.MULTILINE | re.DOTALL)
    if count != 1:
        raise SystemExit(f"function block not found: {path}: {name}")
    p.write_text(updated, encoding="utf-8")


def replace_method(path: str, name: str, next_name: str, new_code: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    pattern = rf"^    def {re.escape(name)}\b.*?(?=^    def {re.escape(next_name)}\b)"
    updated, count = re.subn(pattern, new_code.rstrip() + "\n\n", text, count=1, flags=re.MULTILINE | re.DOTALL)
    if count != 1:
        raise SystemExit(f"method block not found: {path}: {name}")
    p.write_text(updated, encoding="utf-8")


AUDIT = "windows-installer/src/playback_audit.py"

summarize_code = '''def summarize_audit(items: list[dict[str, Any]]) -> dict[str, Any]:
    extensions = Counter(str(item.get("extension") or "").lower() for item in items)
    containers = Counter(str(item.get("containerFormat") or "") for item in items if item.get("containerFormat"))
    video_codecs = Counter(str(item.get("videoCodec") or "") for item in items if item.get("videoCodec"))
    audio_codecs: Counter[str] = Counter()
    for item in items:
        for codec in item.get("audioCodecs") or []:
            if codec:
                audio_codecs[str(codec)] += 1

    source_data_error_reasons = {
        "SUBTITLE_CONTENT_REGISTERED_AS_VIDEO",
        "MISSING_FILE",
        "NO_VIDEO_STREAM",
        "PATH_ESCAPE",
    }
    direct = sum(1 for item in items if item.get("route") == "DIRECT")
    transcode = sum(1 for item in items if item.get("route") == "TRANSCODE")
    raw_no_route = sum(1 for item in items if item.get("route") == "NO_ROUTE")
    source_data_errors = sum(1 for item in items if item.get("reason") in source_data_error_reasons)
    application_no_route = sum(
        1
        for item in items
        if item.get("route") == "NO_ROUTE" and item.get("reason") not in source_data_error_reasons
    )

    return {
        "total": len(items),
        "playableVideoTotal": len(items) - source_data_errors,
        "direct": direct,
        "transcode": transcode,
        "noRoute": raw_no_route,
        "applicationNoRoute": application_no_route,
        "sourceDataErrors": source_data_errors,
        "probeErrors": sum(1 for item in items if item.get("reason") == "PROBE_ERROR"),
        "decodeErrors": sum(1 for item in items if item.get("reason") == "DECODE_ERROR"),
        "missing": sum(1 for item in items if item.get("reason") == "MISSING_FILE"),
        "pathEscapes": sum(1 for item in items if item.get("reason") == "PATH_ESCAPE"),
        "noVideoStream": sum(1 for item in items if item.get("reason") == "NO_VIDEO_STREAM"),
        "subtitleContentRegisteredAsVideo": sum(
            1 for item in items if item.get("reason") == "SUBTITLE_CONTENT_REGISTERED_AS_VIDEO"
        ),
        "withJapaneseAudio": sum(1 for item in items if item.get("hasJapaneseAudio")),
        "multiAudio": sum(1 for item in items if int(item.get("audioTrackCount") or 0) > 1),
        "withExternalSubtitles": sum(1 for item in items if int(item.get("externalSubtitleCount") or 0) > 0),
        "externalSubtitleFiles": sum(int(item.get("externalSubtitleCount") or 0) for item in items),
        "withEmbeddedSubtitles": sum(1 for item in items if int(item.get("embeddedSubtitleCount") or 0) > 0),
        "embeddedSubtitleStreams": sum(int(item.get("embeddedSubtitleCount") or 0) for item in items),
        "extensions": dict(sorted(extensions.items())),
        "containers": dict(sorted(containers.items())),
        "videoCodecs": dict(sorted(video_codecs.items())),
        "audioCodecs": dict(sorted(audio_codecs.items())),
    }
'''
replace_function(AUDIT, "summarize_audit", "write_audit_reports", summarize_code)

write_code = '''def write_audit_reports(
    output_dir: Path,
    report: dict[str, Any],
    *,
    stamp: str | None = None,
) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = stamp or datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    json_path = output_dir / f"playback-audit-{suffix}.json"
    csv_path = output_dir / f"playback-audit-{suffix}.csv"
    source_errors_path = output_dir / f"playback-audit-source-errors-{suffix}.csv"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    fields = [
        "videoId", "externalFileNo", "title", "episode", "relativePath", "extension",
        "containerFormat", "videoCodec", "videoProfile", "pixelFormat", "audioCodecs", "audioLanguages", "audioTrackCount",
        "hasJapaneseAudio", "preferredAudioIndex", "preferredAudioCodec", "preferredAudioLanguage",
        "externalSubtitleCount", "embeddedSubtitleCount", "sampleDecode", "route", "reason", "error",
    ]

    def csv_row(item: dict[str, Any]) -> dict[str, Any]:
        row = dict(item)
        row["audioCodecs"] = ";".join(row.get("audioCodecs") or [])
        row["audioLanguages"] = ";".join(row.get("audioLanguages") or [])
        return row

    items = list(report.get("items") or [])
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for item in items:
            writer.writerow(csv_row(item))

    source_data_error_reasons = {
        "SUBTITLE_CONTENT_REGISTERED_AS_VIDEO",
        "MISSING_FILE",
        "NO_VIDEO_STREAM",
        "PATH_ESCAPE",
    }
    with source_errors_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for item in items:
            if item.get("reason") in source_data_error_reasons:
                writer.writerow(csv_row(item))
    return json_path, csv_path, source_errors_path
'''
replace_function(AUDIT, "write_audit_reports", "audit_real_library", write_code)

p = Path(AUDIT)
text = p.read_text(encoding="utf-8")
old = '''                    "direct": current_summary["direct"],
                    "transcode": current_summary["transcode"],
                    "noRoute": current_summary["noRoute"],
'''
new = '''                    "direct": current_summary["direct"],
                    "transcode": current_summary["transcode"],
                    "noRoute": current_summary["noRoute"],
                    "applicationNoRoute": current_summary["applicationNoRoute"],
                    "sourceDataErrors": current_summary["sourceDataErrors"],
'''
if old not in text:
    raise SystemExit("audit progress dictionary block not found")
text = text.replace(old, new, 1)
old = '''    json_path, csv_path = write_audit_reports(Path(output_dir), report)
    report["jsonReport"] = str(json_path)
    report["csvReport"] = str(csv_path)
    return report
'''
new = '''    json_path, csv_path, source_errors_path = write_audit_reports(Path(output_dir), report)
    report["jsonReport"] = str(json_path)
    report["csvReport"] = str(csv_path)
    report["sourceErrorsCsvReport"] = str(source_errors_path)
    return report
'''
if old not in text:
    raise SystemExit("audit report output block not found")
text = text.replace(old, new, 1)
p.write_text(text, encoding="utf-8")

LAUNCHER = "windows-installer/src/launcher.py"
replace_once(
    LAUNCHER,
    'self.scan_counts.set("DIRECT 0 / 互換変換 0 / 再生経路なし 0")',
    'self.scan_counts.set("DIRECT 0 / 互換変換 0 / アプリ再生不可 0 / 元データ異常 0")',
)

apply_code = '''    def _apply_audit_progress(self, progress: dict[str, Any]) -> None:
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
'''
replace_method(LAUNCHER, "_apply_audit_progress", "_playback_audit_succeeded", apply_code)

success_code = '''    def _playback_audit_succeeded(self, report: dict[str, Any]) -> None:
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
replace_method(LAUNCHER, "_playback_audit_succeeded", "_playback_audit_failed", success_code)

replace_once("windows-installer/src/app_version.py", 'APP_VERSION = "0.9.4"\n', 'APP_VERSION = "0.9.5"\n')
replace_once("windows-installer/installer/VideoLibrary.iss", '#define MyAppVersion "0.9.4"', '#define MyAppVersion "0.9.5"')
replace_once("tests/test_release_consistency.py", 'self.assertEqual(APP_VERSION, "0.9.4")', 'self.assertEqual(APP_VERSION, "0.9.5")')

Path("tests/test_playback_audit_v095.py").write_text(r'''from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from playback_audit import summarize_audit, write_audit_reports


class PlaybackAuditV095Tests(unittest.TestCase):
    def test_summary_separates_application_route_and_source_data_errors(self) -> None:
        summary = summarize_audit([
            {"extension": "mkv", "route": "NO_ROUTE", "reason": "SUBTITLE_CONTENT_REGISTERED_AS_VIDEO", "audioCodecs": []},
            {"extension": "mp4", "route": "DIRECT", "reason": "", "videoCodec": "h264", "audioCodecs": ["aac"]},
            {"extension": "avi", "route": "TRANSCODE", "reason": "BROWSER_INCOMPATIBLE_OR_TRACK_SELECTION", "videoCodec": "mpeg4", "audioCodecs": ["mp3"]},
        ])
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["playableVideoTotal"], 2)
        self.assertEqual(summary["noRoute"], 1)
        self.assertEqual(summary["applicationNoRoute"], 0)
        self.assertEqual(summary["sourceDataErrors"], 1)
        self.assertEqual(summary["subtitleContentRegisteredAsVideo"], 1)

    def test_real_playback_failure_stays_application_no_route(self) -> None:
        summary = summarize_audit([
            {"extension": "mkv", "route": "NO_ROUTE", "reason": "DECODE_ERROR", "videoCodec": "hevc", "audioCodecs": ["aac"]}
        ])
        self.assertEqual(summary["playableVideoTotal"], 1)
        self.assertEqual(summary["applicationNoRoute"], 1)
        self.assertEqual(summary["sourceDataErrors"], 0)

    def test_source_error_csv_contains_only_source_data_errors(self) -> None:
        bad = {
            "videoId": 1, "externalFileNo": 10, "title": "bad", "episode": "ep1", "relativePath": "bad.mkv", "extension": "mkv",
            "containerFormat": "ass", "videoCodec": "", "videoProfile": "", "pixelFormat": "", "audioCodecs": [], "audioLanguages": [],
            "audioTrackCount": 0, "hasJapaneseAudio": False, "preferredAudioIndex": None, "preferredAudioCodec": "", "preferredAudioLanguage": "",
            "externalSubtitleCount": 0, "embeddedSubtitleCount": 1, "sampleDecode": "NOT_RUN", "route": "NO_ROUTE",
            "reason": "SUBTITLE_CONTENT_REGISTERED_AS_VIDEO", "error": "",
        }
        good = dict(bad)
        good.update({"videoId": 2, "externalFileNo": 11, "title": "good", "relativePath": "good.mp4", "extension": "mp4",
                     "containerFormat": "mov,mp4,m4a,3gp,3g2,mj2", "videoCodec": "h264", "audioCodecs": ["aac"],
                     "audioLanguages": ["jpn"], "audioTrackCount": 1, "sampleDecode": "PASS", "route": "DIRECT", "reason": ""})
        report = {"summary": {}, "items": [bad, good]}
        with tempfile.TemporaryDirectory() as temp:
            _, _, source_errors = write_audit_reports(Path(temp), report, stamp="test")
            with source_errors.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "bad")
        self.assertEqual(rows[0]["reason"], "SUBTITLE_CONTENT_REGISTERED_AS_VIDEO")

    def test_launcher_displays_application_and_source_results_separately(self) -> None:
        text = (SRC / "launcher.py").read_text(encoding="utf-8")
        self.assertIn("アプリ再生不可", text)
        self.assertIn("元データ異常", text)
        self.assertIn("sourceErrorsCsvReport", text)
        self.assertIn("実動画の再生互換性は合格です", text)


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")

Path("docs/36-0.9.5-audit-source-data-separation.md").write_text('''# 0.9.5 再生互換性と元データ異常の監査分離

## 背景

0.9.4の実ライブラリ4,869件監査では、実動画4,845件はすべてDIRECTまたは互換変換でサンプルデコードに成功した。一方24件は動画拡張子を持ちながら、ffprobe上の実体がASS/SRT字幕データだった。

## 変更内容

- JSON summaryに `playableVideoTotal` を追加する。
- `noRoute` は従来どおり生のNO_ROUTE件数として保持する。
- `applicationNoRoute` で、元データ異常を除いたアプリ側の再生不可件数を示す。
- `sourceDataErrors` で、動画として登録されているが元データ修復が必要な件数を示す。
- `playback-audit-source-errors-*.csv` を追加し、元データ異常だけをUTF-8 BOM付きCSVで出力する。
- Windowsランチャーは `DIRECT / 互換変換 / アプリ再生不可 / 元データ異常` を別々に表示する。
- アプリ再生不可0件・元データ異常ありの場合は「実動画の再生互換性は合格、元データは修復待ち」と表示する。

## 安全性

監査は読み取り専用である。動画・字幕・SQLite・PlaybackCacheを変更しない。元データ異常CSVにも絶対パスは出さず、既存監査と同じ相対パスだけを記録する。

## v1.0前の判定

- `applicationNoRoute = 0`: アプリ側の再生互換性は合格。
- `sourceDataErrors > 0`: 元ライブラリの修復待ち。アプリ不具合とは分けて扱う。
- `sourceDataErrors = 0` まで解消すれば、ライブラリ全体の再生受入を完了できる。
''', encoding="utf-8")

readme = Path("README.md")
text = readme.read_text(encoding="utf-8")
section = '''### 0.9.4〜0.9.5: 全件再生監査の精度向上と元データ異常分離
- 0.9.4: DB拡張子の正規化、DIRECT decode-only、AAC 2ch正規化、ASS/SRT実体の誤登録分類を追加
- 0.9.5: 実動画の再生互換性と元ライブラリのデータ異常を別集計に分離
- `applicationNoRoute` はアプリ側の未解決再生経路だけを示す
- `sourceDataErrors` は元ファイル差し替えが必要な項目を示す
- 元データ異常だけを `playback-audit-source-errors-*.csv` に出力
- 元動画・字幕・SQLite・PlaybackCacheは監査で変更しない

'''
if section not in text:
    marker = "対象動画拡張子:"
    if marker not in text:
        raise SystemExit("README insertion marker not found")
    readme.write_text(text.replace(marker, section + marker, 1), encoding="utf-8")

for cleanup in [Path(".github/workflows/issue-70-apply.yml"), Path("scripts/issue70_patch.py")]:
    if cleanup.exists():
        cleanup.unlink()
