# 自宅動画ライブラリ

`mp3-source-music-library` の設計思想を引き継ぎ、手元の映画・ドラマ・アニメ動画を変更せずに索引化し、Windows PC / ブラウザ / PWA / Tailscale 経由で利用するための姉妹アプリです。

## 現在の実装状況

### Phase 1: メタデータ / SQLite 基盤
- 監査済み `video_library.json` をSQLiteへUPSERT
- 作品440件 / 動画4,869件
- 作品・動画単位の利用者状態を分離

### Phase 2: 作品閲覧API / Web UI
- 作品一覧・詳細・series_groups・エピソードAPI
- 検索・カテゴリ・60作品単位ページング
- PC / スマートフォン向けレスポンシブUI

### Phase 3: 実ファイルスキャン / Range動画配信
- `scan_discoveries` で未登録動画 (`NEW_FILE`) を記録
- 動画ルート再帰スキャン
- `MATCHED` / `MISSING` / `NEW_FILE`
- HTTP Range (`206`, `416`)
- パストラバーサル／ルート外symlink防止
- HTML5 `<video>` によるブラウザ直接再生
- 元動画は変更・削除・移動しない

### Phase 4: 利用者状態 / 視聴進捗
- 作品お気に入りと動画お気に入りを独立管理
- 視聴済み / 未視聴の手動変更
- 再生位置・再生回数・最終再生日時を保存
- 90%以上再生または `ended` で自動視聴済み
- 「続きから見る」「次に見る」「最近見た作品」「視聴履歴」

### Phase 5: Windows運用 / Tailscale / PWA / Backup
- Windows Tkinterランチャー
- 通常起動はランチャーで実ファイルスキャンを完了してからHTTPサーバーとブラウザを起動
- local owner one-time token → `HttpOnly; SameSite=Strict` Cookie
- Tailscale Serve identityで利用者を個別識別
- serverはlocalhost (`127.0.0.1`) のみbind
- Tailscale Serveの状態確認・有効化/無効化
- PWA manifest / service worker / offline shell
- Service Workerは `/api/*`、`/video/*`、`/subtitle/*` をキャッシュしない
- SQLiteバックアップ / 復元予約 / ロールバック

### Phase 6: ffprobe / 字幕 / Windowsインストーラー
- Phase 6でSQLite schema 4を導入（現在は1.2.1 / schema 8）
- ffprobeによるコンテナ・Codec・解像度・再生時間取得
- 埋込字幕stream数取得
- 外部字幕 `.srt` / `.vtt` / `.ass` / `.ssa` を検出
- 同名 / 言語suffix字幕を安全に動画へ紐付け
- 字幕実パス・実ファイル名をAPIへ公開しない
- ランチャーから監査済み `video_library.json` を初回取込
- PyInstallerでWindowsアプリ生成
- Inno Setupでユーザー権限インストーラー生成
- GitHub Actionsでsetup.exeをartifact化

### 0.7.0: 実機スキャン診断
- Owner専用の `/diagnostics.html`
- 最新SUCCESSスキャンの `MISSING` / `NEW_FILE` / 未紐付字幕 / scan error を一覧化
- MISSINGとNEW_FILEを、サイズ・拡張子・ファイル名・親フォルダー類似度から候補提示
- 未紐付字幕に対し、安全側の動画候補を提示
- 候補にはスコア・HIGH / MEDIUM / LOW・判定理由を表示
- JSON / UTF-8 BOM付きCSVで診断結果をエクスポート
- 診断は読み取り専用。動画・字幕・DBのパスや紐付けを自動変更しない

### 0.7.1: Unicode / 文字化けパス修復
- 起動スキャン前に、メタデータの相対パスに `?` が残っている動画だけを確認
- Unicode NFKD正規化と結合文字除去を行い、`?` を1文字ワイルドカードとして実ファイル名と比較
- メタデータ側・実ファイル側の双方で1対1に一意な場合だけDBパスを実ファイル表記へ修復
- 曖昧候補は自動修復せず、従来どおり `MISSING / NEW_FILE` として診断画面に残す
- 修復するのはSQLiteの `relative_path / filename / extension` のみ。元動画・字幕は移動・改名・削除しない
- `source_subfolder` は論理グループ情報として維持
- 修復後に通常スキャンを行うため、動画再生と字幕照合も正しい実パスを利用

### 0.7.2〜0.7.9: 字幕照合・診断完成と再生・外部接続互換性改善
- 0.7.2: 同一作品内で一意に確定できる字幕だけを安全に自動紐付け
- 0.7.3: WindowsランチャーUIを音楽ライブラリと同系統へ統一
- 0.7.4: 残存字幕を安全条件の範囲で追加照合
- 0.7.5: 対応動画が登録されていない字幕を「対応動画なし」として正常系へ分離
- 0.7.6: 診断ヘッダーを「字幕判定」に変更し、紐付済みと対応動画なしを明示
- 0.7.7: 実機検証、アプリバージョン、README / Phase 6文書の整合性を整理
- 0.7.8: MKV/WebMの複数音声で日本語が存在する場合、元ファイルを変更せず配信時に日本語を優先
- 0.7.9: 動画版Tailscale ServeをHTTPS 8443へ分離し、Windowsランチャーに外部URLを開くボタンを追加

### 0.8.0: 外部字幕のブラウザ再生
- 紐付済みSRT / VTT / ASS / SSAをWebVTTとして安全に配信
- 字幕がある動画は字幕をデフォルトON
- 複数字幕では明示的な日本語字幕を優先
- 元字幕ファイル・字幕マッチングロジックは変更しない

### 0.9.0: 全動画形式の互換再生とプレイヤーモーダル
- 実ライブラリ4,869動画に存在する MKV / MP4 / AVI / WEBM / MPG / FLV 全6形式をCIで実デコード確認
- ブラウザ直接再生できない動画・音声は、初回再生時だけH.264 + AAC MP4へ変換
- 変換結果は `%LOCALAPPDATA%\VideoLibrary\PlaybackCache` へ保存し、2回目以降はキャッシュ再生
- 複数音声に日本語がある場合は日本語を優先し、ブラウザ非対応音声もAACへ変換
- 元動画は変更しない
- Windows InstallerへFFmpeg / ffprobeを同梱し、利用PCへの別途インストールは不要
- プレイヤーをモーダル化し、変換中の経過表示と再生準備失敗の明示エラーを追加

### 0.9.1: 再生キャッシュ容量管理
- WindowsランチャーにPlaybackCacheの現在容量・ファイル数・20GB上限を表示
- 20GBを超えた場合は最終利用時刻が古い変換キャッシュから自動削除
- キャッシュを再利用したときは最終利用時刻を更新し、最近使った動画を優先して保持
- ライブラリ停止中に「キャッシュをすべて削除」できる
- 手動削除・自動整理とも `%LOCALAPPDATA%\VideoLibrary\PlaybackCache` だけを対象とし、元動画・字幕・SQLite・メタデータは変更しない

### 0.9.2: v1.0前の実ライブラリ全件再生監査
- Windowsランチャーの「全件再生監査」で登録動画を実ファイル単位にffprobe解析
- コンテナ、映像Codec、全音声Codec・言語、日本語音声、外部字幕、埋め込み字幕を集計
- 各動画を `DIRECT` / `TRANSCODE` / `NO_ROUTE` に分類
- 欠損、ffprobe失敗、映像ストリームなし、FFmpeg不在を `NO_ROUTE` として明示
- JSON / CSVレポートを `%LOCALAPPDATA%\VideoLibrary\diagnostics` へ出力
- 元動画・字幕・PlaybackCache・SQLiteの利用者状態は変更しない
- v1.0受入条件は実ライブラリ4,869件で `NO_ROUTE = 0`

### 0.9.3: 全件再生監査ボタンのランチャー配置修正
- 標準ウィンドウサイズ `780x690` を維持したまま、バックアップ・全件再生監査・状態再確認を起動スキャン欄より上へ移動
- 起動スキャンのログ表示を標準サイズ向けにコンパクト化し、重要操作が画面外へ押し出されないように修正
- 全件再生監査の処理内容・レポート形式・v1.0受入条件は0.9.2から変更しない
- CIで重要操作がexpand対象の起動スキャン欄より前に配置されることを固定

### 0.9.4〜0.9.5: 全件再生監査の精度向上と元データ異常分離
- 0.9.4: DB拡張子の正規化、DIRECT decode-only、AAC 2ch正規化、ASS/SRT実体の誤登録分類を追加
- 0.9.5: 実動画の再生互換性と元ライブラリのデータ異常を別集計に分離
- `applicationNoRoute` はアプリ側の未解決再生経路だけを示す
- `sourceDataErrors` は元ファイル差し替えが必要な項目を示す
- 元データ異常だけを `playback-audit-source-errors-*.csv` に出力
- 元動画・字幕・SQLite・PlaybackCacheは監査で変更しない

### 0.9.6: 元データ異常の修復候補探索
- 元データ異常について同一フォルダー内から実動画の修復候補を読み取り専用で探索
- ffprobeで映像ストリームを持つファイルだけを候補化
- エピソード番号一致を優先し、ファイル名類似度で最大3候補を順位付け
- JSON / 元データ異常CSVへ相対パスだけを出力し、ランチャーに候補あり・なし件数を表示
- 元動画・字幕・SQLite・PlaybackCacheは自動変更しない

### 0.9.6〜0.9.7: 元データ修復候補の安全化
- 0.9.6: 元データ異常と同じフォルダーにある実動画をffprobe確認し、修復候補として最大3件提示
- 0.9.7: エピソード番号が明確に不一致な別話は修復候補から除外し、置換可能性のある候補だけを「候補あり」に集計
- 実ライブラリ24件では、0.9.6で表示された9件の候補はすべて別エピソードだったため、0.9.7の期待値は「候補あり0 / 候補なし24」
- 候補探索は読み取り専用で、元動画・字幕・SQLite・PlaybackCacheを変更しない

### 1.0.0: 正式版
- 実ライブラリ4,869登録のうち、実動画4,845件で `applicationNoRoute = 0` を実機監査で確認
- DIRECT 1,826件 / 互換変換 3,019件で、実動画4,845件すべてに再生経路を確保
- probe / decode / missing / path escape のアプリ側異常はすべて0
- 元データ異常24件は `.mkv` / `.mp4` 名だが実体がASS/SRT字幕データであり、アプリ不具合と分離
- 0.9.7実機監査で24件すべて `repairCandidateCount = 0` を確認し、別エピソードの誤候補を解消
- Tailscale Serve / PWA / 外部字幕 / 日本語音声優先 / FFmpeg互換変換 / PlaybackCache / Backup / 全件監査を正式版の基準として固定
- 元動画・字幕・SQLite利用者状態を自動変更しない方針を維持

### 1.1.0: TMDb・映画館UI・人物名鑑
- 表示バージョンは `1.1.0`
- SQLiteは当時schema 7
- 既存メタデータの `監督／演出`、`主な出演者／声優` を作品詳細に表示し、人物から登録作品を検索可能
- TMDb API Read Access TokenをBearer認証で使用し、作品照合・overview・poster/backdropを追加
- 作品matcherはversion 8。高信頼の `MATCHED` だけ画像・overviewを採用し、集約作品や構造不一致は安全側で `REVIEW / UNMATCHED`
- Web UIを「関町北映画館」のレトロ映画館デザインへ統一し、PC / Tablet / SmartphoneのPlaywright E2Eで確認
- 「主な出演者／声優」は安全にTMDb人物IDが確定した場合だけ顔写真を表示
- 人物同期version 9、人物監査version 8。実機997人の監査で未説明残件0を確認
- 「監督／演出」は名前・作品数のテキスト名鑑のみ。顔写真用TMDb人物同期は行わない
- TMDb作品画像キャッシュは `work_id + remote_path hash` で識別し、同じwork_idに残った旧別作品画像を再利用しない
- TMDb作品監査と人物監査は `%LOCALAPPDATA%\VideoLibrary\diagnostics` へJSON/CSVで保存

### 1.2.0: 作品表示設定
- 表示バージョンは `1.2.0`
- SQLiteは現行schema 8
- 作品単位で `表示する / 非表示` を設定可能
- 既存作品・新規取込作品の初期値は「表示する」
- 非表示は削除ではなく、動画・TMDb情報・お気に入り・視聴履歴を保持
- 通常の作品目録、検索、上映中、次回上映、人物名鑑、お気に入り、履歴等から非表示作品を除外
- `#/work/{id}` の直接URLは非表示作品でも開ける
- Ownerだけが作品詳細または作品目録の表示設定モードから変更可能
- 表示設定モードでは `表示中 / 非表示 / すべて` を切替え、複数作品を一括表示／非表示可能
- metadata再取込では `is_visible` を上書きせず、設定を保持
- PWA shellは `video-library-shell-v5`


### 1.2.1: 表示設定をWindowsランチャーへ移動（現行）
- 表示バージョンは `1.2.1`
- SQLite schema 8を維持
- Windowsランチャーに「表示設定」ボタンを追加
- 登録済み全作品をチェックリストで表示し、チェックされた作品だけをブラウザへ表示
- 「すべて選択 / すべて解除」チェックボックスで全件を一括切替
- 保存時にチェック状態をDBへ一括反映
- ブラウザから表示／非表示を変更するUIとAPIは撤去
- 非表示作品は作品詳細・動画詳細・動画配信・字幕・作品画像もブラウザから取得不可
- metadata再取込でも `is_visible` は保持
- PWA shellは `video-library-shell-v6`

対象動画拡張子: `.mkv`, `.mp4`, `.avi`, `.webm`, `.mpg`, `.flv`, `.m4v`, `.mov`, `.wmv`

## ffmpeg / ffprobe

ffprobeはCodec・音声トラック解析に使用し、ffmpegはブラウザ非互換動画を再生用MP4へ変換します。0.9.0以降のWindows Installerには両方を同梱します。

検索順:

1. `VIDEO_LIBRARY_FFPROBE` 環境変数
2. アプリ配置先 `ffprobe.exe`
3. アプリ配置先 `tools\ffprobe.exe`
4. PATH

ffprobeが見つからなくても動画一覧・再生・視聴状態管理は利用できます。技術情報だけ `NOT_AVAILABLE` になります。

公開リポジトリにはFFmpeg/ffprobeバイナリをコミットしません。Installer CIで実バイナリを一時配置し、生成するWindowsアプリへ同梱します。

直接再生判定は安全側です。

- MP4/M4V + H.264 + AAC/MP3 → `DIRECT`
- WebM + VP8/VP9/AV1 + Opus/Vorbis → `DIRECT`
- HEVC、MKV等 → `UNKNOWN`

`UNKNOWN` はファイル破損ではなく「ブラウザ直接再生を保証しない」という意味です。0.9.0ではこの場合もFFmpeg互換再生へフォールバックします。

## 字幕

対象:

- `.srt`
- `.vtt`
- `.ass`
- `.ssa`

自動紐付け例:

```text
movie.mkv
movie.srt
movie.ja.srt
movie.jpn.forced.srt
movie.en.default.vtt
```

`movie.commentary.srt` のように意味推測が必要な名前は自動紐付けしません。こうした字幕はスキャン診断画面で候補を確認できますが、自動紐付けはしません。

0.8.0で紐付済み外部字幕のブラウザ再生を実装しました。SRT / ASS / SSAは配信時にWebVTTへ変換し、VTTは正規化して配信します。字幕が1件以上ある動画は優先字幕をデフォルトONにし、再生中はブラウザ標準コントロールからOFF・切替できます。元字幕ファイルは変更しません。

## Windowsでの通常利用

### インストーラー版

CI / Releaseで生成された `VideoLibrary-<version>-setup.exe` を実行します。管理者権限は不要です。

インストール先:

```text
%LOCALAPPDATA%\Programs\VideoLibrary
```

利用者データ:

```text
%LOCALAPPDATA%\VideoLibrary
├─ library.db
├─ config.json
├─ runtime.json
├─ metadata\video_library.json
├─ PlaybackCache\
├─ TMDbImages\
├─ diagnostics\
├─ Backups\
└─ Logs\
```

アンインストールしても利用者データは削除しません。

初回はランチャーで:

1. 動画フォルダーを選択
2. 監査済み `video_library.json` を選択
3. 「取込」
4. 「ライブラリを開始」
5. Windowsランチャー上で動画・字幕・ffprobeの起動スキャン進捗を確認
6. スキャン完了後にブラウザが自動起動

と進めます。

2回目以降は動画フォルダーとDBが有効なら、ランチャー起動後に自動で起動スキャンを開始します。ブラウザはスキャン完了前には開きません。起動後の追加・変更確認には、ブラウザ側の「再スキャン」と進捗モーダルを利用できます。

0.7.1以降、起動スキャン前にメタデータ側に残った `?` 文字化けパスを安全に確認します。一意に対応する実ファイルだけDBのパスを修復してから通常スキャンへ進みます。

### スキャン診断

メイン画面右上の「診断」からOwner専用診断画面を開けます。最新の成功スキャンについて、MISSING / NEW_FILE / 未紐付字幕 / 対応動画なし / 未対応字幕 / エラーと候補を確認できます。

診断画面は読み取り専用です。候補を見つけてもファイル移動、ファイル名変更、DBパス更新、字幕紐付けは自動実行しません。必要な修正ルールを人が確認してから別工程で適用します。

診断API:

```text
GET /api/admin/scan-diagnostics
GET /api/admin/scan-diagnostics.json
GET /api/admin/scan-diagnostics.csv
```

3つともOwner専用です。

### ソースから起動

```powershell
python windows-installer\src\launcher.py
```

開発用直接起動:

```powershell
python windows-installer\src\server.py --database library.db --video-root "D:\Videos"
```

control secretなしの直接起動はテスト／開発用localhost owner互換モードです。通常利用はランチャーを使用してください。

## 認証と外部接続

### localhost owner
ランチャーが短寿命ワンタイムトークンを作成し、ブラウザで1回だけ交換してowner Cookieを発行します。control secretはブラウザへ渡しません。

### Tailscale
Tailscale Serveが付与する本人情報を `user_identities` へ紐付けます。利用者ごとのお気に入り・視聴位置・履歴は混ざりません。

同一PCの音楽版と競合しないよう、動画版はHTTPS 8443を使用します。動画版の外部URLは `https://<PC名>.<tailnet>.ts.net:8443/` です。Windowsランチャーの「外部URLを開く」から既定ブラウザで開けます。

外部公開はTailscale Serveのみを前提とします。ルーターのポート開放、DMZ、Tailscale Funnelは使用しません。

## PWA
PWAがキャッシュするのはHTML/manifest/icon/offline shell等のアプリシェルのみです。

以下はService Workerのキャッシュ対象外です。
- `/api/*`
- `/video/*`
- `/subtitle/*`
- `/tmdb-image/*`
- `/tmdb-person-image/*`
- SQLite
- `video_library.json`
- 視聴履歴などの個人状態

PWA shellは `video-library-shell-v6`。更新時は旧shell cacheを削除し、manifest / offline shell / iconを現行版へ切り替えます。

## バックアップ・復元

ランチャーまたはAPIからSQLiteバックアップを作成できます。バックアップ作成後は `PRAGMA quick_check` とschemaを検証します。

復元は稼働中DBを直接置換せず予約制です。次回ランチャー起動時に現DBを `library-pre-restore-*.db` へ退避してから復元し、失敗時はロールバックします。

## 実機総合検証

実動画はCIへアップロードせず、PC上で次を実行します。

```powershell
python scripts\validate_real_library.py `
  --database "$env:LOCALAPPDATA\VideoLibrary\library.db" `
  --video-root "D:\Videos" `
  --metadata "C:\path\video_library.json" `
  --expected-works 440 `
  --expected-videos 4869 `
  --expected-subtitles 1234 `
  --expected-matched-subtitles 1227 `
  --expected-orphan-subtitles 7 `
  --expected-unsupported-subtitles 3
```

440作品 / 4,869動画、対応字幕1,234件（紐付1,227件・対応動画なし7件）、未対応字幕3件、SQLite整合性、MISSING / NEW_FILE / 真の未紐付字幕 / 診断エラー / ffprobeエラーをまとめて確認します。対応動画なし7件は正常系として扱います。0.7.1以降、この実機検証も起動時と同じ文字化けパス修復を先に適用します。

0.9.2ではさらに、Windowsランチャーでライブラリを停止してから「全件再生監査」を実行します。全登録動画をffprobeで解析し、`DIRECT` / `TRANSCODE` / `NO_ROUTE`、音声トラック、日本語音声、外部字幕、埋め込み字幕をJSON/CSVへ記録します。v1.0受入条件は4,869件すべてが監査対象となり、`NO_ROUTE = 0` であることです。

## 個人データを公開しない
実際の `video_library.json`、実動画、実字幕は公開リポジトリ／CIへ含めません。CIでは同じ **440作品 / 4,869動画 / 動画0件4作品** の合成データを使用します。

## テスト

```powershell
python -m unittest discover -s tests -v
python scripts\validate_ci_fixture.py
```

Windowsインストーラー:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows-installer\build\build.ps1
```

CIはWindows / Python 3.11・3.13です。全テスト成功後にWindowsインストーラーも生成します。

## ドキュメント

### 現在仕様
- [基本設計](docs/00-basic-design.md)
- [DB設計](docs/01-database-design.md)
- [画面設計](docs/02-screen-design.md)
- [API設計](docs/03-api-design.md)
- [TMDb作品照合・ポスター／背景画像](docs/42-1.1.0-tmdb-matching-images.md)
- [人物名鑑ナビゲーション](docs/59-1.1.0-navigation-people-menu.md)
- [主な出演者／声優 顔写真](docs/67-1.1.0-cast-voice-profile-images-phase1.md)
- [人物監査の残件resolution](docs/76-1.1.0-people-audit-residual-resolution.md)
- [監督／演出 顔写真機能の撤回](docs/77-1.1.0-director-profile-images-withdrawn.md)
- [TMDb作品画像キャッシュ識別修正](docs/78-1.1.0-tmdb-image-cache-identity.md)
- [1.1.0 ソース・ドキュメント最終整合性監査](docs/79-1.1.0-final-consistency-audit.md)
- [1.1.0 正式リリースノート](docs/80-1.1.0-release.md)
- [1.2.0 作品表示設定](docs/81-1.2.0-work-visibility.md)
- [1.2.0 正式リリースノート](docs/82-1.2.0-release.md)
- [1.2.1 Windowsランチャー表示設定](docs/83-1.2.1-launcher-work-visibility.md)
- [1.2.1 正式リリースノート](docs/84-1.2.1-release.md)

### 実装履歴
Phase別・バージョン別の詳細記録は `docs/` 配下に保持します。過去時点の設計判断を残すため、履歴文書は現在仕様へ機械的に書き換えません。

## 正本
- 動画そのもの: ユーザー指定の動画フォルダー
- 作品メタデータ: ローカルの `video_library.json`
- 利用者状態: SQLite `library.db`

元動画・字幕を変更・削除・移動しないことを設計原則とします。

## TMDb作品照合・人物画像（1.1.0）

ランチャーの `TMDb設定` でAPI Read Access Tokenを設定すると、ライブラリ停止中に `TMDb同期` を実行できます。

作品名・年・種別から保守的に照合し、matcher version 8で安全に確定した `MATCHED` だけを作品情報の補助として利用します。

- overview
- poster
- backdrop
- 主な出演者／声優のTMDb人物IDとprofile image

低信頼候補、複数作品をまとめたローカル作品、ローカル/TMDb構造が1対1でない作品は `REVIEW` / `UNMATCHED` を維持します。

作品画像は `%LOCALAPPDATA%\VideoLibrary\TMDbImages` に保存します。キャッシュ名は現在のTMDb `remote_path` のhashを含むため、TMDbリンク修正後に同じwork_idの古い別作品画像を再利用しません。ブラウザへは `/tmdb-image/poster/{workId}` / `backdrop` の同一origin URLだけを返します。

主な出演者／声優の顔写真は `/tmdb-person-image/{personId}` から表示します。監督／演出はテキスト名鑑のみで、顔写真は表示しません。

監査レポート:
- `tmdb-match-audit-*.json/.csv`
- `tmdb-people-audit-*.json/.csv`

保存先は `%LOCALAPPDATA%\VideoLibrary\diagnostics` です。TMDb未設定や通信失敗でも、ローカルメタデータ、動画再生、字幕、利用者状態は利用できます。

TMDB attribution: This product uses the TMDB API but is not endorsed or certified by TMDB.
