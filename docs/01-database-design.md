# 自宅動画ライブラリ v1.0 DB設計

SQLiteを使用し、WAL、foreign keysを有効にする。

## Schema
- schema 1: メタデータ、利用者状態、スキャン履歴の初期基盤
- schema 2: Phase 3で `scan_discoveries` を追加
- schema 3: Phase 4で `user_video_state.watched_override` を追加

既存DBは削除・再作成せずmigrationする。schema 2→3でもお気に入り、視聴位置、再生回数などの既存利用者状態を保持する。

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

## 利用者状態
### `user_work_state`
作品単位のお気に入りを保持する。

### `user_video_state`
- `favorite`: 動画単位お気に入り
- `watched`: 現在の視聴済み状態
- `watched_override`: `NULL`=自動判定、`0`=手動未視聴、`1`=手動視聴済み
- `play_count`: 有効な再生セッション回数
- `position_ms`: 再生位置
- `duration_ms`: クライアントが確認した再生時間
- `last_played_at`: 最終再生日時
- `completed_at`: 視聴完了日時

作品お気に入りと動画お気に入りは独立する。

手動で「未視聴」に戻した場合、その状態は自動判定より優先する。次に実際の再生を開始すると手動未視聴overrideを解除し、その新しい再生について再び自動完了判定を許可する。

## 自動視聴済み
通常は `position_ms / duration_ms >= 90%` で視聴済みとする。`ended` イベントは視聴完了とする。

「残り5分以下」は使用しない。短尺動画が再生直後から視聴済みになることを防ぐためである。

## 作品とファイルの分離
`videos` は論理動画、`video_files` は実ファイル。ファイルが消失しても作品情報・視聴履歴を削除しない。

## スキャン状態
JSON登録済みは `NOT_SCANNED` / `MATCHED` / `MISSING`。JSONにない実ファイルは `scan_discoveries.status = NEW_FILE` として記録し、既存作品へ自動推測で紐付けない。

## 再インポート
JSON更新時は外部IDでUPSERTし、`user_work_state` / `user_video_state` を初期化しない。

## 整合性
`PRAGMA quick_check = ok`、`PRAGMA foreign_key_check` エラー0、外部ID重複0を必須とする。
