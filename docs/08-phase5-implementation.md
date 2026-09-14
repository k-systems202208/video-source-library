# Phase 5 実装

## 目的
Phase 4までの動画閲覧・再生・視聴状態に、Windows常駐運用・Tailscale・PWA・バックアップを追加する。

## 認証
### Local owner
Windowsランチャーとサーバーが起動中だけ共有する高エントロピーcontrol secretを使用する。

1. ランチャーが60秒のワンタイムトークンを生成
2. localhost限定 `POST /api/local-auth/token` へcontrol secret付きで登録
3. ブラウザを `/api/local-auth/exchange?token=...` で開く
4. トークンを1回だけ消費
5. `HttpOnly; SameSite=Strict` Cookieを発行

control secret自体はブラウザへ渡さない。サーバー再起動でトークンとセッションは無効になる。

### Tailscale
Tailscale Serveから localhost サーバーへ転送される以下を使用する。

- `Tailscale-User-Login`
- `Tailscale-User-Name`
- `Tailscale-User-Profile-Pic`

`user_identities(provider='tailscale', subject=<normalized login>)` で利用者を安定識別する。表示名変更は同一人物の識別に影響させない。

Tailscale利用者は既定では一般利用者であり、スキャン・バックアップ等のオーナー操作は実行できない。

## サーバー境界
- bind: `127.0.0.1` / localhostのみ
- `0.0.0.0` bindは禁止
- 外部公開はTailscale Serveのみ
- Funnel、DMZ、ルーターポート開放は使用しない

## PWA
追加ファイル:
- `manifest.webmanifest`
- `service-worker.js`
- `offline.html`
- `icon.svg`

Service Workerでキャッシュするのはアプリシェルのみ。

キャッシュ禁止:
- `/api/*`
- `/video/*`
- SQLite
- `video_library.json`
- 個人状態

## Windowsランチャー
`launcher.py` が以下を担当する。

- 動画フォルダー選択
- config保存
- localhostサーバー起動/停止
- ownerとしてブラウザを開く
- Tailscale Serve状態確認・有効化/無効化
- 手動バックアップ作成
- 予約済みDB復元の起動前適用

## バックアップ・復元
SQLite Online Backup APIを使用する。

バックアップ作成後:
- `PRAGMA quick_check`
- schema version
- works/videos/users件数

を検査する。

復元はサーバー稼働中にDBを直接置換せず、APIでは復元予約だけ作成する。次回ランチャー起動時に:

1. 現DBを `library-pre-restore-*.db` へ退避
2. 選択バックアップを一時DBへコピー
3. 一時DBを検証
4. `library.db` と置換
5. 復元後DBを再検証
6. 失敗した場合は復元前DBへロールバック

## API
- `GET /api/current-user`
- `POST /api/local-auth/token`
- `GET /api/local-auth/exchange`
- `GET /api/backups`
- `POST /api/backups/create`
- `POST /api/backups/restore`
- `POST /api/backups/restore/cancel`

## 互換モード
`server.py` をcontrol secretなしで直接起動した場合は、既存Phase 1〜4テストと開発用途のためlocalhost owner互換モードになる。

通常利用は `launcher.py` を使用し、owner Cookie認証を有効にする。

## テスト
Phase 5では以下を追加検証する。

- one-time tokenは1回だけ使用可能
- owner Cookie属性
- 未認証状態変更は401
- Tailscale利用者A/B分離
- Tailscale一般利用者のowner操作拒否
- PWA manifest / Service Worker
- `/api/*` / `/video/*` のキャッシュ除外
- localhost以外へのbind拒否
- バックアップ作成・検証
- 復元予約・復元前バックアップ・復元
