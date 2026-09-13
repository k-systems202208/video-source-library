# 自宅動画ライブラリ

`mp3-source-music-library` の設計思想を引き継ぎ、手元の映画・ドラマ・アニメ動画を変更せずに索引化し、Windows PC / ブラウザ / PWA / Tailscale 経由で利用するための姉妹アプリです。

## Phase 1

Phase 1では、監査済み `video_library.json` を SQLite schema 1 へ取り込む基盤を実装します。

- 作品: 440件
- 動画: 4,869件
- `works` / `series_groups` / `videos` / `video_files`
- `users` / `user_identities`
- 作品単位お気に入り: `user_work_state`
- 動画単位お気に入り・視聴状態: `user_video_state`
- スキャン履歴・メタデータ取込履歴
- SQLite `WAL` / foreign keys
- 再インポート時に個人状態を保持
- GitHub Actions CI

## 個人データを公開しない

実際の `video_library.json` には所蔵作品、ファイル名、相対パス等が含まれるため、公開リポジトリにはコミットしません。`metadata/video_library.json` は `.gitignore` の対象です。

GitHub Actionsでは同じ **440作品 / 4,869動画 / 動画0件4作品** の規模を持つ合成データを生成して検証します。

実機では監査済みJSONをローカル配置して検証します。

```powershell
python scripts\validate_phase1.py metadata\video_library.json
```

## テスト

```powershell
python -m unittest discover -s tests -v
python scripts\validate_ci_fixture.py
```

## ドキュメント

- [基本設計](docs/00-basic-design.md)
- [DB設計](docs/01-database-design.md)
- [画面設計](docs/02-screen-design.md)
- [API設計](docs/03-api-design.md)
- [Phase 1設計・検証](docs/04-phase1-design.md)

## 正本

- 動画そのもの: ユーザー指定の動画フォルダー
- 作品メタデータ: ローカルの `video_library.json`
- 利用者・お気に入り・視聴状態: SQLite `library.db`

元動画を変更・削除・移動しないことを設計原則とします。
