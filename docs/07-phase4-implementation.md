# Phase 4 実装・検証

## 目的
Phase 3までの作品閲覧・実ファイル再生基盤に、利用者ごとのお気に入り、視聴位置、視聴済み、履歴を追加する。

## 利用者
Phase 4ではlocalhostで動作する既定利用者として `local_owner` identityを1件作成する。

これは最終認証方式ではない。Tailscale identity、owner-link、短時間local-auth token / HttpOnly Cookieは後続Phaseで音楽版と同等方式へ置き換える。

## API
- `GET /api/current-user`
- `GET /api/me/favorite-works`
- `GET /api/me/favorite-videos`
- `PUT /api/me/works/{id}/favorite`
- `PUT /api/me/videos/{id}/favorite`
- `PUT /api/me/videos/{id}/watched`
- `POST /api/me/videos/{id}/playback/start`
- `POST /api/me/videos/{id}/playback/progress`
- `GET /api/me/continue-watching`
- `GET /api/me/next-up`
- `GET /api/me/recent-works`
- `GET /api/me/history`

状態変更APIでは `Origin` が送信された場合、現在のHostと一致するsame-originだけを許可する。

## 再生セッション
`playback/start` はランダムな `playSessionId` を返す。セッションはサーバーメモリ上だけで管理し、永続化しない。

再生回数は単なる再生ボタン押下では増加させない。再生位置が次の閾値を超えた最初の1回だけ加算する。

`max(5秒, min(30秒, 動画時間の5%))`

同一 `playSessionId` では最大1回だけ加算する。

## 自動完了
- `ended`: 完了
- それ以外: 再生率90%以上で完了

短尺コンテンツの誤判定を避けるため「残り5分以下」は使用しない。

## 次に見る
同一作品・同一 `series_group` の `content_type = EPISODE` のみを対象とする。`EXTRA`, `TRAILER`, `MAKING`, `INTERVIEW`, `FAN_EDIT` 等は候補に入らない。

グループ末尾から別グループへは自動遷移しない。

## UI
- ホームに「続きから見る」「次に見る」
- 作品カードに視聴進捗
- 作品お気に入り
- エピソードに `★ / ✓ / ▶ / ○` 状態
- 動画お気に入り
- 視聴済み / 未視聴
- 保存位置からの再開
- 再生中は10秒程度の間隔と pause / ended で進捗保存

## 検証
Phase 4テストでは次を確認する。

- schema 2→3 migrationで利用者状態を保持
- 作品お気に入りと動画お気に入りを独立
- 利用者A/Bの状態分離
- 短尺動画が開始直後に自動視聴済みにならない
- 90%で自動視聴済み
- 手動未視聴が自動判定より優先
- 新しい再生開始後は自動完了へ戻る
- continue-watching
- next-upがEXTRAを除外
- play_countが同一sessionで1回のみ
- current-user / favorite / playback HTTP API
- Phase 4 UI操作要素

既存Phase 1〜3テストと440作品 / 4,869動画fixture検証も継続してCIで実行する。
