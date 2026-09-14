# 自宅動画ライブラリ

`mp3-source-music-library` の設計思想を引き継ぎ、手元の映画・ドラマ・アニメ動画を変更せずに索引化し、Windows PC / ブラウザ / PWA / Tailscale 経由で利用するための姉妹アプリです。

## 現在の実装状況

### Phase 1: メタデータ / SQLite 基盤
- 監査済み `video_library.json` を SQLite へUPSERT
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
- SQLite schema 3
- 作品お気に入りと動画お気に入りを独立管理
- 視聴済み / 未視聴の手動変更
- 再生位置・再生回数・最終再生日時を保存
- 90%以上再生または `ended` で自動視聴済み
- 「続きから見る」「次に見る」「最近見た作品」「視聴履歴」

### Phase 5: Windows運用 / Tailscale / PWA / Backup
- Windows Tkinterランチャー
- local owner one-time token → `HttpOnly; SameSite=Strict` Cookie
- Tailscale Serve identityで利用者を個別識別
- serverはlocalhost (`127.0.0.1`) のみbind
- Tailscale Serveの状態確認・有効化/無効化
- PWA manifest / service worker / offline shell
- Service Workerは `/api/*` と `/video/*` をキャッシュしない
- SQLite手動バックアップ
- 復元予約 → 次回起動時復元
- 復元前自動バックアップと失敗時ロールバック

対象拡張子: `.mkv`, `.mp4`, `.avi`, `.webm`, `.mpg`, `.flv`, `.m4v`, `.mov`, `.wmv`

MP4 / M4V / WebM は拡張子ベースで `DIRECT`、その他は `UNKNOWN` とします。Codec判定は後続Phaseで `ffprobe` を導入して精度を上げます。

## 推奨起動方法

監査済みJSONを初回取り込み後、Windowsランチャーを使用します。

```powershell
python windows-installer\src\metadata_importer.py metadata\video_library.json --database "$env:LOCALAPPDATA\VideoLibrary\library.db"
python windows-installer\src\launcher.py
```

ランチャーで動画フォルダーを選択して「開始」を押すと、localhostサーバーを起動し、owner認証済みブラウザを開きます。

データ保存先:

```text
%LOCALAPPDATA%\VideoLibrary
├─ library.db
├─ config.json
├─ runtime.json
├─ Backups\
└─ Logs\
```

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

## 開発用直接起動

```powershell
python windows-installer\src\server.py --database library.db --video-root "D:\Videos"
```

control secretなしの直接起動はテスト／開発用localhost owner互換モードです。通常利用は `launcher.py` を使用してください。

## 個人データを公開しない
実際の `video_library.json` と実動画は公開リポジトリ／CIへ含めません。CIでは同じ **440作品 / 4,869動画 / 動画0件4作品** の合成データを使用します。

## テスト
```powershell
python -m unittest discover -s tests -v
python scripts\validate_ci_fixture.py
```
CIはWindows / Python 3.11・3.13です。

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

## 正本
- 動画そのもの: ユーザー指定の動画フォルダー
- 作品メタデータ: ローカルの `video_library.json`
- 利用者状態: SQLite `library.db`

元動画を変更・削除・移動しないことを設計原則とします。
