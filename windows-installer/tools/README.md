# tools

`ffmpeg.exe` と `ffprobe.exe` をこのフォルダーへ置くと、PyInstallerビルド時にWindowsアプリへ同梱されます。

公開リポジトリにはFFmpeg/ffprobeの実行バイナリをコミットしません。GitHub ActionsのWindows InstallerジョブではChocolateyのFFmpegパッケージから実バイナリを一時配置し、生成するインストーラーへ同梱します。

実行時の検索順は以下です。

1. `VIDEO_LIBRARY_FFMPEG` / `VIDEO_LIBRARY_FFPROBE` 環境変数
2. アプリ配置先の `ffmpeg.exe` / `ffprobe.exe`
3. アプリ配置先の `tools/ffmpeg.exe` / `tools/ffprobe.exe`
4. PATH上のFFmpeg / ffprobe

ffprobeは動画Codec解析に使用します。ffmpegはAVI / MKV / MPG / FLVなど、ブラウザが直接再生できない動画や非対応音声を、元動画を変更せずH.264 + AAC MP4の再生キャッシュへ変換するために使用します。
