# 自宅動画ライブラリ v1.2.3 API設計

通常のローカルURL例: `http://127.0.0.1:8876`

APIはUTF-8 JSON。状態・個人情報系は原則 `Cache-Control: no-store`。TMDb画像は短時間のprivate browser cacheを許可する。

## アクセスモデル

HTTPサーバーはlocalhostへだけbindする。

### 読み取り

作品一覧・作品詳細・人物名鑑・動画/字幕/TMDb画像の配信は、到達可能な同一origin内で利用できる。

利用者認証がない読み取りでは、個人のお気に入り・視聴状態は付与しない。

### 利用者

次のいずれかで利用者をサーバー側で確定する。

- localhost owner Cookie
- Tailscale Serve identity

`/api/me/*` の個人状態APIは認証必須。

### Owner

スキャン実行、診断、バックアップ等の管理操作はOwner必須。

### ランチャー

localhostのWindowsランチャーだけがcontrol secretを使用して短寿命owner one-time tokenを登録する。control secret自体はブラウザへ渡さない。

## 主なGET API

- `GET /api/health`
- `GET /api/current-user`
- `GET /api/stats`
- `GET /api/scan/status`
- `GET /api/works`（`is_visible=1` の作品のみ）
- `GET /api/works/{id}`
- `GET /api/works/{id}/videos`
- `GET /api/videos/{id}`
- `GET /api/people?role=director|cast`
- `GET /api/me/favorite-works`
- `GET /api/me/favorite-videos`
- `GET /api/me/continue-watching`
- `GET /api/me/next-up`
- `GET /api/me/recent-works`
- `GET /api/me/history`
- `GET /api/backups`
- `GET /api/admin/scan-diagnostics`
- `GET /api/admin/scan-diagnostics.json`
- `GET /api/admin/scan-diagnostics.csv`

## メディア配信

- `GET /video/{videoId}`
- `GET /subtitle/{subtitleId}.vtt`
- `GET /tmdb-image/poster/{workId}`
- `GET /tmdb-image/backdrop/{workId}`
- `GET /tmdb-person-image/{personId}`

任意ローカルパス指定は禁止し、DB IDからサーバー側で実体を解決する。動画・字幕・画像の絶対ローカルパスはAPIへ返さない。

動画はHTTP Rangeへ対応する。ブラウザ非互換形式はサーバー側でPlaybackCacheへ互換MP4を準備してから配信する。

## 状態変更API

- `PUT /api/me/works/{id}/favorite`
- `PUT /api/me/videos/{id}/favorite`
- `PUT /api/me/videos/{id}/watched`
- `POST /api/me/videos/{id}/playback/start`
- `POST /api/me/videos/{id}/playback/progress`

状態変更は認証必須で、Origin / Hostを検証する。

## Owner管理API

- `POST /api/scan`
- `POST /api/backups/create`
- `POST /api/backups/restore`
- `POST /api/backups/restore/cancel`

診断GETもOwner専用。作品visibilityを変更するWeb APIは提供しない。作品一覧・作品詳細・動画詳細・動画配信・字幕・作品画像は `is_visible=1` の作品だけを返す。表示対象の変更はWindowsランチャーがSQLiteへ直接反映する。

メタデータ初回取込は現在Windowsランチャーから行い、Web APIとして任意ファイル取込を公開しない。

## localhost owner bootstrap

内部経路:

- `POST /api/local-auth/token`: ランチャーがcontrol secret付きでone-time tokenを登録
- `GET /api/local-auth/exchange?token=...`: loopbackブラウザがtokenをowner session Cookieへ交換

Cookieは `HttpOnly; SameSite=Strict`。

## セキュリティ

- server bindはlocalhostのみ
- 外部接続はTailscale Serve前提
- ワイルドカードCORSは使用しない
- 状態変更時はOrigin / Hostを検証
- 任意ローカルパスをAPI引数として受けない
- 動画、字幕、TMDb画像はDB ID経由で解決
- API Read Access TokenをURLへ付与しない
