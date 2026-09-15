from pathlib import Path

# Version
Path("windows-installer/src/app_version.py").write_text('APP_VERSION = "1.0.0"\n', encoding="utf-8")

p = Path("windows-installer/installer/VideoLibrary.iss")
text = p.read_text(encoding="utf-8")
if '0.9.7' not in text:
    raise SystemExit("installer version 0.9.7 not found")
p.write_text(text.replace('0.9.7', '1.0.0'), encoding="utf-8")

p = Path("tests/test_release_consistency.py")
text = p.read_text(encoding="utf-8")
if 'self.assertEqual(APP_VERSION, "0.9.7")' not in text:
    raise SystemExit("release consistency version anchor not found")
text = text.replace('self.assertEqual(APP_VERSION, "0.9.7")', 'self.assertEqual(APP_VERSION, "1.0.0")', 1)
p.write_text(text, encoding="utf-8")

# README release section
readme = Path("README.md")
text = readme.read_text(encoding="utf-8")
anchor = "対象動画拡張子: `.mkv`, `.mp4`, `.avi`, `.webm`, `.mpg`, `.flv`, `.m4v`, `.mov`, `.wmv`"
section = '''### 1.0.0: 正式版\n- 実ライブラリ4,869登録のうち、実動画4,845件で `applicationNoRoute = 0` を実機監査で確認\n- DIRECT 1,826件 / 互換変換 3,019件で、実動画4,845件すべてに再生経路を確保\n- probe / decode / missing / path escape のアプリ側異常はすべて0\n- 元データ異常24件は `.mkv` / `.mp4` 名だが実体がASS/SRT字幕データであり、アプリ不具合と分離\n- 0.9.7実機監査で24件すべて `repairCandidateCount = 0` を確認し、別エピソードの誤候補を解消\n- Tailscale Serve / PWA / 外部字幕 / 日本語音声優先 / FFmpeg互換変換 / PlaybackCache / Backup / 全件監査を正式版の基準として固定\n- 元動画・字幕・SQLite利用者状態を自動変更しない方針を維持\n\n'''
if "### 1.0.0: 正式版" not in text:
    if anchor not in text:
        raise SystemExit("README anchor not found")
    text = text.replace(anchor, section + anchor, 1)
readme.write_text(text, encoding="utf-8")

# Release note
Path("docs/39-1.0.0-release.md").write_text('''# 1.0.0 正式版リリースノート\n\n## 概要\n0.7系から0.9系で実装・検証してきた自宅動画ライブラリのWindows / Web / PWA / Tailscale運用を、1.0.0として固定する。\n\n## 実機受入結果\n2026-09-15の実ライブラリ全件監査結果を正式版の受入証跡とする。\n\n- 登録: 4,869件\n- 実動画: 4,845件\n- DIRECT: 1,826件\n- TRANSCODE: 3,019件\n- applicationNoRoute: 0件\n- probeErrors: 0件\n- decodeErrors: 0件\n- missing: 0件\n- pathEscapes: 0件\n- 元データ異常: 24件\n\n実動画4,845件はすべてDIRECTまたはTRANSCODEの再生経路を持つ。\n\n## 既知の元データ異常24件\n24件は動画拡張子 `.mkv` / `.mp4` で登録されているが、ffprobe上の実体がASS 17件 / SRT 7件の字幕データで、映像ストリームを持たない。これはアプリ再生経路の不具合とは分離して扱う。\n\n0.9.7の実機監査では24件すべて `repairCandidateCount = 0` で、同一フォルダー内に同一エピソードの置換可能な実動画候補は検出されなかった。元ファイルの再入手またはバックアップからの復旧が必要であり、アプリは元ファイルを自動変更しない。\n\n## 1.0.0で固定する主要機能\n- 作品440件 / 動画4,869件のSQLite索引\n- Windowsランチャーとユーザー権限インストーラー\n- HTTP Range動画配信\n- Tailscale Serveによる外部アクセス\n- PWA\n- 視聴状態 / 続きから見る / 履歴 / お気に入り\n- 外部SRT / VTT / ASS / SSA字幕のWebVTT再生\n- 複数音声の日本語優先\n- ブラウザ非互換動画のH.264 + AAC変換\n- PlaybackCache 20GB上限 / LRU整理 / 全削除\n- バックアップ / 復元\n- 全件再生監査と元データ異常レポート\n\n## 1.1系へ送る機能\n1.0.0では再生基盤を固定し、TMDb連携、ポスター、監督／演出、出演者／声優、人物別作品一覧、レトロ映画館UIは1.1系で実装する。\n''', encoding="utf-8")

# Release acceptance regression test
Path("tests/test_release_v100.py").write_text('''from pathlib import Path\nimport sys\nimport unittest\n\nROOT = Path(__file__).resolve().parents[1]\nSRC = ROOT / "windows-installer" / "src"\nsys.path.insert(0, str(SRC))\n\nfrom app_version import APP_VERSION\n\n\nclass ReleaseV100Tests(unittest.TestCase):\n    def test_release_version_and_docs_are_fixed(self):\n        self.assertEqual(APP_VERSION, "1.0.0")\n        readme = (ROOT / "README.md").read_text(encoding="utf-8")\n        notes = (ROOT / "docs" / "39-1.0.0-release.md").read_text(encoding="utf-8")\n        self.assertIn("### 1.0.0: 正式版", readme)\n        self.assertIn("実動画4,845件", readme)\n        self.assertIn("applicationNoRoute = 0", readme)\n        self.assertIn("元データ異常24件", readme)\n        self.assertIn("DIRECT: 1,826件", notes)\n        self.assertIn("TRANSCODE: 3,019件", notes)\n        self.assertIn("repairCandidateCount = 0", notes)\n\n    def test_installer_is_1_0_0(self):\n        installer = (ROOT / "windows-installer" / "installer" / "VideoLibrary.iss").read_text(encoding="utf-8")\n        self.assertIn('#define MyAppVersion "1.0.0"', installer)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''', encoding="utf-8")
