# Phase 1 設計・検証

## 目的
監査済み `video_library.json` を検証し、SQLite schema 1へ安全に取り込む基盤を作る。

## 完成条件
- 440作品を登録できる
- 4,869動画を登録できる
- `video_files` も4,869件生成される
- 動画0件4作品を作品マスターとして保持する
- `user_work_state` と `user_video_state` を分離する
- JSON再インポートで個人状態を消さない
- `PRAGMA quick_check = ok`
- `PRAGMA foreign_key_check` エラー0

## 公開CIと実データの分離
実データJSONには利用者の所蔵作品、ファイル名、相対パス等が含まれるため公開GitHubには載せない。

GitHub Actionsでは同一規模の合成データを実行時生成し、440作品 / 4,869動画 / 動画0件4作品の取り込みと再インポート互換性を検証する。

実データはローカルのみで次を実行する。

```powershell
python scripts\validate_phase1.py metadata\video_library.json
```

## 動画0件作品
監査済み実データでは4作品が該当する。作品の存在と動画ファイルの存在を分離し、0件でも `works` に保持する。
