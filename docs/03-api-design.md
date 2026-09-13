# 自宅動画ライブラリ v1.0 API設計

ベースURL例: `http://127.0.0.1:8765`

APIはUTF-8 JSON、原則 `Cache-Control: no-store`。

## 権限
- 公開: 匿名閲覧・再生
- 利用者: local owner または有効なTailscale利用者
- オーナー: `is_owner = 1`
- ローカルオーナー: Windows管理画面から認証した自宅PC
- ランチャー: control secretを持つローカルプロセス

利用者IDはクライアント入力を信用せず、Cookie/Tailscale identityからサーバー側で決定する。

## 主なAPI
- `GET /api/health`
- `GET /api/current-user`
- `GET /api/home`
- `GET /api/works`
- `GET /api/works/{id}`
- `GET /api/works/{id}/videos`
- `GET /api/videos/{id}`
- `GET /api/search`
- `GET /video/{id}`
- `GET /api/me/favorite-works`
- `PUT /api/me/works/{id}/favorite`
- `GET /api/me/favorite-videos`
- `PUT /api/me/videos/{id}/favorite`
- `PUT /api/me/videos/{id}/watched`
- `POST /api/me/videos/{id}/playback/start`
- `POST /api/me/videos/{id}/playback/progress`
- `GET /api/me/continue-watching`
- `GET /api/me/next-up`
- `GET /api/me/recent-works`
- `GET /api/me/history`
- `GET /api/diagnostics`
- `POST /api/scan`
- `POST /api/metadata/import`

## 動画配信
`GET /video/{videoId}` だけを正式経路とし、任意ローカルパス指定は禁止。Rangeへ `206 Partial Content` を返す。絶対パスはAPIへ返さない。

## セキュリティ
Cookieは `HttpOnly; SameSite=Strict`。状態変更APIはOrigin/Hostを検証し、ワイルドカードCORSは使用しない。
