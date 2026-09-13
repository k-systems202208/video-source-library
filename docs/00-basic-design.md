# 自宅動画ライブラリ v1.0 基本設計

## 目的
PCに保存している映画・国内ドラマ・海外ドラマ・アニメ等を索引化し、PC・スマートフォン・タブレットから検索・閲覧・再生・視聴状態管理できる家庭向け動画ライブラリを構築する。

## 基本原則
- 元動画を変更・削除・移動・自動変換しない。
- 動画の存在は動画フォルダーを正本とする。
- 作品名、シリーズ、話数、サブタイトル、監督、出演者等はローカルの `video_library.json` を作品マスターとする。
- お気に入り、視聴済み、再生位置、再生回数、利用者情報はSQLiteを正本とする。
- 外部利用はTailscale Serveを正式経路とし、HTTPサーバーはlocalhostへbindする。
- PWAはUIシェルのみキャッシュし、動画/API/DB/個人状態はキャッシュしない。

## 技術構成
Python / SQLite / HTML・CSS・JavaScript / PWA / Tailscale Serve / Tkinter / PyInstaller / Inno Setup を基本とする。

## 段階導入
1. Phase 1: JSON→SQLite基盤
2. Phase 2: 作品詳細・シリーズ・エピソード
3. Phase 3: Range配信・ブラウザ再生
4. Phase 4: 利用者・再生位置・視聴状態
5. Phase 5: Tailscale / PWA / Windowsインストーラー
6. Phase 6: 総合試験・Release

FFmpeg/HLSはv1.0の必須範囲に含めず、直接再生できない動画への後続対応とする。
