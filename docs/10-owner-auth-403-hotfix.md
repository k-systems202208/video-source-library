# 0.6.1 owner認証 403 hotfix

## 実機で確認された現象

Windows実機へ0.6.0をインストール後、以下は正常だった。

- 440作品 / 4,869動画のメタデータ取込
- ffprobe検出
- localhostサーバー起動
- Tailscale Serve検出

一方、ランチャーの「ブラウザで開く」で以下となった。

```text
オーナーとしてブラウザを開けませんでした。
HTTP Error 403: Forbidden
```

## 原因

owner認証ではランチャー自身が `http://127.0.0.1:<port>/api/local-auth/token` へPOSTし、短寿命ワンタイムトークンを登録する。

0.6.0では `urllib.request.urlopen()` をそのまま利用していたため、Windowsのシステムプロキシ・環境変数プロキシを継承できる状態だった。実機環境によってはlocalhost向け内部通信がプロキシへ送られ、VideoLibraryサーバーへ到達する前に403となる。

## 修正

0.6.1ではowner token登録に専用openerを使用する。

```python
urllib.request.build_opener(urllib.request.ProxyHandler({}))
```

これにより、ランチャー→localhostの内部認証通信はシステム/企業プロキシを使用しない。

また、owner認証先は `http` かつ `127.0.0.1` / `localhost` / `::1` に限定する。

## セキュリティ方針

サーバー側のOrigin検査は緩和しない。

`/api/local-auth/token` は引き続き以下を要求する。

- loopback接続
- プロセスごとにランダム生成したcontrol secret
- 状態変更APIのOrigin制約

実機バグへの対処を理由にCSRF防御を弱めない。

## 回帰テスト

Phase 5テストへ以下を追加する。

- `HTTP_PROXY` / `HTTPS_PROXY` がlocalhostを拒否する値でも、ランチャー内部owner token登録が直接localhostへ到達すること
- cross-originのowner token登録は引き続き403になること

## バージョン

Windowsランチャーおよびインストーラーを `0.6.1` とする。
