# 自宅動画ライブラリ v1.0 DB設計

初期DBはSQLite schema 1。WAL、foreign keysを有効にする。

## テーブル
- `schema_info`: schema番号
- `works`: 作品
- `series_groups`: Season / OVA / OAD / SPECIAL / MOVIE / EXTRA 等の表示グループ
- `videos`: 論理動画・エピソード
- `video_files`: 物理ファイル情報
- `users`: 利用者
- `user_identities`: local_owner / tailscale 識別
- `user_work_state`: 作品単位お気に入り
- `user_video_state`: 動画単位お気に入り、視聴済み、再生回数、再生位置
- `scan_runs`, `scan_errors`: スキャン履歴
- `metadata_imports`: JSON取込履歴

## ID
`works.id` / `videos.id` はアプリ内部ID。JSONとの連携には `external_work_no` / `external_file_no` を使用する。

## 作品とファイルの分離
`videos` は論理動画、`video_files` は実ファイル。ファイルが消失しても作品情報・視聴履歴を削除しない。

## お気に入り
- 作品お気に入り: `user_work_state.favorite`
- 動画お気に入り: `user_video_state.favorite`

両者は独立し、作品のお気に入り操作で全エピソードを変更しない。

## 再インポート
JSON更新時は外部IDでUPSERTし、`user_work_state` / `user_video_state` を初期化しない。

## 整合性
最低限 `PRAGMA quick_check = ok`、`PRAGMA foreign_key_check` エラー0、外部ID重複0を必須とする。
