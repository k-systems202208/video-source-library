# Phase 2 実装・検証

## 目的

Phase 1でSQLiteへ取り込んだ作品・動画メタデータを、ブラウザから安全に閲覧できる最初のアプリケーション層を構築する。

## 実装範囲

- `library_service.py`: DB問い合わせ層
- `server.py`: localhost HTTP / JSON API
- `video-library.html`: 最初のレスポンシブWeb UI
- `tests/test_phase2.py`: サービス / HTTP / UI smoke test

## API

- `GET /api/health`
- `GET /api/stats`
- `GET /api/works`
- `GET /api/works/{id}`
- `GET /api/works/{id}/videos`
- `GET /api/videos/{id}`

## 作品一覧

標準60作品単位で取得し、最大200件に制限する。

検索対象:

- 正式日本語タイトル
- 元タイトル
- 監督 / 演出
- 主な出演者 / 声優

カテゴリによる完全一致絞り込みをサポートする。

## 作品詳細

作品詳細では作品メタデータと `series_groups` のみを返す。4,869動画を作品詳細レスポンスへ埋め込まない。

各グループには動画件数と利用可能ファイル件数を返す。

## エピソード一覧

`GET /api/works/{id}/videos?groupId=...` により選択したグループだけを取得する。

UIはグループタブを選択した時点で該当動画を取得する。

## パス情報の非公開

公開APIから次の情報を返さない。

- 動画ルートの絶対パス
- `relative_path`
- `source_folder`
- 実ファイル名

動画配信を実装する後続Phaseでも、ブラウザから物理パスを指定させずDB内部IDから解決する。

## Web UI

初版UIでは次を提供する。

- 作品一覧カード
- 作品検索
- カテゴリ絞り込み
- 並び順
- 追加読み込み
- 作品詳細
- 監督 / 出演情報
- series_groups切替
- エピソード一覧
- 動画メタデータ表示

ポスター画像、お気に入り、視聴進捗、実動画再生は後続Phaseとする。

## HTTP

- `127.0.0.1` bindを既定とする
- JSON / HTMLは `Cache-Control: no-store`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: same-origin`
- 存在しない作品 / 動画は404
- 不正なクエリは400

## 自動テスト

Phase 2テストでは以下を確認する。

- 検索
- カテゴリ
- ページング
- 動画0件作品
- 作品 → グループ → 動画の関連
- APIにパス / ファイル名を露出しない
- `/api/health`
- `/api/works`
- 作品詳細
- エピソード一覧
- 動画詳細
- 404
- Web UI配信
- UIが60件ページングを使用

Phase 1の440作品 / 4,869動画の合成fixture検証も継続する。

## Phase 2完了条件

- Windows / Python 3.11、3.13でCI成功
- Phase 1テストを壊さない
- Phase 2テスト成功
- mainへSquash Merge
- Issueを自動クローズ
