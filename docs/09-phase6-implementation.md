# Phase 6 実装

## 目的

v1.0完成前の最終基盤として、実動画の技術情報取得、外部字幕ファイルの検出・紐付け、Windowsインストーラー生成、実機総合検証手順を追加する。

## SQLite schema 4

Phase 6ではschema 4へ移行する。既存DBを作り直さずmigrationする。

### video_files追加項目

- `embedded_subtitle_count`
- `probe_status`
- `probed_at`

既存の以下の列をffprobe結果で更新する。

- `duration_ms`
- `container_format`
- `video_codec`
- `audio_codec`
- `width`
- `height`
- `playback_support`

### subtitles

外部字幕ファイルを保持する。

- `video_id`
- `relative_path`
- `filename`
- `extension`
- `language`
- `is_forced`
- `is_default`
- `match_method`
- `file_size`
- `modified_time_ns`
- `is_available`
- `last_scanned_at`

相対パスはDB内部だけに保持し、APIへ返さない。

## ffprobe

解析対象:

- コンテナ
- 映像Codec
- 音声Codec
- 解像度
- 再生時間
- 埋込字幕stream数

ffprobeは解析専用で、動画変換・トランスコードには使用しない。

検索順:

1. `VIDEO_LIBRARY_FFPROBE`
2. アプリ直下 `ffprobe.exe`
3. アプリ `tools/ffprobe.exe`
4. PATH

見つからなくてもアプリは継続動作し、`probe_status=NOT_AVAILABLE` とする。

公開リポジトリにはffprobeバイナリを含めない。ビルド時に `windows-installer/tools/ffprobe.exe` が存在する場合のみPyInstallerへ同梱する。

## ブラウザ直接再生判定

Phase 6では拡張子だけでなくCodecを考慮する。

- MP4/M4V + H.264 + AAC/MP3: `DIRECT`
- WebM + VP8/VP9/AV1 + Opus/Vorbis: `DIRECT`
- HEVC、MKV等: `UNKNOWN`

`UNKNOWN` は破損を意味しない。ブラウザ直接再生保証外を示す。

## 外部字幕

対象:

- `.srt`
- `.vtt`
- `.ass`
- `.ssa`

自動紐付けは安全側に限定する。

### 自動紐付けする例

```text
movie.mkv
movie.srt
movie.ja.srt
movie.jpn.forced.srt
movie.en.default.vtt
```

### 自動紐付けしない例

```text
movie.commentary.srt
unknown-subtitle.srt
```

推測が必要な字幕は `UNMATCHED` とし、別作品へ誤紐付けしない。

Phase 6では字幕の検出・関連付け・画面表示までを対象とする。SRT/ASSをWebVTTへ変換してブラウザプレーヤーへ表示する機能は後続対象。

## Windowsランチャー

Phase 6で初回セットアップを成立させるため、ランチャーへ次を追加する。

- 動画フォルダー選択
- `video_library.json` 選択
- メタデータJSON取込
- SQLiteへのUPSERT
- ffprobe検出状態表示

実 `video_library.json` は公開リポジトリや公開インストーラーへ含めない。

## Windowsインストーラー

### PyInstaller

`windows-installer/build/VideoLibrary.spec`

以下を含むonedirアプリを生成する。

- Python runtime
- Tkinter launcher
- HTTP server/API
- Web UI/PWA shell
- SQLite処理
- Tailscale処理
- backup/restore
- ffprobe解析ロジック

### Inno Setup

`windows-installer/installer/VideoLibrary.iss`

インストール先:

```text
%LOCALAPPDATA%\Programs\VideoLibrary
```

管理者権限不要。

ユーザーデータは以下へ保存し、アンインストール時にも削除しない。

```text
%LOCALAPPDATA%\VideoLibrary
```

## CI

Windows / Python 3.11・3.13でPhase 1〜6の回帰テストを実行する。

テスト成功後、Python 3.13で:

1. PyInstaller build
2. Inno Setup build
3. `VideoLibrary.exe` 存在確認
4. `VideoLibrary-0.6.0-setup.exe` 存在確認
5. Actions artifactへsetup.exeを保存

## 実機総合検証

`scripts/validate_real_library.py` を使用する。

例:

```powershell
python scripts\validate_real_library.py `
  --database "$env:LOCALAPPDATA\VideoLibrary\library.db" `
  --video-root "D:\Videos" `
  --metadata "C:\path\video_library.json" `
  --expected-works 440 `
  --expected-videos 4869 `
  --expected-subtitles 1237
```

確認内容:

- SQLite quick_check
- foreign_key_check
- 440作品
- 4,869動画
- 全動画存在
- 字幕1,237件
- 未紐付字幕0
- ffprobeエラー0（ffprobe利用時）

実動画・実字幕はCIへアップロードしない。
