# tools

`ffprobe.exe` をこのフォルダーへ置くと、PyInstallerビルド時にWindowsアプリへ同梱されます。

公開リポジトリにはFFmpeg/ffprobeの実行バイナリを含めません。理由は、配布元・ビルド構成・ライセンス条件をアプリ側で固定しないためです。

実行時の検索順は以下です。

1. `VIDEO_LIBRARY_FFPROBE` 環境変数
2. アプリ配置先の `ffprobe.exe`
3. アプリ配置先の `tools/ffprobe.exe`
4. PATH上の `ffprobe.exe` / `ffprobe`

ffprobeが見つからない場合もアプリは動作します。動画の存在確認・Range配信・視聴状態管理は継続し、技術情報の `probeStatus` が `NOT_AVAILABLE` になります。

ffprobeは解析専用です。Phase 6では動画変換・トランスコードには使用しません。
