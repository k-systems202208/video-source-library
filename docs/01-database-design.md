# 自宅動画ライブラリ v1.0 DB設計

SQLiteを使用し、WAL、foreign keysを有効にする。

## Schema
- schema 1: メタデータ、利用者状態、スキャン履歴の初期基盤
- schema 2: Phase 3で `scan_discoveries` を追加

既存schema 1 DBは削除・再作成せずschema 2へ更新する。

## テーブル
- `schema_info`
- `works`
- `series_groups`
- `videos`
- `video_files`
- `users`
- `user_identities`
- `user_work_state`
- `user_video_state`
- `scan_runs`
- `scan_errors`
- `scan_discoveries`: JSON未登録だが実フォルダーで発見された `NEW_FILE`
- `metadata_imports`

## 作品とファイルの分離
`videos` は論理動画、`video_files` は実ファイル。ファイルが消失しても作品情報・視聴履歴を削除しない。

## スキャン状態
JSON登録済みは `NOT_SCANNED` / `MATCHED` / `MISSING`。JSONにない実ファイルは `scan_discoveries.status = NEW_FILE` として記録し、既存作品へ自動推測で紐付けない。

## 再インポート
JSON更新時は外部IDでUPSERTし、`user_work_state` / `user_video_state` を初期化しない。

## 整合性
`PRAGMA quick_check = ok`、`PRAGMA foreign_key_check` エラー0、外部ID重複0を必須とする。
