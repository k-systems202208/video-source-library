from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


# 1) Runtime playback compatibility layer.
playback = r'''from __future__ import annotations

import functools
import hashlib
import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from media_probe import find_ffprobe

REAL_LIBRARY_VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".webm", ".mpg", ".flv"}


@dataclass(frozen=True)
class PlaybackPreparation:
    path: Path
    content_type: str
    transcoded: bool
    audio_language: str | None = None


@dataclass(frozen=True)
class AudioSelection:
    stream_index: int
    codec: str
    language: str
    japanese: bool
    first_audio: bool


_TRANSCODE_LOCKS: dict[str, threading.Lock] = {}
_TRANSCODE_LOCKS_GUARD = threading.Lock()


def find_ffmpeg(explicit: Path | str | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env_value = os.environ.get("VIDEO_LIBRARY_FFMPEG")
    if env_value:
        candidates.append(Path(env_value).expanduser())

    here = Path(__file__).resolve().parent
    candidates.extend(
        [
            here / "ffmpeg.exe",
            here / "tools" / "ffmpeg.exe",
            here.parent / "tools" / "ffmpeg.exe",
        ]
    )
    found = shutil.which("ffmpeg.exe") or shutil.which("ffmpeg")
    if found:
        candidates.append(Path(found))

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file():
            return resolved
    return None


def browser_direct_playback(extension: str, video_codec: str | None, audio_codec: str | None) -> bool:
    ext = extension.casefold()
    video = (video_codec or "").casefold()
    audio = (audio_codec or "").casefold()

    if ext in {".mp4", ".m4v"}:
        return video in {"h264", "avc", "avc1"} and (not audio or audio in {"aac", "mp3"})
    if ext == ".webm":
        return video in {"vp8", "vp9", "av1"} and (not audio or audio in {"opus", "vorbis"})
    return False


def _is_japanese(language: str, title: str) -> bool:
    lang = language.casefold().replace("_", "-").strip()
    if lang in {"ja", "jp", "jpn", "japanese"} or lang.startswith(("ja-", "jpn-")):
        return True
    lowered = title.casefold()
    return "japanese" in lowered or "日本語" in title


@functools.lru_cache(maxsize=512)
def _cached_audio_selection(path_text: str, size: int, mtime_ns: int, ffprobe_text: str) -> AudioSelection | None:
    del size, mtime_ns
    command = [
        ffprobe_text,
        "-v", "error",
        "-print_format", "json",
        "-show_streams",
        path_text,
    ]
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30.0,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    streams = payload.get("streams") if isinstance(payload, dict) else None
    if not isinstance(streams, list):
        return None

    audio: list[AudioSelection] = []
    for stream in streams:
        if not isinstance(stream, dict) or stream.get("codec_type") != "audio":
            continue
        tags = stream.get("tags") if isinstance(stream.get("tags"), dict) else {}
        language = str(tags.get("language") or "").strip()
        title = str(tags.get("title") or tags.get("handler_name") or "").strip()
        codec = str(stream.get("codec_name") or "").strip().casefold()
        try:
            index = int(stream.get("index"))
        except (TypeError, ValueError):
            continue
        audio.append(
            AudioSelection(
                stream_index=index,
                codec=codec,
                language=language,
                japanese=_is_japanese(language, title),
                first_audio=len(audio) == 0,
            )
        )
    if not audio:
        return None
    return next((item for item in audio if item.japanese), audio[0])


def preferred_audio_selection(source: Path | str, *, ffprobe_path: Path | str | None = None) -> AudioSelection | None:
    src = Path(source).resolve()
    probe = find_ffprobe(ffprobe_path)
    if probe is None:
        return None
    try:
        stat = src.stat()
    except OSError:
        return None
    return _cached_audio_selection(str(src), int(stat.st_size), int(stat.st_mtime_ns), str(probe))


def _cache_target(source: Path, cache_dir: Path) -> Path:
    stat = source.stat()
    key = f"{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8", errors="surrogatepass")
    digest = hashlib.sha256(key).hexdigest()[:24]
    return cache_dir / f"{digest}.mp4"


def _target_lock(target: Path) -> threading.Lock:
    key = str(target.resolve())
    with _TRANSCODE_LOCKS_GUARD:
        lock = _TRANSCODE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _TRANSCODE_LOCKS[key] = lock
        return lock


def transcode_to_browser_mp4(
    source: Path | str,
    cache_dir: Path | str,
    *,
    ffmpeg_path: Path | str | None = None,
    ffprobe_path: Path | str | None = None,
    timeout_seconds: float = 3600.0,
) -> tuple[Path, str | None]:
    src = Path(source).resolve()
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    target = _cache_target(src, cache)
    selection = preferred_audio_selection(src, ffprobe_path=ffprobe_path)
    audio_language = "ja" if selection is not None and selection.japanese else (selection.language or None if selection else None)

    with _target_lock(target):
        if target.is_file() and target.stat().st_size > 0:
            return target, audio_language

        executable = find_ffmpeg(ffmpeg_path)
        if executable is None:
            raise RuntimeError("FFmpegが見つかりません。互換再生にはFFmpegが必要です。")

        temporary = target.with_name(target.stem + ".partial.mp4")
        try:
            if temporary.exists():
                temporary.unlink()
            audio_map = f"0:{selection.stream_index}" if selection is not None else "0:a:0?"
            command = [
                str(executable),
                "-nostdin", "-y", "-v", "error",
                "-i", str(src),
                "-map", "0:v:0",
                "-map", audio_map,
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
            ]
            if selection is not None and selection.japanese:
                command.extend(["-metadata:s:a:0", "language=jpn"])
            command.extend(["-movflags", "+faststart", str(temporary)])
            try:
                completed = subprocess.run(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                    timeout=timeout_seconds,
                    creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("再生用動画の変換が1時間以内に完了しませんでした。") from exc
            if completed.returncode != 0 or not temporary.is_file() or temporary.stat().st_size <= 0:
                message = completed.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(message[:2000] or f"ffmpeg exit code {completed.returncode}")
            temporary.replace(target)
            return target, audio_language
        finally:
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass


def prepare_browser_playback(
    source: Path | str,
    extension: str,
    video_codec: str | None,
    audio_codec: str | None,
    cache_dir: Path | str,
    *,
    ffmpeg_path: Path | str | None = None,
    ffprobe_path: Path | str | None = None,
) -> PlaybackPreparation:
    src = Path(source).resolve()
    ext = extension.casefold()
    selection = preferred_audio_selection(src, ffprobe_path=ffprobe_path)
    effective_audio = selection.codec if selection is not None else audio_codec
    requires_track_selection = bool(selection is not None and selection.japanese and not selection.first_audio)

    if browser_direct_playback(ext, video_codec, effective_audio) and not requires_track_selection:
        content_type = "video/webm" if ext == ".webm" else "video/mp4"
        return PlaybackPreparation(
            path=src,
            content_type=content_type,
            transcoded=False,
            audio_language="ja" if selection is not None and selection.japanese else (selection.language or None if selection else None),
        )

    target, language = transcode_to_browser_mp4(
        src,
        cache_dir,
        ffmpeg_path=ffmpeg_path,
        ffprobe_path=ffprobe_path,
    )
    return PlaybackPreparation(path=target, content_type="video/mp4", transcoded=True, audio_language=language)
'''
write("windows-installer/src/playback_compat.py", playback)


# 2) Wire compatibility preparation into /video/<id> before Range streaming.
server = read("windows-installer/src/server.py")
server = replace_once(
    server,
    "from matroska_audio import apply_patch_to_chunk, preferred_japanese_audio_patch\n",
    "from matroska_audio import apply_patch_to_chunk, preferred_japanese_audio_patch\nfrom playback_compat import prepare_browser_playback\n",
    "server playback import",
)
old = '''            with connect(db_path) as connection:\n                resolved = resolve_video_file(connection, root_path, video_id)\n            if resolved is None:\n                self._error(404, "VIDEO_FILE_NOT_FOUND", "動画ファイルが見つかりません。")\n                return\n            path, extension = resolved\n            audio_patch = preferred_japanese_audio_patch(path) if extension.casefold().lstrip(".") in {"mkv", "webm"} else None\n'''
new = '''            with connect(db_path) as connection:\n                resolved = resolve_video_file(connection, root_path, video_id)\n                video = get_video(connection, video_id)\n            if resolved is None:\n                self._error(404, "VIDEO_FILE_NOT_FOUND", "動画ファイルが見つかりません。")\n                return\n            path, extension = resolved\n            file_info = (video or {}).get("file") or {}\n            try:\n                prepared = prepare_browser_playback(\n                    path,\n                    "." + extension.lstrip("."),\n                    file_info.get("videoCodec"),\n                    file_info.get("audioCodec"),\n                    app_data_root / "PlaybackCache",\n                )\n            except RuntimeError as exc:\n                self._error(503, "PLAYBACK_PREPARATION_FAILED", f"再生用動画の準備に失敗しました。 {exc}")\n                return\n            path = prepared.path\n            extension = path.suffix\n            audio_patch = (\n                preferred_japanese_audio_patch(path)\n                if not prepared.transcoded and extension.casefold() in {".mkv", ".webm"}\n                else None\n            )\n'''
server = replace_once(server, old, new, "server _serve_video preparation")
server = replace_once(
    server,
    '            self.send_header("Content-Type", mime_type_for_extension("." + extension.lstrip(".")))\n',
    '            self.send_header("Content-Type", prepared.content_type)\n            self.send_header("X-Video-Library-Playback", "transcoded" if prepared.transcoded else "direct")\n            if prepared.audio_language:\n                self.send_header("X-Video-Library-Audio-Language", prepared.audio_language)\n',
    "server playback response headers",
)
write("windows-installer/src/server.py", server)


# 3) Player modal and explicit preparation/error state in the browser UI.
html = read("windows-installer/src/video-library.html")
player_css_marker = ".player{width:100%;max-height:72vh;background:#000;border-radius:12px;margin-top:14px}.resume{margin-top:10px}"
player_css = player_css_marker + ".player-modal[hidden]{display:none}.player-modal{position:fixed;inset:0;z-index:1100;background:rgba(0,0,0,.82);display:flex;align-items:center;justify-content:center;padding:18px}.player-dialog{width:min(1100px,100%);max-height:96vh;overflow:auto;background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:18px;box-shadow:0 24px 80px rgba(0,0,0,.55)}.player-dialog-head{display:flex;gap:12px;align-items:flex-start;justify-content:space-between}.player-dialog-head h2{margin:0;font-size:20px}.player-close{flex:0 0 auto}.player-status{margin:10px 0;padding:10px 12px;border:1px solid var(--line);background:var(--panel2);border-radius:10px;color:var(--muted);font-size:13px}.player-status.error{color:var(--danger)}.player-status.ok{color:var(--ok)}.player-modal .player{max-height:70vh;margin-top:10px}.player-tech summary{cursor:pointer;color:var(--accent2);margin:10px 0}.player-tech .tech{margin-top:8px}"
html = replace_once(html, player_css_marker, player_css, "player modal css")
html = replace_once(
    html,
    '<div class="scan-modal" id="scanModal" hidden role="dialog" aria-modal="true" aria-labelledby="scanModalTitle">',
    '<div class="player-modal" id="playerModal" hidden role="dialog" aria-modal="true" aria-labelledby="playerModalTitle"><div class="player-dialog"><div class="player-dialog-head"><h2 id="playerModalTitle">動画再生</h2><button class="ghost player-close" id="playerClose" aria-label="プレイヤーを閉じる">× 閉じる</button></div><div id="playerContent"></div></div></div>\n<div class="scan-modal" id="scanModal" hidden role="dialog" aria-modal="true" aria-labelledby="scanModalTitle">',
    "player modal markup",
)

start = html.find("async function showVideo(id){")
end = html.find("async function openInWork", start)
if start < 0 or end < 0:
    raise RuntimeError("showVideo function range was not found")
new_show_video = r'''let activePlayer=null,playerPrepareTimer=null;
function closePlayerModal(){const m=$('playerModal');if(playerPrepareTimer){clearInterval(playerPrepareTimer);playerPrepareTimer=null}if(activePlayer){try{activePlayer.pause()}catch{}activePlayer.removeAttribute('src');activePlayer.load();activePlayer=null}m.dataset.requestToken='';m.hidden=true;document.body.style.overflow=''}
function playbackNeedsPreparation(v){const f=v.file||{},ext=String(f.extension||'').toLowerCase().replace(/^\./,''),vc=String(f.videoCodec||'').toLowerCase(),ac=String(f.audioCodec||'').toLowerCase();if((ext==='mp4'||ext==='m4v')&&(vc==='h264'||vc==='avc'||vc==='avc1')&&(!ac||ac==='aac'||ac==='mp3'))return false;if(ext==='webm'&&['vp8','vp9','av1'].includes(vc)&&(!ac||['opus','vorbis'].includes(ac)))return false;return true}
async function showVideo(id){const m=$('playerModal'),b=$('playerContent'),token=`${id}-${Date.now()}-${Math.random()}`;m.dataset.requestToken=token;m.hidden=false;document.body.style.overflow='hidden';b.replaceChildren(node('div','notice','動画情報を読み込んでいます…'));let v;try{v=await api(`/api/videos/${id}`)}catch(e){if(m.dataset.requestToken!==token)return;b.replaceChildren(node('div','error',`動画情報を取得できませんでした。 ${e.message}`));return}if(m.dataset.requestToken!==token)return;
  $('playerModalTitle').textContent=`${v.episodeOrType||''} ${v.episodeTitle||''}`.trim()||v.work.title;const d=node('div','video-detail'),acts=node('div','video-actions'),fav=node('button','action'+(v.state.favorite?' on':''),v.state.favorite?'★ 動画お気に入り':'☆ 動画お気に入り'),wat=node('button','action'+(v.state.watched?' on':''),v.state.watched?'✓ 視聴済み':'○ 未視聴');fav.onclick=async()=>{v.state.favorite=!v.state.favorite;await api(`/api/me/videos/${v.id}/favorite`,jo('PUT',{favorite:v.state.favorite}));fav.textContent=v.state.favorite?'★ 動画お気に入り':'☆ 動画お気に入り';fav.classList.toggle('on',v.state.favorite)};wat.onclick=async()=>{v.state.watched=!v.state.watched;await api(`/api/me/videos/${v.id}/watched`,jo('PUT',{watched:v.state.watched}));wat.textContent=v.state.watched?'✓ 視聴済み':'○ 未視聴';wat.classList.toggle('on',v.state.watched);loadHome()};acts.append(fav,wat);d.append(acts);
  const details=document.createElement('details');details.className='player-tech';const summary=document.createElement('summary');summary.textContent='技術情報・字幕';details.append(summary);const tech=node('div','tech');addTech(tech,'コンテナ',techValue(v.file.container,v.file.extension));addTech(tech,'映像Codec',techValue(v.file.videoCodec));addTech(tech,'音声Codec',techValue(v.file.audioCodec));addTech(tech,'解像度',v.file.width&&v.file.height?`${v.file.width}×${v.file.height}`:'未取得');addTech(tech,'再生時間',v.file.durationMs?ft(v.file.durationMs):'未取得');addTech(tech,'字幕',`外部 ${v.subtitles?.length||0} / 埋込 ${v.file.embeddedSubtitleCount||0}`);addTech(tech,'解析状態',techValue(v.file.probeStatus));details.append(tech);if(v.subtitles?.length){const tags=node('div','tags');for(const s of v.subtitles){const text=[s.language?String(s.language).toUpperCase():'言語不明',s.extension,s.forced?'forced':'',s.default?'default':''].filter(Boolean).join(' · ');tags.append(node('span','tag',text))}details.append(tags)}d.append(details);
  if(v.file.available){const status=node('div','player-status',playbackNeedsPreparation(v)?'ブラウザ互換形式を準備しています。初回再生は時間がかかる場合があります。':'再生データを確認しています…'),p=document.createElement('video');p.className='player';p.controls=true;p.preload='metadata';p.playsInline=true;p.hidden=true;activePlayer=p;d.append(status,p);attachExternalSubtitles(p,v.subtitles||[]);let seconds=0;playerPrepareTimer=setInterval(()=>{seconds+=5;if(!p.src&&m.dataset.requestToken===token){status.textContent=`再生用動画を準備しています… 経過 ${seconds}秒${seconds>=60?'（初回変換中です。完了後はキャッシュから再生します）':''}`}},5000);
    try{const ready=await fetch(`/video/${v.id}`,{method:'HEAD',cache:'no-store'});if(m.dataset.requestToken!==token)return;if(!ready.ok)throw new Error(`HTTP ${ready.status}`);if(playerPrepareTimer){clearInterval(playerPrepareTimer);playerPrepareTimer=null}const mode=ready.headers.get('X-Video-Library-Playback');status.className='player-status ok';status.textContent=mode==='transcoded'?'ブラウザ互換形式の準備が完了しました。':'再生準備が完了しました。';p.hidden=false;p.src=`/video/${v.id}`;p.load();p.addEventListener('loadedmetadata',()=>preferJapaneseAudio(p));if(p.audioTracks&&p.audioTracks.addEventListener)p.audioTracks.addEventListener('addtrack',()=>preferJapaneseAudio(p));let sid=null,last=0;async function start(){if(sid)return sid;const x=await api(`/api/me/videos/${v.id}/playback/start`,{method:'POST'});sid=x.playSessionId;return sid}async function progress(event,force=false){if(!sid)return;const now=Date.now();if(!force&&now-last<10000)return;last=now;const x=await api(`/api/me/videos/${v.id}/playback/progress`,jo('POST',{playSessionId:sid,positionMs:Math.round(p.currentTime*1000),durationMs:Number.isFinite(p.duration)?Math.round(p.duration*1000):null,event}));v.state={...v.state,...x.state};wat.textContent=v.state.watched?'✓ 視聴済み':'○ 未視聴'}p.addEventListener('play',start);p.addEventListener('timeupdate',()=>progress('timeupdate'));p.addEventListener('pause',()=>progress('pause',true));p.addEventListener('ended',()=>progress('ended',true).then(loadHome));p.addEventListener('error',()=>{status.className='player-status error';status.textContent='動画の再生に失敗しました。診断画面でCodec情報を確認してください。'});if(v.state.positionMs>0&&!v.state.watched){const rb=node('button','primary resume',`▶ ${ft(v.state.positionMs)} から再開`);rb.onclick=async()=>{await start();p.currentTime=v.state.positionMs/1000;p.play()};d.append(rb)}}catch(e){if(playerPrepareTimer){clearInterval(playerPrepareTimer);playerPrepareTimer=null}if(m.dataset.requestToken!==token)return;status.className='player-status error';status.textContent=`再生用動画を準備できませんでした。 ${e.message}`;p.hidden=true}}
  else d.append(node('div','notice','動画ファイルが見つかりません。'));b.replaceChildren(d)}
$('playerClose').onclick=closePlayerModal;$('playerModal').addEventListener('click',e=>{if(e.target===$('playerModal'))closePlayerModal()});document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('playerModal').hidden)closePlayerModal()});
'''
html = html[:start] + new_show_video + html[end:]
write("windows-installer/src/video-library.html", html)


# 4) Package FFmpeg and ffprobe in the Windows application when staged in tools/.
spec = read("windows-installer/build/VideoLibrary.spec")
old_spec = '''ffprobe = TOOLS / "ffprobe.exe"\nif ffprobe.is_file():\n    datas.append((str(ffprobe), "tools"))\n'''
new_spec = '''for tool_name in ("ffprobe.exe", "ffmpeg.exe"):\n    tool = TOOLS / tool_name\n    if tool.is_file():\n        datas.append((str(tool), "tools"))\n'''
spec = replace_once(spec, old_spec, new_spec, "PyInstaller FFmpeg tools")
write("windows-installer/build/VideoLibrary.spec", spec)


# 5) Stage real FFmpeg binaries in the installer CI job (never commit binaries).
ci = read(".github/workflows/ci.yml")
marker = '''      - name: Ensure Inno Setup 6\n        shell: pwsh\n'''
staging = '''      - name: Stage FFmpeg and ffprobe for installer\n        shell: pwsh\n        run: |\n          if (-not (Test-Path "$env:ChocolateyInstall\\lib\\ffmpeg")) {\n            choco install ffmpeg --yes --no-progress\n          }\n          $ffmpegRoot = Join-Path $env:ChocolateyInstall 'lib\\ffmpeg\\tools'\n          $ffmpeg = Get-ChildItem $ffmpegRoot -Recurse -Filter ffmpeg.exe | Select-Object -First 1\n          $ffprobe = Get-ChildItem $ffmpegRoot -Recurse -Filter ffprobe.exe | Select-Object -First 1\n          if (-not $ffmpeg -or -not $ffprobe) { throw 'real FFmpeg binaries were not found' }\n          $target = '.\\windows-installer\\tools'\n          New-Item -ItemType Directory -Force -Path $target | Out-Null\n          Copy-Item $ffmpeg.FullName (Join-Path $target 'ffmpeg.exe') -Force\n          Copy-Item $ffprobe.FullName (Join-Path $target 'ffprobe.exe') -Force\n          Write-Host "FFmpeg staged: $($ffmpeg.FullName)"\n          Write-Host "ffprobe staged: $($ffprobe.FullName)"\n      - name: Ensure Inno Setup 6\n        shell: pwsh\n'''
ci = replace_once(ci, marker, staging, "installer FFmpeg staging")
write(".github/workflows/ci.yml", ci)


# 6) Version and installer alignment.
version = read("windows-installer/src/app_version.py")
version = re.sub(r'APP_VERSION = "[^"]+"', 'APP_VERSION = "0.9.0"', version, count=1)
write("windows-installer/src/app_version.py", version)
iss = read("windows-installer/installer/VideoLibrary.iss")
iss = re.sub(r'#define MyAppVersion "[^"]+"', '#define MyAppVersion "0.9.0"', iss, count=1)
write("windows-installer/installer/VideoLibrary.iss", iss)


# 7) Tool documentation.
tools = '''# tools\n\n`ffmpeg.exe` と `ffprobe.exe` をこのフォルダーへ置くと、PyInstallerビルド時にWindowsアプリへ同梱されます。\n\n公開リポジトリにはFFmpeg/ffprobeの実行バイナリをコミットしません。GitHub ActionsのWindows InstallerジョブではChocolateyのFFmpegパッケージから実バイナリを一時配置し、生成するインストーラーへ同梱します。\n\n実行時の検索順は以下です。\n\n1. `VIDEO_LIBRARY_FFMPEG` / `VIDEO_LIBRARY_FFPROBE` 環境変数\n2. アプリ配置先の `ffmpeg.exe` / `ffprobe.exe`\n3. アプリ配置先の `tools/ffmpeg.exe` / `tools/ffprobe.exe`\n4. PATH上のFFmpeg / ffprobe\n\nffprobeは動画Codec解析に使用します。ffmpegはAVI / MKV / MPG / FLVなど、ブラウザが直接再生できない動画や非対応音声を、元動画を変更せずH.264 + AAC MP4の再生キャッシュへ変換するために使用します。\n'''
write("windows-installer/tools/README.md", tools)


# 8) CI/runtime regression tests.
test = r'''from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from playback_compat import AudioSelection, browser_direct_playback, prepare_browser_playback


class PlaybackRuntimeV090Tests(unittest.TestCase):
    def test_direct_and_fallback_policy(self) -> None:
        self.assertTrue(browser_direct_playback(".mp4", "h264", "aac"))
        self.assertTrue(browser_direct_playback(".webm", "vp9", "opus"))
        for ext in (".mkv", ".avi", ".mpg", ".flv"):
            self.assertFalse(browser_direct_playback(ext, "h264", "aac"))

    def test_second_japanese_audio_forces_preparation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "movie.mp4"
            source.write_bytes(b"source")
            cached = Path(temp) / "cache" / "converted.mp4"
            cached.parent.mkdir()
            cached.write_bytes(b"converted")
            japanese = AudioSelection(stream_index=2, codec="aac", language="jpn", japanese=True, first_audio=False)
            with mock.patch("playback_compat.preferred_audio_selection", return_value=japanese), mock.patch(
                "playback_compat.transcode_to_browser_mp4", return_value=(cached, "ja")
            ) as transcode:
                prepared = prepare_browser_playback(source, ".mp4", "h264", "aac", Path(temp) / "cache")
            self.assertTrue(prepared.transcoded)
            self.assertEqual(prepared.audio_language, "ja")
            transcode.assert_called_once()

    def test_server_wires_playback_cache_before_range_streaming(self) -> None:
        text = (SRC / "server.py").read_text(encoding="utf-8")
        self.assertIn("prepare_browser_playback", text)
        self.assertIn('app_data_root / "PlaybackCache"', text)
        self.assertIn('"PLAYBACK_PREPARATION_FAILED"', text)
        self.assertIn('"X-Video-Library-Playback"', text)

    def test_browser_player_is_modal_with_head_preflight_and_explicit_error(self) -> None:
        text = (SRC / "video-library.html").read_text(encoding="utf-8")
        self.assertIn('id="playerModal"', text)
        self.assertIn('id="playerClose"', text)
        self.assertIn("method:'HEAD'", text)
        self.assertIn("ブラウザ互換形式を準備しています", text)
        self.assertIn("再生用動画を準備できませんでした", text)
        self.assertIn("Escape", text)

    def test_installer_packages_ffmpeg_and_ffprobe(self) -> None:
        spec = (ROOT / "windows-installer" / "build" / "VideoLibrary.spec").read_text(encoding="utf-8")
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn('("ffprobe.exe", "ffmpeg.exe")', spec)
        self.assertIn("Stage FFmpeg and ffprobe for installer", ci)
        self.assertIn("Copy-Item $ffmpeg.FullName", ci)
        self.assertIn("Copy-Item $ffprobe.FullName", ci)

    def test_version_is_090(self) -> None:
        spec = importlib.util.spec_from_file_location("app_version_v090", SRC / "app_version.py")
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        self.assertEqual(module.APP_VERSION, "0.9.0")
        installer = (ROOT / "windows-installer" / "installer" / "VideoLibrary.iss").read_text(encoding="utf-8")
        self.assertIn('#define MyAppVersion "0.9.0"', installer)


if __name__ == "__main__":
    unittest.main()
'''
write("tests/test_playback_runtime_v090.py", test)


# 9) Design note.
doc = '''# 0.9.0 再生互換ランタイムとプレイヤーモーダル\n\n## 目的\n\n実機で確認したAVI再生不可、映像のみで音声が出ない動画、読み込み中のままになる動画を解消し、作品詳細の最下部にあったプレイヤーを操作しやすいモーダルへ移す。\n\n## 再生経路\n\n- MP4(H.264 + AAC/MP3) / WebM(VP8/VP9/AV1 + Opus/Vorbis) は直接配信できる場合にそのままRange配信する。\n- MKV / AVI / MPG / FLV、またはブラウザ非対応Codecは、初回再生時にH.264 + AAC MP4へ変換する。\n- 変換結果は `%LOCALAPPDATA%\\VideoLibrary\\PlaybackCache` に保存し、元動画のパス・サイズ・更新日時からキャッシュキーを作る。元動画は変更しない。\n- 複数音声に日本語がある場合はffprobeで日本語ストリームを探して優先する。ブラウザで安定してトラック選択できない場合は互換MP4へ変換して日本語音声を固定する。\n- 同一動画への同時変換はプロセス内ロックで1回に集約する。\n\n## UI\n\n- エピソード選択時に中央モーダルを開く。PCは大画面ダイアログ、スマホは画面幅をほぼ使用する。\n- 閉じるボタン、背景クリック、Escで閉じられる。閉じる時はvideo要素のsrcを破棄して通信を止める。\n- `/video/<id>` へHEADを先行し、互換変換が必要な場合は経過時間つきで「再生用動画を準備しています」と表示する。\n- 変換/配信失敗は明示的なエラー表示にし、無限ローディングに見えないようにする。\n- 技術情報と字幕情報は折りたたみ表示とする。外部字幕のデフォルトON仕様は0.8.0から維持する。\n\n## 配布\n\n公開GitリポジトリにはFFmpegバイナリを置かない。Installer CIでFFmpeg/ffprobe実バイナリをステージし、PyInstaller成果物へ同梱する。したがって利用PCへ別途FFmpegをインストールする必要はない。\n\n## CI\n\n0.8.0までの全回帰テストに加え、0.9.0では以下を必須とする。\n\n- 実ライブラリ4,869件に存在するMKV / MP4 / AVI / WEBM / MPG / FLV全6拡張子の合成動画をFFmpeg生成し、最終出力を実デコードする `playback-formats` ジョブ。\n- サーバーがPlaybackCache経由の互換再生処理を呼ぶこと。\n- モーダル、HEAD事前確認、明示エラー表示のUI回帰テスト。\n- FFmpeg/ffprobeがWindows Installerへ同梱される構成の回帰テスト。\n'''
write("docs/31-0.9.0-playback-runtime-modal.md", doc)

print("Issue #59 runtime patches applied")
