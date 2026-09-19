# 自宅動画ライブラリ v1.2.0 DB設計

SQLiteを使用し、WALとforeign keysを有効にする。現行schemaは **8**。

## Schema履歴

- schema 1: メタデータ、利用者状態、スキャン履歴の初期基盤
- schema 2: `scan_discoveries` を追加
- schema 3: `user_video_state.watched_override` を追加
- schema 4: `subtitles` とffprobe解析状態を追加
- schema 5: TMDb作品紐付け `tmdb_work_links` と `tmdb_api_cache` を追加
- schema 6: `tmdb_people` / `tmdb_work_people` を追加し、出演者／声優の人物写真を導入
- schema 7: `tmdb_work_people.role` に `DIRECTOR` を保存可能な互換定義を追加
- schema 8: `works.is_visible` を追加し、館内表示対象を作品単位で管理

schema 7の `DIRECTOR` は一度配布済みのDBとの後方互換のため残す。現在の通常同期では監督／演出の顔写真用人物リンクを新規作成しない。

schema 8の `works.is_visible` は `1=表示 / 0=非表示`。既存作品と新規作品の初期値は1。metadata再取込ではこの列を更新対象に含めず、Ownerが設定した表示状態を保持する。

既存DBは削除・再作成せずmigrationし、お気に入り、視聴位置、再生回数等の既存利用者状態を保持する。

## 主なテーブル

- `schema_info`
- `works`
- `series_groups`
- `videos`
- `video_files`
- `subtitles`
- `users`
- `user_identities`
- `user_work_state`
- `user_video_state`
- `scan_runs`
- `scan_errors`
- `scan_discoveries`
- `metadata_imports`
- `tmdb_work_links`
- `tmdb_people`
- `tmdb_work_people`
- `tmdb_api_cache`

## `works`

作品メタデータに加え、schema 8から館内表示設定を保持する。

- `is_visible`: `1=通常画面に表示` / `0=非表示`
- 非表示は削除ではなく、動画・TMDb・お気に入り・視聴履歴を保持する
- `#/work/{id}` の直接表示はvisibilityに関係なく可能

## `video_files`

`videos` が論理動画、`video_files` が実ファイルを表す。

主な実ファイル情報:

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
- `playback_support`
- `is_available`
- `scan_status`

ファイルが消失しても論理動画や利用者状態は削除しない。

## `subtitles`

外部字幕を保持する。

- `video_id`: 安全に紐付けできた動画。未紐付の場合は `NULL`
- `relative_path` / `filename`: DB内部用でAPIへ実パスを返さない
- `extension`
- `language`
- `is_forced`
- `is_default`
- `match_method`
- `file_size`
- `modified_time_ns`
- `is_available`
- `last_scanned_at`

字幕名から作品内容を推測して自動紐付けしない。

## 利用者状態

### `user_work_state`

作品単位のお気に入りを保持する。

### `user_video_state`

- `favorite`
- `watched`
- `watched_override`
- `play_count`
- `position_ms`
- `duration_ms`
- `last_played_at`
- `completed_at`

作品お気に入りと動画お気に入りは独立する。

## スキャン

`scan_runs`、`scan_errors`、`scan_discoveries` で実ファイルスキャン結果を保持する。

JSON登録済み動画は `NOT_SCANNED` / `MATCHED` / `MISSING`。JSONにない実ファイルは `scan_discoveries.status = NEW_FILE` として記録し、既存作品へ推測で自動紐付けしない。

## `tmdb_work_links`

ローカル `works.id` ごとにTMDb作品との照合状態を0または1行保持する。

- `media_type`: `movie` / `tv`
- `tmdb_id`
- `match_status`: `UNMATCHED` / `CANDIDATE` / `MATCHED` / `REVIEW`
- `confidence`
- `matched_title` / `matched_year`
- `poster_path` / `backdrop_path`
- `overview`
- `synced_at`

同じTMDb作品へ複数のローカル作品が対応する可能性があるため、TMDb ID自体はUNIQUEにしない。

## `tmdb_people`

安全に特定できたTMDb人物を保持する。

- `tmdb_person_id`
- `display_name`
- `original_name`
- `profile_path`
- `known_for_department`
- `synced_at`

## `tmdb_work_people`

ローカル作品・ローカル人物名・TMDb人物IDの対応を保持する。

- 主キー: `work_id, role, local_name`
- `role`: `CAST` / `DIRECTOR`
- `tmdb_person_id`
- `character_text`
- `billing_order`

現在の通常人物同期は `CAST` のみ作成・更新する。`DIRECTOR` はschema 7互換用として定義を残す。

## `tmdb_api_cache`

TMDb検索・details・credits・person search等の応答を `cache_key` 単位でJSON保存する。期限付きキャッシュは `expires_at` を超えたら再利用しない。API Read Access TokenはDBへ保存しない。

## 再インポートと整合性

JSON更新時は外部IDでUPSERTし、利用者状態を初期化しない。

必須整合性:

- `PRAGMA quick_check = ok`
- `PRAGMA foreign_key_check` エラー0
- 外部ID重複0
