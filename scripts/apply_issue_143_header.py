from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "windows-installer" / "src" / "video-library.html"
MANIFEST = ROOT / "windows-installer" / "src" / "manifest.webmanifest"
RESP_TEST = ROOT / "tests" / "test_image_responsive_cinema_ui_v110.py"
TMDB_TEST = ROOT / "tests" / "test_tmdb_multi_image_repair_v110.py"
DOC = ROOT / "docs" / "63-1.1.0-sekimachi-kita-cinema-header.md"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


html = HTML.read_text(encoding="utf-8")

old_header = '''  <header>
    <button class="brand cinema-home-reset" id="headerBrandReset" type="button" aria-label="シネマ蔵書館を初期状態で再読み込み"><div class="brand-kicker">PRIVATE CINEMA ARCHIVE</div><h1><span class="brand-mark" aria-hidden="true">◉</span> シネマ蔵書館</h1><p>映画で、また会える。</p></button>
    <label class="header-search-wrap"><span class="sr-only">作品検索</span><input id="headerSearch" class="header-search" type="search" placeholder="作品・俳優・監督を検索..."></label>
    <div class="header-actions"><div><div class="user" id="currentUser"></div><div class="stats" id="stats">読み込み中...</div><div class="scan-status" id="scanStatus"></div></div><button class="ghost" id="scanButton">再スキャン</button></div>
  </header>'''
new_header = '''  <header>
    <button class="brand cinema-home-reset" id="headerBrandReset" type="button" aria-label="関町北映画館を初期状態で再読み込み"><div class="brand-kicker">PRIVATE CINEMA ARCHIVE</div><h1><span class="brand-mark" aria-hidden="true">◉</span> 関町北映画館</h1></button>
  </header>'''
html = replace_once(html, old_header, new_header, "header markup")

# Site name: browser title, side navigation brand and reset labels.
html = html.replace("シネマ蔵書館", "関町北映画館")
html = replace_once(
    html,
    "$('headerSearch').addEventListener('input',e=>{$('search').value=e.target.value;$('search').dispatchEvent(new Event('input',{bubbles:true}))});\n$('search').addEventListener('input',e=>{if(document.activeElement!==$('headerSearch'))$('headerSearch').value=e.target.value});\n",
    "",
    "header search synchronization",
)
html = replace_once(
    html,
    "function clearPersonSearchFilter(){if(!state.person)return false;state.person='';state.q='';$('search').value='';$('headerSearch').value='';return true}",
    "function clearPersonSearchFilter(){if(!state.person)return false;state.person='';state.q='';$('search').value='';return true}",
    "header search clear",
)
html = replace_once(
    html,
    "async function loadStats(){const s=await api('/api/stats');$('stats').textContent=`${s.works}作品 / ${s.videos}動画 / 字幕 ${s.subtitles??0}`;",
    "async function loadStats(){const s=await api('/api/stats');const stats=$('stats');if(stats)stats.textContent=`${s.works}作品 / ${s.videos}動画 / 字幕 ${s.subtitles??0}`;",
    "optional header stats",
)
html = replace_once(
    html,
    "async function loadUser(){const r=await api('/api/current-user');$('currentUser').textContent=r.authenticated?`利用者: ${r.user.displayName}`:'匿名利用'}",
    "async function loadUser(){const currentUser=$('currentUser');if(!currentUser)return;const r=await api('/api/current-user');currentUser.textContent=r.authenticated?`利用者: ${r.user.displayName}`:'匿名利用'}",
    "optional header user",
)
html = replace_once(
    html,
    "$('loadMore').onclick=()=>loadWorks(false);$('back').onclick=()=>location.hash=state.person?`#/person/${encodeURIComponent(state.person)}`:'#/library';$('scanButton').onclick=runScan;$('scanClose').onclick=hideScanModal;window.onhashchange=route;",
    "$('loadMore').onclick=()=>loadWorks(false);$('back').onclick=()=>location.hash=state.person?`#/person/${encodeURIComponent(state.person)}`:'#/library';$('scanClose').onclick=hideScanModal;window.onhashchange=route;",
    "scan button binding",
)
html = replace_once(
    html,
    "(async()=>{await Promise.all([loadStats(),loadUser(),loadScan(),loadHome()]);route()})();",
    "(async()=>{await Promise.all([loadStats(),loadHome()]);route()})();",
    "header-only startup calls",
)

header_css = r'''

    /* SEKIMACHI_KITA_CINEMA_HEADER_V1 */
    header{
      display:flex!important;align-items:center!important;justify-content:center!important;
      min-height:112px;padding:16px 20px 18px!important
    }
    header .brand{
      justify-self:auto!important;margin:0 auto!important;text-align:center!important;
      width:min(760px,78vw);min-width:0
    }
    .brand.cinema-home-reset{text-align:center!important}
    header .brand p,.header-search-wrap,.header-actions{display:none!important}
    @media(min-width:1200px){
      header{display:flex!important;justify-content:center!important}
      header .brand{justify-self:auto!important;width:min(760px,72%);padding:10px 22px}
    }
    @media(min-width:768px) and (max-width:1199px){
      header{display:flex!important;justify-content:center!important;min-height:96px;padding:12px 68px!important}
      header .brand{width:min(650px,86%);padding:8px 18px}
      header .brand-kicker{display:none}
      header .brand h1{font-size:clamp(24px,3.6vw,31px)}
    }
    @media(max-width:767px){
      header{display:flex!important;justify-content:center!important;min-height:74px;padding:8px 56px!important;margin-bottom:12px}
      header .brand{width:100%;max-width:620px;padding:6px 10px;border-width:2px}
      header .brand-kicker{display:none}
      header .brand h1{font-size:clamp(18px,5.4vw,24px);white-space:nowrap}
      header .brand-mark{font-size:.7em}
    }
'''
html = replace_once(html, "\n    /* NAVIGATION_PEOPLE_MENU_V1 */", header_css + "\n    /* NAVIGATION_PEOPLE_MENU_V1 */", "header CSS insertion")

for forbidden in ('id="headerSearch"', 'id="scanButton"', '映画で、また会える。'):
    if forbidden in html:
        raise RuntimeError(f"header cleanup failed: {forbidden}")
if "<title>関町北映画館</title>" not in html or "<strong>関町北映画館</strong>" not in html:
    raise RuntimeError("site rename incomplete")

HTML.write_text(html, encoding="utf-8")

manifest = MANIFEST.read_text(encoding="utf-8")
manifest = replace_once(manifest, '"name": "自宅動画ライブラリ"', '"name": "関町北映画館"', "manifest name")
manifest = replace_once(manifest, '"short_name": "動画ライブラリ"', '"short_name": "関町北映画館"', "manifest short name")
MANIFEST.write_text(manifest, encoding="utf-8")

resp = RESP_TEST.read_text(encoding="utf-8")
old_resp = '''    def test_header_search_reuses_existing_search(self):
        self.assertIn('id="headerSearch"',HTML)
        self.assertIn("$('search').dispatchEvent(new Event('input'",HTML)
'''
new_resp = '''    def test_header_is_centered_and_header_controls_are_removed(self):
        self.assertIn('SEKIMACHI_KITA_CINEMA_HEADER_V1',HTML)
        self.assertIn('<title>関町北映画館</title>',HTML)
        self.assertIn('<strong>関町北映画館</strong>',HTML)
        self.assertNotIn('シネマ蔵書館',HTML)
        self.assertNotIn('id="headerSearch"',HTML)
        self.assertNotIn('id="scanButton"',HTML)
        self.assertNotIn('映画で、また会える。',HTML)
        self.assertIn('justify-content:center!important',HTML)
'''
resp = replace_once(resp, old_resp, new_resp, "responsive header test")
RESP_TEST.write_text(resp, encoding="utf-8")

tmdb = TMDB_TEST.read_text(encoding="utf-8")
old_tmdb = '''    def test_desktop_header_brand_is_left_aligned_only_in_desktop_rule(self):
        html = (SRC / "video-library.html").read_text(encoding="utf-8")
        desktop = html[html.index("@media(min-width:1200px){"):html.index("@media(min-width:768px) and (max-width:1199px){")]
        self.assertIn("header .brand{justify-self:start}", desktop)
'''
new_tmdb = '''    def test_header_brand_has_centered_override_for_all_breakpoints(self):
        html = (SRC / "video-library.html").read_text(encoding="utf-8")
        marker = html[html.index("/* SEKIMACHI_KITA_CINEMA_HEADER_V1 */"):html.index("/* NAVIGATION_PEOPLE_MENU_V1 */")]
        self.assertIn("justify-content:center!important", marker)
        self.assertIn("@media(min-width:1200px)", marker)
        self.assertIn("@media(min-width:768px) and (max-width:1199px)", marker)
        self.assertIn("@media(max-width:767px)", marker)
        self.assertNotIn("justify-self:start", marker)
'''
tmdb = replace_once(tmdb, old_tmdb, new_tmdb, "TMDb header regression test")
TMDB_TEST.write_text(tmdb, encoding="utf-8")

DOC.write_text('''# 1.1.0 関町北映画館ヘッダー整理\n\n## 変更内容\n\n- サイト名を「シネマ蔵書館」から「関町北映画館」へ変更。\n- PC / Tablet / Smartphone のヘッダー館名をすべて中央配置へ統一。\n- Smartphone は左側のハンバーガーボタンと独立して、館名がヘッダー中央に見えるよう左右同量の余白を確保。\n- ヘッダーの検索テキストボックスを削除。作品検索は作品目録内の検索欄に一本化。\n- ヘッダーの再スキャンボタンとステータス表示を削除。\n- 「映画で、また会える。」を削除。\n- PWA manifest の名称も「関町北映画館」に統一。\n- 表示バージョンは 1.1.0 を維持。\n\n## 維持する機能\n\n左メニュー、上映中、次回上映、作品目録、監督／演出、出演者／声優、再生、TMDb、人物リンク、お気に入り、作品目録内検索、カテゴリ、並び替え、ページングは変更しない。\n\n## 回帰確認\n\n- PC (1200px以上)\n- Tablet (768px〜1199px)\n- Smartphone (767px以下)\n\n上記3ブレークポイントで館名中央配置を固定し、旧ヘッダー検索・再スキャン・旧キャッチコピーがDOMに残らないことをテストする。\n''', encoding="utf-8")

print("issue 143 header migration applied")
