# Phase 3 実装・検証

## 目的
監査済みJSONと実際の動画保存フォルダーを照合し、元動画を変更せずにブラウザへRange配信できる状態を作る。

## 設定
`app_config.py` が `%LOCALAPPDATA%\VideoLibrary\config.json` の `videoRoot` を読み込む。`--video-root` 指定時はコマンドライン値を優先する。APIには絶対パスを返さない。

## スキャン
- JSONと相対パス一致: `MATCHED`, `is_available = 1`
- JSONにあるが実ファイルなし: `MISSING`, `is_available = 0`
- 実ファイルはあるがJSONにない: `scan_discoveries` へ `NEW_FILE`

`file_size`, `modified_time_ns`, `last_scanned_at` を保存する。元動画へのwrite / rename / move / deleteは行わない。

## Path安全性
`..`, 絶対パス, ドライブ付きパス, 動画ルート外へ解決されるsymlinkを拒否する。配信は `videoId -> DB relative_path -> video_root` でのみ解決する。

## Range配信
`GET /video/{videoId}` はRangeなし200、有効な単一Range 206、不正Range 416。`Accept-Ranges: bytes` と `Content-Range` に対応し、チャンク単位で送信する。

## Web UI
`file.available = true` の動画だけHTML5 `<video>` を生成する。MP4 / M4V / WebMは `DIRECT`、その他は `UNKNOWN` とし、UNKNOWNを破損扱いしない。

## Schema 2
未登録実ファイルには `video_id` がないため `video_files` に無理に登録せず `scan_discoveries` を追加する。

## 自動テスト
schema 2 migration、MATCHED/MISSING/NEW_FILE、欠落時の利用者状態保持、path traversal拒否、config、Range 200/206/416、scan API、絶対パス非公開、UIプレーヤーを検証する。既存Phase 1/2と440/4,869 fixtureも継続実行する。
