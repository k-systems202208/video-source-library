from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'windows-installer'/'src'

# server static assets
p=SRC/'server.py'; s=p.read_text(encoding='utf-8')
needle='    "/icon.svg": ("icon.svg", "image/svg+xml"),\n}'
repl='    "/icon.svg": ("icon.svg", "image/svg+xml"),\n    "/cinema-header.svg": ("cinema-header.svg", "image/svg+xml"),\n    "/cinema-sidebar.svg": ("cinema-sidebar.svg", "image/svg+xml"),\n    "/cinema-footer.svg": ("cinema-footer.svg", "image/svg+xml"),\n}'
assert needle in s
p.write_text(s.replace(needle,repl),encoding='utf-8')

# pyinstaller assets
p=ROOT/'windows-installer'/'build'/'VideoLibrary.spec'; s=p.read_text(encoding='utf-8')
needle='    "icon.svg",\n]'
repl='    "icon.svg",\n    "cinema-header.svg",\n    "cinema-sidebar.svg",\n    "cinema-footer.svg",\n]'
assert needle in s
p.write_text(s.replace(needle,repl),encoding='utf-8')

# UI shell
p=SRC/'video-library.html'; s=p.read_text(encoding='utf-8')
assert 'CINEMA_IMAGE_RESPONSIVE_V1' not in s
css=r'''
    /* CINEMA_IMAGE_RESPONSIVE_V1 */
    :root{--cinema-nav-w:228px;--cinema-footer-h:70px}
    body{background:#0b0908}
    .cinema-nav{display:none}
    .cinema-nav-backdrop{display:none}
    .mobile-menu-toggle,.cinema-nav-close{display:none}
    .header-search-wrap{display:flex;align-items:center;gap:8px;min-width:min(320px,34vw)}
    .header-search{width:100%;background:rgba(8,7,6,.78);border:1px solid #8b6a3d;color:var(--cream);padding:10px 13px;border-radius:7px;box-shadow:inset 0 0 0 1px rgba(255,220,150,.05)}
    .header-search::placeholder{color:#998d7b}
    header{background-image:linear-gradient(90deg,rgba(14,10,8,.28),rgba(14,10,8,.08),rgba(14,10,8,.35)),url('/cinema-header.svg');background-size:auto 100%,cover;background-position:center;background-repeat:no-repeat;min-height:112px}
    header .brand{background:linear-gradient(#e4c98e,#a97c39);padding:8px 18px;border:4px solid #5d3519;outline:1px solid #d9b86e;box-shadow:0 5px 18px rgba(0,0,0,.45);text-align:center;min-width:260px}
    header .brand-kicker{color:#4c2b16}.brand h1{color:#26150d;text-shadow:0 1px #f4dfac}.brand p{color:#56351f;margin-top:2px}
    .cinema-footer{position:relative;margin:26px -20px -80px;padding:20px 30px 22px;min-height:var(--cinema-footer-h);background:url('/cinema-footer.svg') center/cover no-repeat;border-top:1px solid #a97a36;color:#ead9b4;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:18px;font-family:"Yu Mincho","Hiragino Mincho ProN",serif;letter-spacing:.1em}
    .cinema-footer .tmdb-credit{margin:0;padding:0;border:0;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;letter-spacing:0;text-align:center;color:#b4a78f;font-size:10px}
    .cinema-footer-copy:last-child{text-align:right}
    .cinema-footer-mark{display:none}
    .app{transition:filter .2s ease}
    .cinema-nav-item{appearance:none;width:100%;border:0;background:transparent;color:#eadfc7;text-align:left;padding:15px 18px;display:grid;grid-template-columns:34px 1fr;gap:10px;align-items:center;border-bottom:1px solid rgba(181,137,73,.22);cursor:pointer;font-family:"Yu Mincho","Hiragino Mincho ProN",serif;font-size:16px}
    .cinema-nav-item small{display:block;color:#9d8d78;font:11px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif;margin-top:2px}
    .cinema-nav-item:hover,.cinema-nav-item:focus-visible{background:linear-gradient(90deg,rgba(132,31,32,.88),rgba(91,22,23,.5));outline:1px solid #c39243;outline-offset:-3px;color:#fff3d4}
    .cinema-nav-icon{color:#e1b75f;font-size:24px;text-align:center}
    .cinema-nav-brand{text-align:center;padding:20px 10px 14px;border-bottom:1px solid rgba(193,147,75,.5);font-family:"Yu Mincho","Hiragino Mincho ProN",serif;color:#f0ddae}.cinema-nav-brand strong{display:block;font-size:23px;letter-spacing:.08em}.cinema-nav-brand small{font-size:10px;letter-spacing:.18em;color:#c9aa6d}
    .cinema-nav-art{position:absolute;left:0;right:0;bottom:0;height:42%;background:url('/cinema-sidebar.svg') center bottom/cover no-repeat;opacity:.82;pointer-events:none;mask-image:linear-gradient(transparent,#000 25%)}
    @media(min-width:1200px){
      body{padding-left:var(--cinema-nav-w)}
      .cinema-nav{display:block;position:fixed;z-index:900;left:0;top:0;bottom:0;width:var(--cinema-nav-w);background:linear-gradient(rgba(12,10,8,.94),rgba(12,9,7,.9)),url('/cinema-sidebar.svg') center/cover no-repeat;border-right:1px solid #8b6737;box-shadow:10px 0 30px rgba(0,0,0,.35);overflow:hidden}
      .cinema-nav nav{position:relative;z-index:1}.cinema-nav-art{display:block}
      .app{max-width:1500px;padding-top:12px}
      header{display:grid;grid-template-columns:minmax(270px,.8fr) minmax(320px,1.2fr) auto;align-items:center}
      .brand{justify-self:center}.header-search-wrap{grid-column:2;grid-row:1;justify-self:stretch}.header-actions{grid-column:3;grid-row:1}
    }
    @media(min-width:768px) and (max-width:1199px){
      .mobile-menu-toggle{display:grid;place-items:center;position:fixed;z-index:940;left:14px;top:18px;width:44px;height:44px;border:1px solid #b18446;background:#17110d;color:#f2d796;border-radius:6px;font-size:22px;box-shadow:0 5px 18px #0008;cursor:pointer}
      .cinema-nav{display:block;position:fixed;z-index:960;left:0;top:0;bottom:0;width:min(300px,78vw);transform:translateX(-102%);transition:transform .22s ease;background:linear-gradient(rgba(12,10,8,.95),rgba(12,9,7,.91)),url('/cinema-sidebar.svg') center/cover no-repeat;border-right:1px solid #8b6737;box-shadow:16px 0 40px rgba(0,0,0,.55);overflow:auto}.cinema-nav.open{transform:none}
      .cinema-nav-backdrop{display:block;position:fixed;z-index:950;inset:0;background:#0009;opacity:0;pointer-events:none;transition:opacity .2s}.cinema-nav-backdrop.open{opacity:1;pointer-events:auto}
      .cinema-nav-close{display:block;position:absolute;right:8px;top:8px;background:#160f0b;border:1px solid #846238;color:#ecd49b;width:36px;height:36px;border-radius:5px;cursor:pointer}
      header{padding-left:64px;display:grid;grid-template-columns:1fr minmax(220px,34vw) auto}.header-search-wrap{display:flex}.brand h1{font-size:24px}.brand p,.brand-kicker{display:none}.header-actions .stats,.header-actions .scan-status,.header-actions .user{display:none}
      .app{max-width:100%;padding-left:18px;padding-right:18px}.cinema-footer{margin-left:-18px;margin-right:-18px}
    }
    @media(max-width:767px){
      .mobile-menu-toggle{display:grid;place-items:center;position:fixed;z-index:940;left:10px;top:12px;width:40px;height:40px;border:1px solid #b18446;background:#17110d;color:#f2d796;border-radius:5px;font-size:20px;box-shadow:0 4px 14px #0009;cursor:pointer}
      .cinema-nav{display:block;position:fixed;z-index:960;left:0;top:0;bottom:0;width:min(310px,86vw);transform:translateX(-102%);transition:transform .22s ease;background:linear-gradient(rgba(12,10,8,.96),rgba(12,9,7,.92)),url('/cinema-sidebar.svg') center/cover no-repeat;border-right:1px solid #8b6737;box-shadow:16px 0 40px rgba(0,0,0,.6);overflow:auto}.cinema-nav.open{transform:none}
      .cinema-nav-backdrop{display:block;position:fixed;z-index:950;inset:0;background:#000b;opacity:0;pointer-events:none;transition:opacity .2s}.cinema-nav-backdrop.open{opacity:1;pointer-events:auto}
      .cinema-nav-close{display:block;position:absolute;right:8px;top:8px;background:#160f0b;border:1px solid #846238;color:#ecd49b;width:36px;height:36px;border-radius:5px}
      .app{padding:8px 10px 72px;max-width:none}header{min-height:74px;padding:8px 8px 8px 52px;display:grid;grid-template-columns:1fr 42px;gap:8px;background-size:auto 100%,cover;margin-bottom:12px}
      header .brand{min-width:0;padding:5px 9px;border-width:2px}.brand-kicker,.brand p{display:none}.brand h1{font-size:19px;white-space:nowrap}.brand-mark{font-size:.7em}
      .header-actions{display:none}.header-search-wrap{min-width:0}.header-search{padding:9px 10px;font-size:13px}
      .catalog-tools{grid-template-columns:1fr}.catalog-heading{align-items:end}.catalog-title-block p{display:none}.catalog-count{font-size:11px}
      .cinema-footer{margin:20px -10px -72px;padding:15px 12px 18px;min-height:58px;grid-template-columns:1fr;text-align:center}.cinema-footer-copy{display:none}.cinema-footer .tmdb-credit{text-align:center;font-size:9px}
      .hero-layout{grid-template-columns:92px minmax(0,1fr);gap:13px}.hero-poster{width:92px}.hero h2{font-size:30px}.overview{grid-column:1/-1}.credit-row{grid-template-columns:1fr}.credit-label{padding-top:0}.person-link{min-height:38px}
      .mini{min-width:82vw}.grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.card-body{padding:10px}.card h2{font-size:15px}.poster{aspect-ratio:2/3}
      .strip-scroll-hint{width:42px}.toolbar{margin-bottom:8px}
    }
    @media(max-width:480px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.card .source{display:none}.card-foot{font-size:10px}.hero-layout{grid-template-columns:82px minmax(0,1fr)}.hero-poster{width:82px}.hero h2{font-size:26px}.header-search{font-size:12px}}
'''
s=s.replace('</style>',css+'\n</style>')
body_marker='<body>\n<div class="app">'
body_repl='''<body>\n<button class="mobile-menu-toggle" id="mobileMenuToggle" type="button" aria-label="館内メニューを開く" aria-controls="cinemaNav" aria-expanded="false">☰</button>\n<div class="cinema-nav-backdrop" id="cinemaNavBackdrop"></div>\n<aside class="cinema-nav" id="cinemaNav" aria-label="館内メニュー">\n  <button class="cinema-nav-close" id="cinemaNavClose" type="button" aria-label="館内メニューを閉じる">×</button>\n  <div class="cinema-nav-brand"><span aria-hidden="true">◉</span><strong>シネマ蔵書館</strong><small>PRIVATE CINEMA ARCHIVE</small></div>\n  <nav>\n    <button class="cinema-nav-item" type="button" data-scroll-target="continueSection"><span class="cinema-nav-icon">●</span><span>上映中<small>いま観られる作品</small></span></button>\n    <button class="cinema-nav-item" type="button" data-scroll-target="nextSection"><span class="cinema-nav-icon">◆</span><span>次回上映<small>次に観る作品</small></span></button>\n    <button class="cinema-nav-item" type="button" data-scroll-target="catalog"><span class="cinema-nav-icon">▣</span><span>作品目録<small>すべての作品</small></span></button>\n    <a class="cinema-nav-item" href="/diagnostics.html" style="text-decoration:none"><span class="cinema-nav-icon">◎</span><span>診断<small>ライブラリ状態</small></span></a>\n    <button class="cinema-nav-item" type="button" id="navScan"><span class="cinema-nav-icon">↻</span><span>再スキャン<small>蔵書を更新</small></span></button>\n  </nav>\n  <div class="cinema-nav-art" aria-hidden="true"></div>\n</aside>\n<div class="app">'''
assert body_marker in s
s=s.replace(body_marker,body_repl,1)
old_header='''  <header>\n    <div class="brand"><div class="brand-kicker">PRIVATE CINEMA ARCHIVE</div><h1><span class="brand-mark" aria-hidden="true">◉</span> シネマ蔵書館</h1><p>映画で、また会える。</p></div>\n    <div class="header-actions"><div><div class="user" id="currentUser"></div><div class="stats" id="stats">読み込み中...</div><div class="scan-status" id="scanStatus"></div></div><button class="ghost" id="scanButton">再スキャン</button></div>\n  </header>'''
new_header='''  <header>\n    <div class="brand"><div class="brand-kicker">PRIVATE CINEMA ARCHIVE</div><h1><span class="brand-mark" aria-hidden="true">◉</span> シネマ蔵書館</h1><p>映画で、また会える。</p></div>\n    <label class="header-search-wrap"><span class="sr-only">作品検索</span><input id="headerSearch" class="header-search" type="search" placeholder="作品・俳優・監督を検索..."></label>\n    <div class="header-actions"><div><div class="user" id="currentUser"></div><div class="stats" id="stats">読み込み中...</div><div class="scan-status" id="scanStatus"></div></div><button class="ghost" id="scanButton">再スキャン</button></div>\n  </header>'''
assert old_header in s
s=s.replace(old_header,new_header,1)
old_footer='''  <footer class="tmdb-credit">This product uses the TMDB API but is not endorsed or certified by TMDB. · <a href="https://www.themoviedb.org" target="_blank" rel="noopener noreferrer">TMDB</a></footer>'''
new_footer='''  <footer class="cinema-footer"><div class="cinema-footer-copy">映画は、人生のよき友だ。</div><div class="tmdb-credit">This product uses the TMDB API but is not endorsed or certified by TMDB. · <a href="https://www.themoviedb.org" target="_blank" rel="noopener noreferrer">TMDB</a></div><div class="cinema-footer-copy">よい映画で、よい時間を。</div></footer>'''
assert old_footer in s
s=s.replace(old_footer,new_footer,1)
js_marker="async function api(p,o={})"
nav_js=r'''function setCinemaNav(open){const nav=$('cinemaNav'),back=$('cinemaNavBackdrop'),toggle=$('mobileMenuToggle');nav.classList.toggle('open',open);back.classList.toggle('open',open);toggle.setAttribute('aria-expanded',open?'true':'false');document.body.classList.toggle('cinema-nav-open',open)}
$('mobileMenuToggle').onclick=()=>setCinemaNav(!$('cinemaNav').classList.contains('open'));
$('cinemaNavClose').onclick=()=>setCinemaNav(false);$('cinemaNavBackdrop').onclick=()=>setCinemaNav(false);
document.querySelectorAll('[data-scroll-target]').forEach(b=>b.onclick=()=>{const target=$(b.dataset.scrollTarget);if(target&&!target.hidden)target.scrollIntoView({behavior:'smooth',block:'start'});else if(b.dataset.scrollTarget==='catalog'){location.hash='#/library';setTimeout(()=>$('catalog').scrollIntoView({behavior:'smooth'}),20)}setCinemaNav(false)});
$('navScan').onclick=()=>{$('scanButton').click();setCinemaNav(false)};
$('headerSearch').addEventListener('input',e=>{$('search').value=e.target.value;$('search').dispatchEvent(new Event('input',{bubbles:true}))});
$('search').addEventListener('input',e=>{if(document.activeElement!==$('headerSearch'))$('headerSearch').value=e.target.value});
window.addEventListener('hashchange',()=>setCinemaNav(false));
'''
assert js_marker in s
s=s.replace(js_marker,nav_js+js_marker,1)
# utility for screen readers
s=s.replace('*{box-sizing:border-box}', '*{box-sizing:border-box}.sr-only{position:absolute!important;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}')
p.write_text(s,encoding='utf-8')

# docs
(ROOT/'docs'/'58-1.1.0-image-responsive-cinema-ui.md').write_text('''# 1.1.0 画像パーツ化・レスポンシブ映画館UI\n\nIssue #134。Run #185 のシネマ蔵書館を、共有モックアップへさらに近づける。\n\n- header / side menu / footer を SVG 装飾画像として分離\n- 文字・検索・ボタン・リンクは HTML のまま保持\n- PC (1200px+) は左館内メニュー常設\n- Tablet (768-1199px) は開閉ドロワー\n- Smartphone (767px以下) は簡略ヘッダー＋ドロワー＋1カラム寄りの詳細\n- ヘッダー検索は既存目録検索と同期\n- 再生、TMDb、人物リンク、お気に入り、検索ロジック、ページングは変更しない\n- 表示バージョンは 1.1.0 のまま\n''',encoding='utf-8')

# regression test
(ROOT/'tests'/'test_image_responsive_cinema_ui_v110.py').write_text('''from pathlib import Path\nimport unittest\n\nROOT=Path(__file__).resolve().parents[1]\nHTML=(ROOT/'windows-installer'/'src'/'video-library.html').read_text(encoding='utf-8')\nSERVER=(ROOT/'windows-installer'/'src'/'server.py').read_text(encoding='utf-8')\nSPEC=(ROOT/'windows-installer'/'build'/'VideoLibrary.spec').read_text(encoding='utf-8')\n\nclass ImageResponsiveCinemaUiTests(unittest.TestCase):\n    def test_image_assets_are_served_and_packaged(self):\n        for name in ('cinema-header.svg','cinema-sidebar.svg','cinema-footer.svg'):\n            self.assertIn(name,SERVER)\n            self.assertIn(name,SPEC)\n            self.assertTrue((ROOT/'windows-installer'/'src'/name).is_file())\n    def test_responsive_shell_exists(self):\n        self.assertIn('CINEMA_IMAGE_RESPONSIVE_V1',HTML)\n        self.assertIn('id="cinemaNav"',HTML)\n        self.assertIn('id="mobileMenuToggle"',HTML)\n        self.assertIn('@media(min-width:1200px)',HTML)\n        self.assertIn('@media(min-width:768px) and (max-width:1199px)',HTML)\n        self.assertIn('@media(max-width:767px)',HTML)\n    def test_header_search_reuses_existing_search(self):\n        self.assertIn('id="headerSearch"',HTML)\n        self.assertIn("$('search').dispatchEvent(new Event('input'",HTML)\n    def test_existing_features_remain(self):\n        self.assertIn('FEATURE PRESENTATION',HTML)\n        self.assertIn('上映プログラム',HTML)\n        self.assertIn('上映目録',HTML)\n        self.assertIn('const PAGE=60',HTML)\n        self.assertIn('/api/me/continue-watching',HTML)\n        self.assertIn('/api/me/next-up',HTML)\n\nif __name__=='__main__': unittest.main()\n''',encoding='utf-8')
print('patched')
