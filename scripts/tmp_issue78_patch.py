from __future__ import annotations

import re
from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        raise SystemExit(f"marker not found: {path}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


def regex_once(path: str, pattern: str, replacement: str) -> None:
    text = read(path)
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"regex marker count={count}: {path}: {pattern[:100]!r}")
    write(path, updated)


# library_service: expose only local image URLs for confirmed TMDb matches.
path = "windows-installer/src/library_service.py"
text = read(path)
text = text.replace(
    "          (SELECT COUNT(*) FROM videos v JOIN user_video_state s ON s.video_id=v.id AND s.user_id=? WHERE v.work_id=w.id AND s.position_ms>0 AND s.watched=0) in_progress_count\n        FROM works w {where_sql}",
    "          (SELECT COUNT(*) FROM videos v JOIN user_video_state s ON s.video_id=v.id AND s.user_id=? WHERE v.work_id=w.id AND s.position_ms>0 AND s.watched=0) in_progress_count,\n          t.match_status tmdb_match_status,t.poster_path tmdb_poster_path,t.backdrop_path tmdb_backdrop_path\n        FROM works w LEFT JOIN tmdb_work_links t ON t.work_id=w.id {where_sql}",
    1,
)
text = text.replace(
    '                "progress": _progress(int(r["watched_count"]), int(r["progress_total"]), int(r["in_progress_count"])),\n',
    '                "progress": _progress(int(r["watched_count"]), int(r["progress_total"]), int(r["in_progress_count"])),\n'
    '                "posterUrl": f"/tmdb-image/poster/{int(r[\"id\"])}" if r["tmdb_match_status"] == "MATCHED" and r["tmdb_poster_path"] else None,\n'
    '                "backdropUrl": f"/tmdb-image/backdrop/{int(r[\"id\"])}" if r["tmdb_match_status"] == "MATCHED" and r["tmdb_backdrop_path"] else None,\n',
    1,
)
text = text.replace(
    "               w.main_cast_or_voice_actors,w.verification_status,w.credits_verification_status,\n               COALESCE(s.favorite,0) favorite\n        FROM works w LEFT JOIN user_work_state s ON s.work_id=w.id AND s.user_id=? WHERE w.id=?",
    "               w.main_cast_or_voice_actors,w.verification_status,w.credits_verification_status,\n               COALESCE(s.favorite,0) favorite,t.media_type tmdb_media_type,t.tmdb_id,t.match_status tmdb_match_status,\n               t.confidence tmdb_confidence,t.matched_title tmdb_matched_title,t.matched_year tmdb_matched_year,\n               t.poster_path tmdb_poster_path,t.backdrop_path tmdb_backdrop_path,t.overview tmdb_overview\n        FROM works w LEFT JOIN user_work_state s ON s.work_id=w.id AND s.user_id=?\n        LEFT JOIN tmdb_work_links t ON t.work_id=w.id WHERE w.id=?",
    1,
)
text = text.replace(
    '        "favorite": bool(r["favorite"]),\n        "progress": _progress',
    '        "favorite": bool(r["favorite"]),\n'
    '        "posterUrl": f"/tmdb-image/poster/{int(r[\"id\"])}" if r["tmdb_match_status"] == "MATCHED" and r["tmdb_poster_path"] else None,\n'
    '        "backdropUrl": f"/tmdb-image/backdrop/{int(r[\"id\"])}" if r["tmdb_match_status"] == "MATCHED" and r["tmdb_backdrop_path"] else None,\n'
    '        "tmdb": {\n'
    '            "status": r["tmdb_match_status"] or "UNMATCHED",\n'
    '            "mediaType": r["tmdb_media_type"], "id": r["tmdb_id"], "confidence": r["tmdb_confidence"],\n'
    '            "matchedTitle": r["tmdb_matched_title"], "matchedYear": r["tmdb_matched_year"],\n'
    '            "overview": r["tmdb_overview"],\n'
    '        },\n'
    '        "progress": _progress',
    1,
)
if "tmdb_match_status" not in text:
    raise SystemExit("library_service TMDb patch failed")
write(path, text)


# server: serve cached poster/backdrop from local app data only.
replace_once(
    "windows-installer/src/server.py",
    "from tailscale_identity import parse_tailscale_identity\n",
    "from tailscale_identity import parse_tailscale_identity\nfrom tmdb_images import resolve_cached_tmdb_image\n",
)
server_path = "windows-installer/src/server.py"
server = read(server_path)
marker = "        def do_GET(self) -> None:\n"
if marker not in server:
    raise SystemExit("server do_GET marker missing")
helper = '''        def _serve_tmdb_image(self, kind: str, work_id: int, *, head: bool = False) -> None:\n            with connect(db_path) as connection:\n                resolved = resolve_cached_tmdb_image(connection, app_data_root / "TMDbImages", work_id, kind)\n            if resolved is None:\n                self._error(404, "TMDB_IMAGE_NOT_FOUND", "TMDb画像が見つかりません。")\n                return\n            image_path, content_type = resolved\n            try:\n                size = image_path.stat().st_size\n            except OSError:\n                self._error(404, "TMDB_IMAGE_NOT_FOUND", "TMDb画像が見つかりません。")\n                return\n            self.send_response(200)\n            self.send_header("Content-Type", content_type)\n            self.send_header("Content-Length", str(size))\n            self._common(cache="public, max-age=3600")\n            self.end_headers()\n            if not head:\n                try:\n                    self.wfile.write(image_path.read_bytes())\n                except (BrokenPipeError, ConnectionResetError):\n                    pass\n\n'''
server = server.replace(marker, helper + marker, 1)
server = server.replace(
    '            stream = re.fullmatch(r"/video/(\\d+)", path)\n            if stream:\n                self._serve_video(int(stream.group(1))); return\n',
    '            tmdb_image = re.fullmatch(r"/tmdb-image/(poster|backdrop)/(\\d+)", path)\n'
    '            if tmdb_image:\n'
    '                self._serve_tmdb_image(tmdb_image.group(1), int(tmdb_image.group(2))); return\n'
    '            stream = re.fullmatch(r"/video/(\\d+)", path)\n'
    '            if stream:\n'
    '                self._serve_video(int(stream.group(1))); return\n',
    1,
)
server = server.replace(
    '            stream = re.fullmatch(r"/video/(\\d+)", urlsplit(self.path).path)\n            if stream:\n                self._serve_video(int(stream.group(1)), head=True); return\n',
    '            tmdb_image = re.fullmatch(r"/tmdb-image/(poster|backdrop)/(\\d+)", urlsplit(self.path).path)\n'
    '            if tmdb_image:\n'
    '                self._serve_tmdb_image(tmdb_image.group(1), int(tmdb_image.group(2)), head=True); return\n'
    '            stream = re.fullmatch(r"/video/(\\d+)", urlsplit(self.path).path)\n'
    '            if stream:\n'
    '                self._serve_video(int(stream.group(1)), head=True); return\n',
    1,
)
if "TMDB_IMAGE_NOT_FOUND" not in server or "tmdb-image" not in server:
    raise SystemExit("server TMDb image patch failed")
write(server_path, server)


# launcher: owner-controlled asynchronous TMDb sync.
replace_once(
    "windows-installer/src/launcher.py",
    "from server import create_server\n",
    "from server import create_server\nfrom tmdb_sync import sync_tmdb_library\n",
)
replace_once(
    "windows-installer/src/launcher.py",
    "PLAYBACK_AUDIT_OUTPUT_PATH = DATA_ROOT / \"diagnostics\"\n",
    "PLAYBACK_AUDIT_OUTPUT_PATH = DATA_ROOT / \"diagnostics\"\nTMDB_IMAGE_PATH = DATA_ROOT / \"TMDbImages\"\nTMDB_REPORT_OUTPUT_PATH = DATA_ROOT / \"diagnostics\"\n",
)
replace_once(
    "windows-installer/src/launcher.py",
    "        self.audit_thread: threading.Thread | None = None\n",
    "        self.audit_thread: threading.Thread | None = None\n        self.tmdb_thread: threading.Thread | None = None\n",
)
replace_once(
    "windows-installer/src/launcher.py",
    '        ttk.Button(operations_frame, text="TMDb設定", command=self.open_tmdb_settings).pack(side="left", padx=(0, 8))\n',
    '        self.tmdb_sync_button = ttk.Button(operations_frame, text="TMDb同期", command=self.start_tmdb_sync)\n'
    '        self.tmdb_sync_button.pack(side="left", padx=(0, 8))\n'
    '        ttk.Button(operations_frame, text="TMDb設定", command=self.open_tmdb_settings).pack(side="left", padx=(0, 8))\n',
)
launcher_path = "windows-installer/src/launcher.py"
launcher = read(launcher_path)
insert_marker = "\n\n    def refresh_cache_status(self) -> None:\n"
if insert_marker not in launcher:
    raise SystemExit("launcher refresh marker missing")
tmdb_methods = r'''

    def start_tmdb_sync(self) -> None:
        if self.server is not None or self.scan_thread is not None or self.audit_thread is not None or self.tmdb_thread is not None:
            messagebox.showinfo(APP_NAME, "TMDb同期の前にライブラリを停止してください。")
            return
        if not DATABASE_PATH.is_file():
            messagebox.showerror(APP_NAME, "ライブラリDBが見つかりません。")
            return
        token = configured_tmdb_token(config_path=CONFIG_PATH)
        if not token:
            messagebox.showinfo(APP_NAME, "先に「TMDb設定」でAPI Read Access Tokenを設定してください。")
            return
        if not messagebox.askyesno(
            APP_NAME,
            "登録作品をTMDbと照合し、高信頼で一致した作品のポスター／背景画像を保存します。\n"
            "低信頼候補は自動確定しません。開始しますか？",
        ):
            return
        self._set_busy(True)
        self.status.set("TMDb作品情報を同期中です")
        self.scan_status.set("TMDb同期中 — 作品を照合しています")
        self.scan_counts.set("MATCHED 0 / REVIEW 0 / UNMATCHED 0")
        self.scan_current.set("現在処理中: —")
        self.scan_progress.configure(mode="determinate", maximum=1)
        self.scan_progress["value"] = 0
        self._append_log("=" * 72)
        self._append_log("TMDb作品照合を開始します。低信頼候補は自動確定しません。")
        self.tmdb_thread = threading.Thread(
            target=self._tmdb_sync_worker,
            args=(token,),
            daemon=True,
            name="VideoLibraryTmdbSync",
        )
        self.tmdb_thread.start()

    def _tmdb_sync_worker(self, token: str) -> None:
        try:
            report = sync_tmdb_library(
                DATABASE_PATH,
                TMDB_IMAGE_PATH,
                TMDB_REPORT_OUTPUT_PATH,
                token,
                progress_callback=self._tmdb_progress_from_worker,
            )
        except Exception as exc:
            self.after(0, lambda e=exc: self._tmdb_sync_failed(e))
            return
        self.after(0, lambda r=report: self._tmdb_sync_succeeded(r))

    def _tmdb_progress_from_worker(self, progress: dict[str, Any]) -> None:
        snapshot = dict(progress)
        self.after(0, lambda p=snapshot: self._apply_tmdb_progress(p))

    def _apply_tmdb_progress(self, progress: dict[str, Any]) -> None:
        current = int(progress.get("current") or 0)
        total = int(progress.get("total") or 0)
        matched = int(progress.get("matched") or 0)
        review = int(progress.get("review") or 0)
        unmatched = int(progress.get("unmatched") or 0)
        self.scan_status.set(f"TMDb同期中 — {current:,} / {total:,}")
        self.scan_counts.set(f"MATCHED {matched:,} / REVIEW {review:,} / UNMATCHED {unmatched:,}")
        self.scan_current.set(f"現在処理中: {progress.get('currentItem') or '—'}")
        self.scan_progress.configure(mode="determinate", maximum=max(1, total))
        self.scan_progress["value"] = min(current, total)
        if current and (current % 25 == 0 or current == total):
            self._append_log(
                f"TMDb {current:,}/{total:,}: MATCHED {matched:,} / REVIEW {review:,} / UNMATCHED {unmatched:,}"
            )

    def _tmdb_sync_succeeded(self, report: dict[str, Any]) -> None:
        self.tmdb_thread = None
        summary = report.get("summary") or {}
        total = int(summary.get("total") or 0)
        matched = int(summary.get("matched") or 0)
        review = int(summary.get("review") or 0)
        unmatched = int(summary.get("unmatched") or 0)
        posters = int(summary.get("posterCached") or 0)
        backdrops = int(summary.get("backdropCached") or 0)
        self.scan_progress.configure(mode="determinate", maximum=max(1, total))
        self.scan_progress["value"] = total
        self.scan_status.set("完了 — TMDb作品情報を同期しました")
        self.scan_counts.set(f"MATCHED {matched:,} / REVIEW {review:,} / UNMATCHED {unmatched:,}")
        self.scan_current.set("現在処理中: 完了")
        self.status.set("TMDb作品情報の同期が完了しました")
        self._append_log(
            f"TMDb同期完了: {total:,}作品 / MATCHED {matched:,} / REVIEW {review:,} / UNMATCHED {unmatched:,}"
        )
        self._append_log(f"ポスター {posters:,} / 背景 {backdrops:,} / JSON: {report.get('jsonReport', '')}")
        self._append_log(f"CSV : {report.get('csvReport', '')}")
        self._set_busy(False)
        messagebox.showinfo(
            APP_NAME,
            "TMDb同期が完了しました。\n\n"
            f"登録作品: {total:,}\nMATCHED: {matched:,}\nREVIEW: {review:,}\nUNMATCHED: {unmatched:,}\n"
            f"ポスター保存: {posters:,}\n背景保存: {backdrops:,}\n\n"
            "REVIEWは自動確定していません。診断CSVで確認できます。",
        )

    def _tmdb_sync_failed(self, exc: Exception) -> None:
        self.tmdb_thread = None
        self.status.set("TMDb同期に失敗しました")
        self.scan_status.set("失敗 — TMDb作品情報を同期できませんでした")
        self._append_log(f"TMDb ERROR: {type(exc).__name__}: {exc}")
        self._set_busy(False)
        messagebox.showerror(APP_NAME, f"TMDb同期に失敗しました。\n{exc}")
'''
launcher = launcher.replace(insert_marker, tmdb_methods + insert_marker, 1)
launcher = launcher.replace(
    "        self.audit_button.configure(state=state)\n",
    "        self.audit_button.configure(state=state)\n        self.tmdb_sync_button.configure(state=state)\n",
    1,
)
if "start_tmdb_sync" not in launcher or "TMDB_IMAGE_PATH" not in launcher:
    raise SystemExit("launcher TMDb sync patch failed")
write(launcher_path, launcher)


# Browser UI: poster cards, backdrop detail and TMDb attribution.
html_path = "windows-installer/src/video-library.html"
html = read(html_path)
css_marker = "    @media(max-width:700px){"
css_extra = '''    .poster{position:relative;aspect-ratio:2/3;background:linear-gradient(145deg,#29231a,#111318);border-bottom:1px solid var(--line);overflow:hidden}.poster img{width:100%;height:100%;display:block;object-fit:cover}.poster-fallback{height:100%;display:flex;align-items:center;justify-content:center;padding:18px;text-align:center;color:var(--accent2);font-weight:700}.card{padding:0;overflow:hidden}.card-body{padding:14px 16px 16px;display:flex;flex-direction:column;flex:1}.hero.has-backdrop{background-size:cover;background-position:center}.hero.has-backdrop::before{content:"";position:absolute;inset:0;background:linear-gradient(90deg,rgba(17,19,24,.96),rgba(17,19,24,.75),rgba(17,19,24,.9));pointer-events:none}.hero{position:relative;overflow:hidden}.hero-layout{position:relative;z-index:1;display:grid;grid-template-columns:150px minmax(0,1fr);gap:20px}.hero-poster{width:150px;aspect-ratio:2/3;object-fit:cover;border-radius:10px;border:1px solid var(--line);box-shadow:0 10px 28px rgba(0,0,0,.45)}.hero-body{min-width:0}.overview{margin:14px 0 0;line-height:1.75;color:#d7dbe2}.tmdb-credit{margin-top:36px;padding-top:16px;border-top:1px solid var(--line);font-size:11px;color:var(--muted);text-align:center}.tmdb-credit a{color:var(--accent2)}\n'''
if css_marker not in html:
    raise SystemExit("HTML CSS marker missing")
html = html.replace(css_marker, css_extra + "    @media(max-width:700px){.hero-layout{grid-template-columns:100px minmax(0,1fr)}.hero-poster{width:100px}" , 1)
html = html.replace(
    "  </main>\n</div>\n<div class=\"player-modal\"",
    "  </main>\n  <footer class=\"tmdb-credit\">This product uses the TMDB API but is not endorsed or certified by TMDB. · <a href=\"https://www.themoviedb.org\" target=\"_blank\" rel=\"noopener noreferrer\">TMDB</a></footer>\n</div>\n<div class=\"player-modal\"",
    1,
)
card_pattern = r"function card\(w\)\{.*?\}\nasync function loadWorks"
card_replacement = r'''function card(w){const c=node('article','card'),poster=node('div','poster');if(w.posterUrl){const img=document.createElement('img');img.src=w.posterUrl;img.alt=`${w.title} ポスター`;img.loading='lazy';img.onerror=()=>{poster.replaceChildren(node('div','poster-fallback',w.title))};poster.append(img)}else poster.append(node('div','poster-fallback',w.title));c.append(poster);const body=node('div','card-body');body.append(node('div','badge',w.category+(w.favorite?' · ★ お気に入り':'')));body.append(node('h2','',w.title));body.append(node('div','source',w.sourceTitle&&w.sourceTitle!==w.title?w.sourceTitle:''));if(w.progress.total)body.append(node('div','meta',`視聴 ${w.progress.watched}/${w.progress.total} (${w.progress.percent}%)`));const f=node('div','card-foot');f.append(node('span','',w.yearOrPeriod||'年不明'));f.append(node('span',w.availableVideoCount?'available':'',w.availableVideoCount?`${w.availableVideoCount}/${w.videoCount} 利用可`:`${w.videoCount}動画`));body.append(f);c.append(body);c.onclick=()=>location.hash=`#/work/${w.id}`;return c}
async function loadWorks'''
html, count = re.subn(card_pattern, card_replacement, html, count=1, flags=re.S)
if count != 1:
    raise SystemExit(f"card function replacement count={count}")
show_pattern = r"async function showWork\(id\)\{.*?\}\nfunction es\(v\)"
show_replacement = r'''async function showWork(id){$('continueSection').hidden=true;$('nextSection').hidden=true;$('catalog').hidden=true;$('detail').hidden=false;const w=await api(`/api/works/${id}`),r=document.createDocumentFragment(),h=node('div','hero');if(w.backdropUrl){h.classList.add('has-backdrop');h.style.backgroundImage=`url("${w.backdropUrl}")`}const layout=node('div','hero-layout');if(w.posterUrl){const img=document.createElement('img');img.className='hero-poster';img.src=w.posterUrl;img.alt=`${w.title} ポスター`;img.onerror=()=>img.remove();layout.append(img)}const heroBody=node('div','hero-body'),line=node('div','hero-line'),title=node('div');title.append(node('div','badge',w.category),node('h2','',w.title),node('div','meta',`視聴 ${w.progress.watched}/${w.progress.total} · 検出字幕 ${w.availableSubtitleCount??0}`));line.append(title);const a=node('div','hero-actions'),fav=node('button','action'+(w.favorite?' on':''),w.favorite?'★ お気に入り':'☆ お気に入り');fav.onclick=async()=>{w.favorite=!w.favorite;await api(`/api/me/works/${w.id}/favorite`,jo('PUT',{favorite:w.favorite}));fav.textContent=w.favorite?'★ お気に入り':'☆ お気に入り';fav.classList.toggle('on',w.favorite)};a.append(fav);line.append(a);heroBody.append(line);if(w.tmdb?.overview)heroBody.append(node('p','overview',w.tmdb.overview));const credits=node('div','credits'),director=creditRow('監督／演出',w.director),cast=creditRow('主な出演者／声優',w.cast);if(director)credits.append(director);if(cast)credits.append(cast);if(credits.childElementCount)heroBody.append(credits);layout.append(heroBody);h.append(layout);r.append(h);if(w.groups.length){const g=node('div','groups');w.groups.forEach((x,i)=>{const b=node('button','group'+(i===0?' active':''),`${x.name} (${x.watchedCount}/${x.videoCount})`);b.onclick=()=>{document.querySelectorAll('.group').forEach(q=>q.classList.toggle('active',q===b));loadEpisodes(w.id,x.id)};g.append(b)});r.append(g);const ep=node('div','episodes');ep.id='episodes';r.append(ep);const vd=node('div');vd.id='videoDetail';r.append(vd)}else r.append(node('div','empty','この作品には登録済み動画がありません。'));$('workDetail').replaceChildren(r);if(w.groups.length)loadEpisodes(w.id,w.groups[0].id)}
function es(v)'''
html, count = re.subn(show_pattern, show_replacement, html, count=1, flags=re.S)
if count != 1:
    raise SystemExit(f"showWork replacement count={count}")
write(html_path, html)


# PWA: explicitly keep TMDb image responses out of Cache Storage; they are already persisted on disk.
replace_once(
    "windows-installer/src/service-worker.js",
    "url.pathname.startsWith('/subtitle/'))return;",
    "url.pathname.startsWith('/subtitle/')||url.pathname.startsWith('/tmdb-image/'))return;",
)


# README: add operator workflow and attribution note.
readme_path = "README.md"
readme = read(readme_path)
section = '''\n## TMDb作品照合とポスター（1.1.0）\n\nランチャーの `TMDb設定` で API Read Access Token を設定した後、ライブラリ停止中に `TMDb同期` を実行できます。作品名・年・種別から保守的に照合し、高信頼の `MATCHED` だけを自動確定して poster/backdrop を `%LOCALAPPDATA%\\VideoLibrary\\TMDbImages` に保存します。低信頼候補は `REVIEW` として監査CSVへ残し、画像は採用しません。\n\n同期結果は `%LOCALAPPDATA%\\VideoLibrary\\diagnostics\\tmdb-match-audit-*.json/.csv` に保存します。TMDb未設定や通信失敗でも、動画再生・字幕・利用者状態など既存機能はそのまま利用できます。\n\nTMDB attribution: This product uses the TMDB API but is not endorsed or certified by TMDB.\n'''
if "## TMDb作品照合とポスター（1.1.0）" not in readme:
    readme = readme.rstrip() + "\n" + section
write(readme_path, readme)
