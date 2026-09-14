from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


# library_service.py: explicit Japanese first, then default, then normal subtitle.
path = "windows-installer/src/library_service.py"
text = read(path)
text = replace_once(
    text,
    "        ORDER BY is_default DESC, is_forced DESC, COALESCE(language,''), id\n",
    "        ORDER BY\n"
    "            CASE WHEN lower(COALESCE(language,'')) IN ('ja','jp','jpn','japanese') THEN 0 ELSE 1 END,\n"
    "            is_default DESC, is_forced ASC, id\n",
    "subtitle order",
)
text = replace_once(
    text,
    '            "id": int(st["id"]),\n',
    '            "id": int(st["id"]),\n            "preferred": index == 0,\n',
    "preferred field",
)
text = replace_once(
    text,
    "        for st in subtitle_rows\n",
    "        for index, st in enumerate(subtitle_rows)\n",
    "subtitle enumerate",
)
write(path, text)


# server.py: safe WebVTT subtitle delivery endpoint.
path = "windows-installer/src/server.py"
text = read(path)
text = replace_once(
    text,
    "from scan_runner import scan_library\n",
    "from scan_runner import scan_library\nfrom subtitle_stream import resolve_subtitle_file, subtitle_file_to_webvtt\n",
    "subtitle import",
)
subtitle_method = '''        def _serve_subtitle(self, subtitle_id: int, *, head: bool = False) -> None:
            if root_path is None:
                self._error(409, "VIDEO_ROOT_NOT_CONFIGURED", "動画フォルダーが設定されていません。")
                return
            with connect(db_path) as connection:
                resolved = resolve_subtitle_file(connection, root_path, subtitle_id)
            if resolved is None:
                self._error(404, "SUBTITLE_FILE_NOT_FOUND", "字幕ファイルが見つかりません。")
                return
            subtitle_path, extension = resolved
            try:
                body = subtitle_file_to_webvtt(subtitle_path, extension)
            except OSError:
                self._error(404, "SUBTITLE_FILE_NOT_FOUND", "字幕ファイルが見つかりません。")
                return
            except ValueError:
                self._error(415, "SUBTITLE_FORMAT_UNSUPPORTED", "この字幕形式は再生できません。")
                return
            except Exception:
                self._error(500, "SUBTITLE_CONVERSION_FAILED", "字幕の変換に失敗しました。")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/vtt; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._common(cache="no-store")
            self.end_headers()
            if not head:
                self.wfile.write(body)

'''
if "        def _serve_subtitle(self, subtitle_id: int" not in text:
    text = replace_once(
        text,
        "        def do_GET(self) -> None:\n",
        subtitle_method + "        def do_GET(self) -> None:\n",
        "subtitle method",
    )
get_route = '''            subtitle = re.fullmatch(r"/subtitle/(\\d+)\\.vtt", path)
            if subtitle:
                self._serve_subtitle(int(subtitle.group(1))); return
'''
if 're.fullmatch(r"/subtitle/(\\d+)\\.vtt", path)' not in text:
    text = replace_once(
        text,
        '            stream = re.fullmatch(r"/video/(\\d+)", path)\n',
        get_route + '            stream = re.fullmatch(r"/video/(\\d+)", path)\n',
        "subtitle GET route",
    )
head_route = '''            subtitle = re.fullmatch(r"/subtitle/(\\d+)\\.vtt", urlsplit(self.path).path)
            if subtitle:
                self._serve_subtitle(int(subtitle.group(1)), head=True); return
'''
if 'self._serve_subtitle(int(subtitle.group(1)), head=True)' not in text:
    text = replace_once(
        text,
        "        def do_HEAD(self) -> None:\n",
        "        def do_HEAD(self) -> None:\n" + head_route,
        "subtitle HEAD route",
    )
write(path, text)


# video-library.html: add one native <track> per linked subtitle and show preferred once.
path = "windows-installer/src/video-library.html"
text = read(path)
subtitle_helpers = '''function subtitleLanguage(s){const x=String(s?.language||'').toLowerCase().replace('_','-');if(x==='jp'||x==='jpn'||x==='japanese')return'ja';if(x==='eng'||x==='english')return'en';return x||'und'}
function subtitleLabel(s,i){const lang=subtitleLanguage(s);let label=lang==='ja'?'日本語':lang==='en'?'English':`字幕 ${i+1}`;if(s?.forced)label+=' (forced)';return label}
function attachExternalSubtitles(p,subs){if(!Array.isArray(subs)||!subs.length)return;let preferred=subs.findIndex(s=>s.preferred);if(preferred<0)preferred=0;const tracks=[];subs.forEach((s,i)=>{const t=document.createElement('track');t.kind='subtitles';t.src=`/subtitle/${s.id}.vtt`;t.srclang=subtitleLanguage(s);t.label=subtitleLabel(s,i);t.default=i===preferred;p.append(t);tracks.push(t)});let initialized=false;const applyInitial=()=>{if(initialized)return;for(let i=0;i<tracks.length;i++){if(!tracks[i].track)return;tracks[i].track.mode=i===preferred?'showing':'disabled'}initialized=true};tracks[preferred].addEventListener('load',applyInitial,{once:true});p.addEventListener('loadedmetadata',()=>setTimeout(applyInitial,0),{once:true})}
'''
if "function attachExternalSubtitles" not in text:
    text = replace_once(
        text,
        "function phaseLabel(p){",
        subtitle_helpers + "function phaseLabel(p){",
        "subtitle UI helpers",
    )
text = replace_once(
    text,
    "p.playsInline=true;p.src=`/video/${v.id}`;d.append(p);p.addEventListener('loadedmetadata',()=>preferJapaneseAudio(p));",
    "p.playsInline=true;attachExternalSubtitles(p,v.subtitles||[]);p.src=`/video/${v.id}`;d.append(p);p.addEventListener('loadedmetadata',()=>preferJapaneseAudio(p));",
    "attach tracks",
)
write(path, text)


# Service Worker: subtitle responses must never be cached.
path = "windows-installer/src/service-worker.js"
text = read(path)
text = text.replace("video-library-shell-v2", "video-library-shell-v3")
text = replace_once(
    text,
    "if(url.pathname.startsWith('/api/')||url.pathname.startsWith('/video/'))return;",
    "if(url.pathname.startsWith('/api/')||url.pathname.startsWith('/video/')||url.pathname.startsWith('/subtitle/'))return;",
    "service worker subtitle exclusion",
)
write(path, text)


# Release version alignment.
write("windows-installer/src/app_version.py", 'APP_VERSION = "0.8.0"\n')
path = "windows-installer/installer/VideoLibrary.iss"
text = read(path).replace('#define MyAppVersion "0.7.9"', '#define MyAppVersion "0.8.0"')
write(path, text)
path = "tests/test_release_consistency.py"
text = read(path).replace('self.assertEqual(APP_VERSION, "0.7.9")', 'self.assertEqual(APP_VERSION, "0.8.0")')
write(path, text)


# README.
path = "README.md"
text = read(path)
text = text.replace(
    '- Service Workerは `/api/*` と `/video/*` をキャッシュしない',
    '- Service Workerは `/api/*`、`/video/*`、`/subtitle/*` をキャッシュしない',
)
old = "0.7.6までに字幕の検出・安全な紐付け・診断分類を実装済みです。SRT/ASS→WebVTT変換とプレーヤー字幕表示は後続機能です。"
new = "0.8.0で紐付済み外部字幕のブラウザ再生を実装しました。SRT / ASS / SSAは配信時にWebVTTへ変換し、VTTは正規化して配信します。字幕が1件以上ある動画は優先字幕をデフォルトONにし、再生中はブラウザ標準コントロールからOFF・切替できます。元字幕ファイルは変更しません。"
if old in text:
    text = text.replace(old, new, 1)
marker = "- 0.7.9: 動画版Tailscale ServeをHTTPS 8443へ分離し、Windowsランチャーに外部URLを開くボタンを追加\n"
if "### 0.8.0: 外部字幕のブラウザ再生" not in text:
    addition = marker + "\n### 0.8.0: 外部字幕のブラウザ再生\n- 紐付済みSRT / VTT / ASS / SSAをWebVTTとして安全に配信\n- 字幕がある動画は字幕をデフォルトON\n- 複数字幕では明示的な日本語字幕を優先\n- 元字幕ファイル・字幕マッチングロジックは変更しない\n"
    text = replace_once(text, marker, addition, "README 0.8.0 status")
doc_marker = "- [0.7.9 動画版Tailscale外部URL分離](docs/29-0.7.9-video-remote-url.md)\n"
if "docs/30-0.8.0-external-subtitle-playback.md" not in text:
    text = replace_once(
        text,
        doc_marker,
        doc_marker + "- [0.8.0 外部字幕のブラウザ再生](docs/30-0.8.0-external-subtitle-playback.md)\n",
        "README docs",
    )
text = text.replace("- `/video/*`\n- SQLite", "- `/video/*`\n- `/subtitle/*`\n- SQLite")
write(path, text)
