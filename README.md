# 自宅動画ライブラリ

`mp3-source-music-library` の設計思想を引き継ぎ、手元の映画・ドラマ・アニメ動画を変更せずに索引化し、Windows PC / ブラウザ / PWA / Tailscale 経由で利用するための姉妹アプリです。

## 現在の実装状況

### Phase 1: メタデータ / SQLite 基盤
- 監査済み `video_library.json` をSQLiteへUPSERT
- 作品440件 / 動画4,869件
- 作品・動画単位の利用者状態を分離

### Phase 2: 作品閲覧API / Web UI
- 作品一覧・詳細・series_groups・エピソードAPI
- 検索・カテゴリ・60作品単位ページング
- PC / スマートフォン向けレスポンシブUI

### Phase 3: 実ファイルスキャン / Range動画配信
- `scan_discoveries` で未登録動画 (`NEW_FILE`) を記録
- 動画ルート再帰スキャン
- `MATCHED` / `MISSING` / `NEW_FILE`
- HTTP Range (`206`, `416`)
- パストラバーサル／ルート外symlink防止
- HTML5 `<video>` によるブラウザ直接再生
- 元動画は変更・削除・移動しない

### Phase 4: 利用者状態 / 視聴進捗
- 作品お気に入りと動画お気に入りを独立管理
- 視聴済み / 未視聴の手動変更
- 再生位置・再生回数・最終再生日時を保存
- 90%以上再生または `ended` で自動視聴済み
- 「続きから見る」「次に見る」「最近見た作品」「視聴履歴」

### Phase 5: Windows運用 / Tailscale / PWA / Backup
- Windows Tkinterランチャー
- 通常起動はランチャーで実ファイルスキャンを完了してからHTTPサーバーとブラウザを起動
- local owner one-time token → `HttpOnly; SameSite=Strict` Cookie
- Tailscale Serve identityで利用者を個別識別
- serverはlocalhost (`127.0.0.1`) のみbind
- Tailscale Serveの状態確認・有効化/無効化
- PWA manifest / service worker / offline shell
- Service Workerは `/api/*` と `/video/*` をキャッシュしない
- SQLiteバックアップ / 復元予約 / ロールバック

### Phase 6: ffprobe / 字幕 / Windowsインストーラー
- SQLite schema 4
- ffprobeによるコンテナ・Codec・解像度・再生時間取得
- 埋込字幕stream数取得
- 外部字幕 `.srt` / `.vtt` / `.ass` / `.ssa` を検出
- 同名 / 言語suffix字幕を安全に動画へ紐付け
- 字幕実パス・実ファイル名をAPIへ公開しない
- ランチャーから監査済み `video_library.json` を初回取込
- PyInstallerでWindowsアプリ生成
- Inno Setupでユーザー権限インストーラー生成
- GitHub Actionsでsetup.exeをartifact化

### 0.7.0: 実機スキャン診断
- Owner専用の `/diagnostics.html`
- 最新SUCCESSスキャンの `MISSING` / `NEW_FILE` / 未紐付字幕 / scan error を一覧化
- MISSINGとNEW_FILEを、サイズ・拡張子・ファイル名・親フォルダー類似度から候補提示
- 未紐付字幕に対し、安全側の動画候補を提示
- 候補にはスコア・HIGH / MEDIUM / LOW・判定理由を表示
- JSON / UTF-8 BOM付きCSVで診断結果をエクスポート
- 診断は読み取り専用。動画・字幕・DBのパスや紐付けを自動変更しない

### 0.7.1: Unicode / 文字化けパス修復
- 起動スキャン前に、メタデータの相対パスに `?` が残っている動画だけを確認
- Unicode NFKD正規化と結合文字除去を行い、`?` を1文字ワイルドカードとして実ファイル名と比較
- メタデータ側・実ファイル側の双方で1対1に一意な場合だけDBパスを実ファイル表記へ修復
- 曖昧候補は自動修復せず、従来どおり `MISSING / NEW_FILE` として診断画面に残す
- 修復するのはSQLiteの `relative_path / filename / extension` のみ。元動画・字幕は移動・改名・削除しない
- `source_subfolder` は論理グループ情報として維持
- 修復後に通常スキャンを行うため、動画再生と字幕照合も正しい実パスを利用

### 0.7.2〜0.7.8: 字幕照合・診断完成と再生互換性改善
- 0.7.2: 同一作品内で一意に確定できる字幕だけを安全に自動紐付け
- 0.7.3: WindowsランチャーUIを音楽ライブラリと同系統へ統一
- 0.7.4: 残存字幕を安全条件の範囲で追加照合
- 0.7.5: 対応動画が登録されていない字幕を「対応動画なし」として正常系へ分離
- 0.7.6: 診断ヘッダーを「字幕判定」に変更し、紐付済みと対応動画なしを明示
- 0.7.7: 実機検証、アプリバージョン、README / Phase 6文書の整合性を整理
- 0.7.8: MKV/WebMの複数音声で日本語が存在する場合、元ファイルを変更せず配信時に日本語を優先

対象動画拡張子: `.mkv`, `.mp4`, `.avi`, `.webm`, `.mpg`, `.flv`, `.m4v`, `.mov`, `.wmv`

## ffprobe

ffprobeは解析専用です。動画変換・トランスコードには使用しません。

検索順:

1. `VIDEO_LIBRARY_FFPROBE` 環境変数
2. アプリ配置先 `ffprobe.exe`
3. アプリ配置先 `tools\ffprobe.exe`
4. PATH

ffprobeが見つからなくても動画一覧・再生・視聴状態管理は利用できます。技術情報だけ `NOT_AVAILABLE` になります。

公開リポジトリにはffprobeバイナリを含めません。`windows-installer\tools\ffprobe.exe` を配置してビルドした場合はアプリへ同梱します。

直接再生判定は安全側です。

- MP4/M4V + H.264 + AAC/MP3 → `DIRECT`
- WebM + VP8/VP9/AV1 + Opus/Vorbis → `DIRECT`
- HEVC、MKV等 → `UNKNOWN`

`UNKNOWN` はファイル破損ではなく「ブラウザ直接再生を保証しない」という意味です。

## 字幕

対象:

- `.srt`
- `.vtt`
- `.ass`
- `.ssa`

自動紐付け例:

```text
movie.mkv
movie.srt
movie.ja.srt
movie.jpn.forced.srt
movie.en.default.vtt
```

`movie.commentary.srt` のように意味推測が必要な名前は自動紐付けしません。こうした字幕はスキャン診断画面で候補を確認できますが、自動紐付けはしません。

0.7.6までに字幕の検出・安全な紐付け・診断分類を実装済みです。SRT/ASS→WebVTT変換とプレーヤー字幕表示は後続機能です。

## Windowsでの通常利用

### インストーラー版

CI / Releaseで生成された `VideoLibrary-<version>-setup.exe` を実行します。管理者権限は不要です。

インストール先:

```text
%LOCALAPPDATA%\Programs\VideoLibrary
```

利用者データ:

```text
%LOCALAPPDATA%\VideoLibrary
├─ library.db
├─ config.json
├─ runtime.json
├─ metadata\video_library.json
├─ Backups\
└─ Logs\
```

アンインストールしても利用者データは削除しません。

初回はランチャーで:

1. 動画フォルダーを選択
2. 監査済み `video_library.json` を選択
3. 「取込」
4. 「ライブラリを開始」
5. Windowsランチャー上で動画・字幕・ffprobeの起動スキャン進捗を確認
6. スキャン完了後にブラウザが自動起動

と進めます。

2回目以降は動画フォルダーとDBが有効なら、ランチャー起動後に自動で起動スキャンを開始します。ブラウザはスキャン完了前には開きません。起動後の追加・変更確認には、ブラウザ側の「再スキャン」と進捗モーダルを利用できます。

0.7.1以降、起動スキャン前にメタデータ側に残った `?` 文字化けパスを安全に確認します。一意に対応する実ファイルだけDBのパスを修復してから通常スキャンへ進みます。

### スキャン診断

メイン画面右上の「診断」からOwner専用診断画面を開けます。最新の成功スキャンについて、MISSING / NEW_FILE / 未紐付字幕 / 対応動画なし / 未対応字幕 / エラーと候補を確認できます。

診断画面は読み取り専用です。候補を見つけてもファイル移動、ファイル名変更、DBパス更新、字幕紐付けは自動実行しません。必要な修正ルールを人が確認してから別工程で適用します。

診断API:

```text
GET /api/admin/scan-diagnostics
GET /api/admin/scan-diagnostics.json
GET /api/admin/scan-diagnostics.csv
```

3つともOwner専用です。

### ソースから起動

```powershell
python windows-installer\src\launcher.py
```

開発用直接起動:

```powershell
python windows-installer\src\server.py --database library.db --video-root "D:\Videos"
```

control secretなしの直接起動はテスト／開発用localhost owner互換モードです。通常利用はランチャーを使用してください。

## 認証と外部接続

### localhost owner
ランチャーが短寿命ワンタイムトークンを作成し、ブラウザで1回だけ交換してowner Cookieを発行します。control secretはブラウザへ渡しません。

### Tailscale
Tailscale Serveが付与する本人情報を `user_identities` へ紐付けます。利用者ごとのお気に入り・視聴位置・履歴は混ざりません。

外部公開はTailscale Serveのみを前提とします。ルーターのポート開放、DMZ、Tailscale Funnelは使用しません。

## PWA
PWAがキャッシュするのはHTML/manifest/icon/offline shell等のアプリシェルのみです。

以下はキャッシュ対象外です。
- `/api/*`
- `/video/*`
- SQLite
- `video_library.json`
- 視聴履歴などの個人状態

## バックアップ・復元

ランチャーまたはAPIからSQLiteバックアップを作成できます。バックアップ作成後は `PRAGMA quick_check` とschemaを検証します。

復元は稼働中DBを直接置換せず予約制です。次回ランチャー起動時に現DBを `library-pre-restore-*.db` へ退避してから復元し、失敗時はロールバックします。

## 実機総合検証

実動画はCIへアップロードせず、PC上で次を実行します。

```powershell
python scripts\validate_real_library.py `
  --database "$env:LOCALAPPDATA\VideoLibrary\library.db" `
  --video-root "D:\Videos" `
  --metadata "C:\path\video_library.json" `
  --expected-works 440 `
  --expected-videos 4869 `
  --expected-subtitles 1234 `
  --expected-matched-subtitles 1227 `
  --expected-orphan-subtitles 7 `
  --expected-unsupported-subtitles 3
```

440作品 / 4,869動画、対応字幕1,234件（紐付1,227件・対応動画なし7件）、未対応字幕3件、SQLite整合性、MISSING / NEW_FILE / 真の未紐付字幕 / 診断エラー / ffprobeエラーをまとめて確認します。対応動画なし7件は正常系として扱います。0.7.1以降、この実機検証も起動時と同じ文字化けパス修復を先に適用します。

## 個人データを公開しない
実際の `video_library.json`、実動画、実字幕は公開リポジトリ／CIへ含めません。CIでは同じ **440作品 / 4,869動画 / 動画0件4作品** の合成データを使用します。

## テスト

```powershell
python -m unittest discover -s tests -v
python scripts\validate_ci_fixture.py
```

Windowsインストーラー:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows-installer\build\build.ps1
```

CIはWindows / Python 3.11・3.13です。全テスト成功後にWindowsインストーラーも生成します。

## ドキュメント
- [基本設計](docs/00-basic-design.md)
- [DB設計](docs/01-database-design.md)
- [画面設計](docs/02-screen-design.md)
- [API設計](docs/03-api-design.md)
- [Phase 1](docs/04-phase1-design.md)
- [Phase 2](docs/05-phase2-implementation.md)
- [Phase 3](docs/06-phase3-implementation.md)
- [Phase 4](docs/07-phase4-implementation.md)
- [Phase 5](docs/08-phase5-implementation.md)
- [Phase 6](docs/09-phase6-implementation.md)
- [0.6.9 起動時スキャンフロー](docs/20-0.6.9-startup-scan-flow.md)
- [0.7.0 スキャン診断](docs/21-0.7.0-scan-diagnostics.md)
- [0.7.1 Unicode / 文字化けパス修復](docs/22-0.7.1-unicode-path-repair.md)
- [0.7.2 安全な字幕一意照合](docs/23-0.7.2-safe-subtitle-match.md)
- [0.7.3 ランチャーUI統一](docs/24-0.7.3-launcher-ui-parity.md)
- [0.7.4 残存字幕照合](docs/24-0.7.4-residual-subtitle-matching.md)
- [0.7.5 対応動画なし字幕診断](docs/25-0.7.5-orphan-subtitle-diagnostics.md)
- [0.7.6 字幕判定表示](docs/26-0.7.6-diagnostics-subtitle-judgement.md)
- [0.7.7 整合性整理](docs/27-0.7.7-consistency-cleanup.md)
- [0.7.8 MKV複数音声の日本語優先再生](docs/28-0.7.8-japanese-audio-default.md)

## 正本
- 動画そのもの: ユーザー指定の動画フォルダー
- 作品メタデータ: ローカルの `video_library.json`
- 利用者状態: SQLite `library.db`

元動画・字幕を変更・削除・移動しないことを設計原則とします。