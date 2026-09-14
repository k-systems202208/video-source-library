from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch(path, old, new, label):
    p = ROOT / path
    text = p.read_text(encoding='utf-8')
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'{label}: expected 1 match, got {count}')
    p.write_text(text.replace(old, new, 1), encoding='utf-8')


# Make preparation status visible before the potentially long HEAD/transcode request.
patch(
    'windows-installer/src/video-library.html',
    "d.append(details);\n  if(v.file.available){",
    "d.append(details);b.replaceChildren(d);\n  if(v.file.available){",
    'show modal content before preflight',
)

# Full-screen modal on phones.
patch(
    'windows-installer/src/video-library.html',
    '@media(max-width:700px){header{',
    '@media(max-width:700px){.player-modal{padding:0}.player-dialog{width:100%;height:100dvh;max-height:none;border-radius:0;padding:12px}.player-modal .player{max-height:65vh}header{',
    'mobile modal css',
)

# README: document 0.9.0 and bundled FFmpeg playback behavior.
readme = ROOT / 'README.md'
text = readme.read_text(encoding='utf-8')
anchor = '''### 0.8.0: 外部字幕のブラウザ再生
- 紐付済みSRT / VTT / ASS / SSAをWebVTTとして安全に配信
- 字幕がある動画は字幕をデフォルトON
- 複数字幕では明示的な日本語字幕を優先
- 元字幕ファイル・字幕マッチングロジックは変更しない

'''
addition = anchor + '''### 0.9.0: 全動画形式の互換再生とプレイヤーモーダル
- 実ライブラリ4,869動画に存在する MKV / MP4 / AVI / WEBM / MPG / FLV 全6形式をCIで実デコード確認
- ブラウザ直接再生できない動画・音声は、初回再生時だけH.264 + AAC MP4へ変換
- 変換結果は `%LOCALAPPDATA%\\VideoLibrary\\PlaybackCache` へ保存し、2回目以降はキャッシュ再生
- 複数音声に日本語がある場合は日本語を優先し、ブラウザ非対応音声もAACへ変換
- 元動画は変更しない
- Windows InstallerへFFmpeg / ffprobeを同梱し、利用PCへの別途インストールは不要
- プレイヤーをモーダル化し、変換中の経過表示と再生準備失敗の明示エラーを追加

'''
if text.count(anchor) != 1:
    raise RuntimeError('README 0.8.0 anchor mismatch')
text = text.replace(anchor, addition, 1)
text = text.replace('## ffprobe\n\nffprobeは解析専用です。動画変換・トランスコードには使用しません。', '## ffmpeg / ffprobe\n\nffprobeはCodec・音声トラック解析に使用し、ffmpegはブラウザ非互換動画を再生用MP4へ変換します。0.9.0のWindows Installerには両方を同梱します。', 1)
text = text.replace('公開リポジトリにはffprobeバイナリを含めません。`windows-installer\\tools\\ffprobe.exe` を配置してビルドした場合はアプリへ同梱します。', '公開リポジトリにはFFmpeg/ffprobeバイナリをコミットしません。Installer CIで実バイナリを一時配置し、生成するWindowsアプリへ同梱します。', 1)
text = text.replace('`UNKNOWN` はファイル破損ではなく「ブラウザ直接再生を保証しない」という意味です。', '`UNKNOWN` はファイル破損ではなく「ブラウザ直接再生を保証しない」という意味です。0.9.0ではこの場合もFFmpeg互換再生へフォールバックします。', 1)
readme.write_text(text, encoding='utf-8')

# Real FFmpeg test for Japanese second audio track selection.
script = ROOT / 'scripts' / 'validate_playback_formats.py'
text = script.read_text(encoding='utf-8')
anchor = '''        print("Playback format CI: all real-library extensions are playable")
'''
block = '''        dual = root / "dual-audio-japanese-second.mkv"
        _run([
            ffmpeg,
            "-nostdin", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=12",
            "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000",
            "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=48000",
            "-t", "0.7",
            "-map", "0:v:0", "-map", "1:a:0", "-map", "2:a:0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "flac",
            "-metadata:s:a:0", "language=eng",
            "-metadata:s:a:1", "language=jpn",
            str(dual),
        ])
        dual_video, dual_audio = _probe(ffprobe_path, dual)
        dual_prepared = prepare_browser_playback(
            dual, ".mkv", dual_video, dual_audio, cache, ffmpeg_path=ffmpeg
        )
        out_video, out_audio = _probe(ffprobe_path, dual_prepared.path)
        if out_video != "h264" or out_audio != "aac" or dual_prepared.audio_language != "ja":
            raise AssertionError(
                f"Japanese second audio was not selected/transcoded: {out_video}+{out_audio} lang={dual_prepared.audio_language}"
            )
        language_payload = json.loads(_run([
            ffprobe_path, "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream_tags=language", "-of", "json",
            str(dual_prepared.path),
        ]).stdout.decode("utf-8"))
        audio_streams = language_payload.get("streams") or []
        language = str(((audio_streams[0].get("tags") or {}).get("language") if audio_streams else "") or "").casefold()
        if language not in {"jpn", "ja"}:
            raise AssertionError(f"Japanese language tag missing after transcode: {language!r}")
        _run([
            ffmpeg, "-nostdin", "-v", "error", "-i", str(dual_prepared.path),
            "-map", "0:v:0", "-map", "0:a:0", "-t", "0.2", "-f", "null", "-",
        ])
        results.append("DUAL  Japanese second audio -> TRANSCODE h264+aac (jpn)")

        print("Playback format CI: all real-library extensions are playable")
'''
if text.count(anchor) != 1:
    raise RuntimeError('playback CI print anchor mismatch')
script.write_text(text.replace(anchor, block, 1), encoding='utf-8')

print('Issue #59 follow-up patches applied')
