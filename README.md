# 自宅動画ライブラリ

`mp3-source-music-library` の設計思想を引き継ぎ、手元の映画・ドラマ・アニメ動画を変更せずに索引化し、Windows PC / ブラウザ / PWA / Tailscale 経由で利用するための姉妹アプリです。

## 現在の実装状況

### Phase 1: メタデータ / SQLite 基盤
- 監査済み `video_library.json` を SQLite へUPSERT
- 作品440件 / 動画4,869件
- 作品・動画単位の利用者状態を分離

### Phase 2: 作品閲覧API / Web UI
- 作品一覧・詳細・series_groups・エピソードAPI
- 検索・カテゴリ・60作品単位ページング
- PC / スマートフォン向けレスポンシブUI

### Phase 3: 実ファイルスキャン / Range動画配信
- SQLite schema 2
- `scan_discoveries` で未登録動画 (`NEW_FILE`) を記録
- 動画ルート再帰スキャン
- `MATCHED` / `MISSING` / `NEW_FILE`
- `GET /api/scan/status` / `POST /api/scan`
- `GET /video/{videoId}`
- HTTP Range (`206`, `416`)
- パストラバーサル／ルート外symlink防止
- HTML5 `<video>` によるブラウザ直接再生
- 元動画は変更・削除・移動しない

対象拡張子: `.mkv`, `.mp4`, `.avi`, `.webm`, `.mpg`, `.flv`, `.m4v`, `.mov`, `.wmv`

MP4 / M4V / WebM は拡張子ベースで `DIRECT`、その他は `UNKNOWN` とします。Codec判定は後続Phaseで `ffprobe` を導入して精度を上げます。

## ローカル起動
```powershell
python windows-installer\src\metadata_importer.py metadata\video_library.json --database library.db
python windows-installer\src\server.py --database library.db --video-root "D:\Videos"
```

または `%LOCALAPPDATA%\VideoLibrary\config.json`:
```json
{"videoRoot":"D:\\Videos"}
```

ブラウザ: `http://127.0.0.1:8765/`

## 個人データを公開しない
実際の `video_library.json` と実動画は公開リポジトリ／CIへ含めません。CIでは同じ **440作品 / 4,869動画 / 動画0件4作品** の合成データを使用します。

## テスト
```powershell
python -m unittest discover -s tests -v
python scripts\validate_ci_fixture.py
```
CIはWindows / Python 3.11・3.13です。

## ドキュメント
- [基本設計](docs/00-basic-design.md)
- [DB設計](docs/01-database-design.md)
- [画面設計](docs/02-screen-design.md)
- [API設計](docs/03-api-design.md)
- [Phase 1](docs/04-phase1-design.md)
- [Phase 2](docs/05-phase2-implementation.md)
- [Phase 3](docs/06-phase3-implementation.md)

## 正本
- 動画そのもの: ユーザー指定の動画フォルダー
- 作品メタデータ: ローカルの `video_library.json`
- 利用者状態: SQLite `library.db`

元動画を変更・削除・移動しないことを設計原則とします。
