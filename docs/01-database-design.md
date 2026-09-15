# 自宅動画ライブラリ v1.1 DB設計

SQLiteを使用し、WAL、foreign keysを有効にする。

## Schema
- schema 1: メタデータ、利用者状態、スキャン履歴の初期基盤
- schema 2: Phase 3で `scan_discoveries` を追加
- schema 3: Phase 4で `user_video_state.watched_override` を追加
- schema 4: Phase 6で `subtitles` とffprobe解析状態を追加
- schema 5: 1.1.0でTMDb作品紐付けとAPIレスポンスキャッシュを追加

既存DBは削除・再作成せずmigrationする。schema更新後もお気に入り、視聴位置、再生回数などの既存利用者状態を保持する。

## テーブル
- `schema_info`
- `works`
- `series_groups`
- `videos`
- `video_files`
- `subtitles`: 外部字幕の検出・動画紐付け状態
- `users`
- `user_identities`
- `user_work_state`
- `user_video_state`
- `scan_runs`
- `scan_errors`
- `scan_discoveries`: JSON未登録だが実フォルダーで発見された `NEW_FILE`
- `metadata_imports`
- `tmdb_work_links`: ローカル作品とTMDb movie/tv IDの紐付け・画像パス等のキャッシュ
- `tmdb_api_cache`: TMDb search/details/credits/configuration等のJSONレスポンスキャッシュ

## `video_files`

`videos` が論理動画、`video_files` が実ファイルを表す。

Phase 6時点の主な実ファイル情報:

- `relative_path`: 動画ルートからの相対パス。APIには返さない
- `file_size`
- `modified_time_ns`
- `duration_ms`
- `container_format`
- `video_codec`
- `audio_codec`
- `width` / `height`
- `embedded_subtitle_count`
- `probe_status`: `NOT_PROBED` / `NOT_AVAILABLE` / `OK` / `ERROR`
- `probed_at`
- `playback_support`: `DIRECT` / `UNKNOWN`
- `is_available`
- `scan_status`: `NOT_SCANNED` / `MATCHED` / `MISSING`

ファイルが消失しても `videos` や利用者状態は削除しない。

## `subtitles`

外部字幕ファイルを保持する。

- `video_id`: 安全に紐付けできた動画。未紐付の場合は `NULL`
- `relative_path`: 字幕の相対パス。APIには返さない
- `filename`: DB内部の診断用。APIには返さない
- `extension`: SRT / VTT / ASS / SSA
- `language`
- `is_forced`
- `is_default`
- `match_method`: `EXACT_STEM` / `LANGUAGE_SUFFIX` / `UNMATCHED`
- `file_size`
- `modified_time_ns`
- `is_available`
- `last_scanned_at`

字幕名から作品内容を推測して紐付けない。同一フォルダーかつ動画stem完全一致、または認識済みの言語・forced/default suffixだけを自動紐付けする。

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

## スキャン状態
JSON登録済みは `NOT_SCANNED` / `MATCHED` / `MISSING`。JSONにない実ファイルは `scan_discoveries.status = NEW_FILE` として記録し、既存作品へ自動推測で紐付けない。

`scan_runs` は動画の一致/欠落/新規に加え、Phase 6から以下も保持する。

- `subtitles_found`
- `subtitles_matched`
- `subtitles_unmatched`
- `probe_errors`

## ffprobe再解析

ファイルサイズまたは更新時刻が変わった動画は再解析する。

ffprobeが後から利用可能になった場合、`probe_status != OK` の既存動画も再解析対象とする。解析失敗時に古い技術情報を新ファイルの情報として残さない。

## 再インポート
JSON更新時は外部IDでUPSERTし、`user_work_state` / `user_video_state` を初期化しない。実ファイルスキャン情報や字幕情報もJSON再取込だけでは削除しない。

## 整合性
`PRAGMA quick_check = ok`、`PRAGMA foreign_key_check` エラー0、外部ID重複0を必須とする。

## TMDbキャッシュ（schema 5）

### `tmdb_work_links`
ローカル `works.id` ごとにTMDbとの照合状態を保持する。1作品につき0または1行で、同じTMDb作品へ複数のローカル作品が対応する可能性があるためTMDb ID自体はUNIQUEにしない。

- `media_type`: `movie` / `tv`
- `tmdb_id`: TMDb側ID
- `match_status`: `UNMATCHED` / `CANDIDATE` / `MATCHED` / `REVIEW`
- `confidence`: 0.0〜1.0。自動確定の判断材料であり、低信頼候補は後続工程で `REVIEW` とする
- `matched_title` / `matched_year`
- `poster_path` / `backdrop_path`
- `overview`
- `synced_at`

### `tmdb_api_cache`
API応答を `cache_key` 単位でJSON保存する。`expires_at` がある場合は期限切れを再利用しない。API Read Access Tokenは保存しない。
