# 自宅動画ライブラリ v1.1.0 基本設計

## 目的

PCに保存している映画・国内ドラマ・海外ドラマ・アニメ等を索引化し、Windows PC / ブラウザ / PWA / Tailscale経由で検索・閲覧・再生・視聴状態管理できる家庭向け動画ライブラリを構築する。

Web UIの現在の館名は **「関町北映画館」** とし、レトロ映画館をモチーフにした表示を採用する。

## 正本と補助情報

- 元動画・元字幕: ユーザー指定の動画フォルダーを正本とする。
- 作品メタデータ: ローカルの `video_library.json` を正本とする。
- お気に入り、視聴済み、再生位置、再生回数、利用者情報: SQLite `library.db` を正本とする。
- TMDb: 作品照合、overview、poster/backdrop、主な出演者／声優の人物ID・プロフィール画像を補助情報として利用する。
- TMDb情報が取得できない場合でも、ローカル作品メタデータと動画再生機能は維持する。

## 基本原則

- 元動画・元字幕を変更・削除・移動しない。
- ブラウザ互換再生用の変換は `PlaybackCache` に別ファイルとして生成し、元動画へ書き戻さない。
- TMDb照合は安全側とし、低信頼候補や構造が1対1でない作品を自動確定しない。
- 既に確定したTMDb作品リンクは、監査済みの例外を除き勝手に別作品へ付け替えない。
- 主な出演者／声優の顔写真は表示するが、監督／演出の顔写真は表示しない。
- 外部利用はTailscale Serveを正式経路とし、アプリHTTPサーバーはlocalhostへbindする。
- PWAはUIシェルのみキャッシュし、API・動画・字幕・TMDb画像・個人状態はService Workerへ保存しない。

## 技術構成

- Python 3.11 / 3.13
- SQLite（現行schema 7）
- HTML / CSS / JavaScript
- PWA / Service Worker
- Tailscale Serve
- Tkinter Windowsランチャー
- FFmpeg / ffprobe
- PyInstaller
- Inno Setup
- GitHub Actions / Playwright

Windows InstallerにはFFmpeg / ffprobeを同梱し、利用PCへ別途導入しなくても全登録動画の再生経路を確保する。

## 現在の主要機能

1. 監査済み `video_library.json` のSQLite取込
2. 動画フォルダーの安全な実ファイルスキャン
3. Range動画配信とFFmpeg互換再生
4. SRT / VTT / ASS / SSA外部字幕のブラウザ表示
5. 日本語音声優先
6. お気に入り、視聴済み、再生位置、履歴
7. PlaybackCache容量管理
8. スキャン診断・全件再生監査
9. Backup / 次回起動時Restore
10. TMDb作品照合、overview、poster/backdrop
11. 監督／演出・主な出演者／声優の人物名鑑
12. 主な出演者／声優のTMDbプロフィール画像
13. PC / Tablet / Smartphoneの映画館UI
14. Tailscale Serve / PWA

## TMDbの安全ルール

- 作品matcherは現行version 8。
- 高信頼かつ一意に確定できる作品のみ `MATCHED`。
- 集約作品やローカル/TMDb構造が一致しない作品は `REVIEW` / `UNMATCHED` を維持する。
- 人物同期は現行version 9。通常処理では主な出演者／声優のみを人物リンク対象とする。
- 人物監査は現行version 8。
- 監督／演出の人物名鑑はローカルクレジットから生成し、顔写真用TMDb人物同期は行わない。

## ローカルデータ

主な利用者データは `%LOCALAPPDATA%\VideoLibrary` 以下に保持する。

- `library.db`
- `config.json`
- `runtime.json`
- `metadata\video_library.json`
- `PlaybackCache\`
- `TMDbImages\`
- `diagnostics\`
- `Backups\`
- `Logs\`

アンインストール時も利用者データは自動削除しない。

## 品質基準

CIでは次を必須とする。

- Python 3.11 / 3.13
- 単体・HTTPテスト
- 440作品 / 4,869動画の合成データ検証
- 実ライブラリに存在する動画形式のFFmpeg/ffprobe検証
- Playwright PC / Tablet / Smartphone E2E
- Windows Installer Build / Verify

実動画・実字幕・実 `video_library.json` は公開リポジトリやCIへ含めない。
