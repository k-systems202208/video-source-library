from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
HTML = SRC / "video-library.html"
SERVER = SRC / "server.py"
SPEC = ROOT / "windows-installer" / "build" / "VideoLibrary.spec"
SW = SRC / "service-worker.js"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"patch anchor not found: {label}")
    return text.replace(old, new, 1)


server = SERVER.read_text(encoding="utf-8")
if '"/cinema-header.svg"' not in server:
    server = replace_once(
        server,
        '    "/icon.svg": ("icon.svg", "image/svg+xml"),\n}',
        '    "/icon.svg": ("icon.svg", "image/svg+xml"),\n'
        '    "/cinema-header.svg": ("cinema-header.svg", "image/svg+xml"),\n'
        '    "/cinema-sidebar.svg": ("cinema-sidebar.svg", "image/svg+xml"),\n'
        '    "/cinema-footer.svg": ("cinema-footer.svg", "image/svg+xml"),\n}',
        "server static assets",
    )
SERVER.write_text(server, encoding="utf-8")

spec = SPEC.read_text(encoding="utf-8")
if '"cinema-header.svg"' not in spec:
    spec = replace_once(
        spec,
        '    "icon.svg",\n]',
        '    "icon.svg",\n    "cinema-header.svg",\n    "cinema-sidebar.svg",\n    "cinema-footer.svg",\n]',
        "pyinstaller assets",
    )
SPEC.write_text(spec, encoding="utf-8")

sw = SW.read_text(encoding="utf-8")
sw = sw.replace("video-library-shell-v3", "video-library-shell-v4")
if "cinema-header.svg" not in sw:
    sw = replace_once(
        sw,
        "const SHELL=['/','/manifest.webmanifest','/offline.html','/icon.svg'];",
        "const SHELL=['/','/manifest.webmanifest','/offline.html','/icon.svg','/cinema-header.svg','/cinema-sidebar.svg','/cinema-footer.svg'];",
        "service worker shell",
    )
SW.write_text(sw, encoding="utf-8")

html = HTML.read_text(encoding="utf-8")
if "CINEMA_LIBRARY_IMAGE_RESPONSIVE_V5" not in html:
    css = r'''
    /* CINEMA_LIBRARY_IMAGE_RESPONSIVE_V5 */
    :root{--cinema-chrome-header:112px;--cinema-chrome-sidebar:220px;--cinema-bottom-nav:66px}
    html{scroll-padding-top:calc(var(--cinema-chrome-header) + 18px)}
    body.cinema-image-chrome{background:#0a0807 radial-gradient(circle at 55% -10%,rgba(111,23,27,.18),transparent 38rem) fixed}
    body.cinema-image-chrome .app{max-width:none;margin:0;transition:padding .2s ease}
    body.cinema-image-chrome header{position:fixed;z-index:900;top:0;left:0;right:0;height:var(--cinema-chrome-header);margin:0;padding:15px 24px;display:flex;align-items:center;gap:14px;border:0;border-bottom:1px solid #9b6d30;border-radius:0;background-image:linear-gradient(90deg,rgba(7,5,4,.34),rgba(7,5,4,.03) 34%,rgba(7,5,4,.08) 66%,rgba(7,5,4,.64)),url('/cinema-header.svg');background-size:cover;background-position:center;box-shadow:0 10px 34px rgba(0,0,0,.55)}
    body.cinema-image-chrome header::before,body.cinema-image-chrome header::after{display:none}
    body.cinema-image-chrome header .brand{position:relative;z-index:2;min-width:280px;padding:9px 16px;border:1px solid rgba(193,145,65,.54);background:rgba(18,12,9,.82);box-shadow:inset 0 0 24px rgba(0,0,0,.4)}
    body.cinema-image-chrome header .brand h1{font-size:26px}
    body.cinema-image-chrome header .brand p{margin-top:3px;font-size:10px}
    .cinema-marquee-title{position:absolute;left:50%;top:18px;transform:translateX(-50%);z-index:1;width:min(470px,35vw);height:76px;display:flex;flex-direction:column;align-items:center;justify-content:center;pointer-events:none;text-align:center;color:#f3dfb6;text-shadow:0 2px 3px #000}
    .cinema-marquee-title strong{font-family:"Yu Mincho","Hiragino Mincho ProN",Georgia,serif;font-size:29px;letter-spacing:.18em}
    .cinema-marquee-title small{margin-top:4px;color:#cfae70;font-family:Georgia,"Yu Mincho",serif;letter-spacing:.16em;font-size:9px}
    .cinema-header-tools{position:relative;z-index:2;margin-left:auto;display:flex;align-items:center;gap:8px}
    .cinema-header-search{width:330px;display:flex;align-items:center;gap:8px;border:1px solid #6d5335;background:rgba(10,8,7,.84);padding:7px 11px;box-shadow:inset 0 0 18px rgba(0,0,0,.55)}
    .cinema-header-search span{color:#d9ad61;font-size:18px}.cinema-header-search input{width:100%;min-width:0;border:0;outline:0;background:transparent;color:#f3ead8;font:inherit}.cinema-header-search input::placeholder{color:#9e8b70}
    .cinema-header-search-button{display:none;border:1px solid #7f5d30;background:#16110e;color:#e7bd72;width:42px;height:38px;cursor:pointer}
    body.cinema-image-chrome .header-actions{position:relative;z-index:2;gap:6px;margin-left:2px}
    body.cinema-image-chrome .header-actions>div{max-width:205px;opacity:.62}.cinema-image-chrome .header-actions .user,.cinema-image-chrome .header-actions .stats,.cinema-image-chrome .header-actions .scan-status{font-size:9px;line-height:1.25}
    body.cinema-image-chrome .header-actions .ghost{padding:7px 9px;border-radius:3px;background:rgba(20,14,11,.74)}

    .cinema-sidebar{position:fixed;z-index:920;left:0;top:var(--cinema-chrome-header);bottom:0;width:var(--cinema-chrome-sidebar);padding:16px 12px 26px;display:flex;flex-direction:column;overflow:auto;border-right:1px solid #805b2d;background-image:linear-gradient(180deg,rgba(8,6,5,.18),rgba(8,6,5,.54)),url('/cinema-sidebar.svg');background-size:cover;background-position:center bottom;box-shadow:12px 0 34px rgba(0,0,0,.38);transition:transform .25s ease}
    .cinema-side-brand{padding:12px 10px 16px;margin-bottom:10px;text-align:center;border-bottom:1px solid rgba(183,137,62,.46);font-family:"Yu Mincho","Hiragino Mincho ProN",serif;color:#f1d99a}.cinema-side-brand strong{display:block;font-size:18px;letter-spacing:.08em}.cinema-side-brand small{display:block;margin-top:4px;color:#af9876;font-size:9px;letter-spacing:.14em}
    .cinema-side-nav{display:grid;gap:7px}.cinema-nav-item{width:100%;display:grid;grid-template-columns:34px 1fr;grid-template-rows:auto auto;column-gap:8px;align-items:center;text-align:left;border:1px solid transparent;background:rgba(10,8,7,.52);color:#eadfc9;padding:10px 9px;cursor:pointer;text-decoration:none;transition:.16s ease}.cinema-nav-item:hover,.cinema-nav-item:focus-visible{outline:none;border-color:#b6873f;background:rgba(91,23,25,.76);box-shadow:inset 4px 0 #d3a14b}.cinema-nav-item.active{border-color:#d1a050;background:linear-gradient(90deg,rgba(125,28,30,.92),rgba(81,17,20,.78))}.cinema-nav-icon{grid-row:1/3;font-size:23px;color:#dfb35f;text-align:center}.cinema-nav-item strong{font-family:"Yu Mincho","Hiragino Mincho ProN",serif;font-size:15px}.cinema-nav-item small{color:#a9987c;font-size:9px;margin-top:2px}.cinema-side-copy{margin-top:auto;padding:16px 10px 2px;color:#d5b26f;font-family:"Yu Mincho",serif;font-size:11px;line-height:1.8;text-align:center;text-shadow:0 1px 2px #000}
    .cinema-menu-toggle{position:fixed;z-index:1002;top:17px;left:15px;width:44px;height:40px;border:1px solid #a87835;background:rgba(12,9,7,.88);color:#f0ce8a;font-size:22px;cursor:pointer;display:none}.cinema-drawer-overlay{position:fixed;z-index:910;inset:0;background:rgba(0,0,0,.66);backdrop-filter:blur(2px);display:none}.cinema-drawer-overlay.open{display:block}
    .cinema-tablet-nav{display:none}.cinema-bottom-nav{display:none}
    .cinema-footer-shell{position:relative;min-height:78px;margin:42px 0 -80px;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:20px 32px;background-image:linear-gradient(rgba(31,6,8,.16),rgba(10,4,4,.3)),url('/cinema-footer.svg');background-size:cover;background-position:center;border-top:1px solid #9a6d31;border-bottom:1px solid #5f3e20;color:#d3b171;font-family:"Yu Mincho","Hiragino Mincho ProN",serif;letter-spacing:.16em;font-size:11px}.cinema-footer-shell strong{color:#e7c782;font-weight:500;letter-spacing:.38em}.cinema-footer-shell .footer-tmdb{font-family:system-ui,sans-serif;letter-spacing:0;font-size:9px;color:#9f8e74}.cinema-footer-shell .footer-tmdb a{color:#cba45d}
    body.cinema-image-chrome .tmdb-credit{display:none}

    @media(min-width:1200px){
      body.cinema-image-chrome .app{padding:calc(var(--cinema-chrome-header) + 18px) 22px 116px calc(var(--cinema-chrome-sidebar) + 22px)}
      .cinema-sidebar{transform:none!important}.cinema-menu-toggle,.cinema-drawer-overlay,.cinema-tablet-nav,.cinema-bottom-nav{display:none!important}
      body.cinema-image-chrome main{max-width:1500px;margin:0 auto;width:100%}
    }
    @media(min-width:768px) and (max-width:1199px){
      :root{--cinema-chrome-header:88px}
      html{scroll-padding-top:146px}
      body.cinema-image-chrome .app{padding:148px 16px 102px}
      body.cinema-image-chrome header{height:88px;padding:10px 14px 10px 68px}
      body.cinema-image-chrome header .brand{display:none}.cinema-marquee-title{left:38%;top:11px;width:310px;height:64px}.cinema-marquee-title strong{font-size:23px}.cinema-header-search{width:250px}.cinema-image-chrome .header-actions{display:none}
      .cinema-menu-toggle{display:block;top:22px}.cinema-sidebar{top:0;z-index:1001;width:min(320px,82vw);transform:translateX(-104%);padding-top:74px}.cinema-sidebar.open{transform:translateX(0)}
      .cinema-tablet-nav{position:fixed;z-index:880;top:88px;left:0;right:0;height:48px;display:flex;align-items:stretch;justify-content:center;background:#120e0b;border-bottom:1px solid #62451f;box-shadow:0 7px 18px rgba(0,0,0,.3)}.cinema-tablet-nav button{min-width:126px;border:0;border-right:1px solid #3e2d1c;background:transparent;color:#d8c29b;font-family:"Yu Mincho",serif;cursor:pointer}.cinema-tablet-nav button:hover,.cinema-tablet-nav button:focus-visible{outline:none;background:#5f171b;color:#f5dfb2}
      .cinema-footer-shell{margin-left:-16px;margin-right:-16px}
      .grid{grid-template-columns:repeat(auto-fill,minmax(190px,1fr))}
    }
    @media(max-width:767px){
      :root{--cinema-chrome-header:68px}
      html{scroll-padding-top:82px}
      body.cinema-image-chrome .app{padding:82px 10px calc(var(--cinema-bottom-nav) + 26px)}
      body.cinema-image-chrome header{height:68px;padding:7px 58px;background-position:center top}
      body.cinema-image-chrome header .brand,.cinema-image-chrome .header-actions{display:none}.cinema-marquee-title{position:static;transform:none;width:100%;height:auto;margin:auto}.cinema-marquee-title strong{font-size:20px;letter-spacing:.10em}.cinema-marquee-title small{display:none}.cinema-header-tools{position:absolute;right:10px;margin:0}.cinema-header-search{display:none}.cinema-header-search-button{display:block}
      .cinema-menu-toggle{display:block;top:14px;left:10px}.cinema-sidebar{top:0;z-index:1101;width:min(318px,86vw);transform:translateX(-104%);padding:76px 12px 28px}.cinema-sidebar.open{transform:translateX(0)}.cinema-drawer-overlay{z-index:1090}
      .cinema-tablet-nav{display:none}.cinema-bottom-nav{position:fixed;z-index:980;left:0;right:0;bottom:0;height:var(--cinema-bottom-nav);display:grid;grid-template-columns:repeat(4,1fr);padding-bottom:max(4px,env(safe-area-inset-bottom));background:rgba(15,10,8,.96);border-top:1px solid #8c642d;box-shadow:0 -8px 22px rgba(0,0,0,.46)}.cinema-bottom-nav button{border:0;border-right:1px solid #342417;background:transparent;color:#d1b987;font-size:10px;display:grid;place-items:center;align-content:center;gap:2px;cursor:pointer}.cinema-bottom-nav button span{font-size:19px;color:#dcae59}.cinema-bottom-nav button:focus-visible{outline:1px solid #d5a850;outline-offset:-3px}
      .hero-layout{grid-template-columns:1fr!important;gap:14px}.hero-poster{width:min(145px,46vw)!important;justify-self:center}.hero-body{text-align:left}.detail-feature,.hero-line{min-width:0}.overview{font-size:13px;line-height:1.7}.credit-row{grid-template-columns:1fr;gap:5px}.credit-label{padding-top:0}.person-link{padding:6px 9px}.groups{overflow-x:auto;flex-wrap:nowrap;padding-bottom:5px}.group{white-space:nowrap}.episodes{gap:7px}.episode{grid-template-columns:64px minmax(0,1fr);padding:10px}.episode-state{grid-column:2}.catalog-heading{align-items:flex-end}.catalog-heading h2{font-size:24px}.catalog-count strong{font-size:16px}.catalog-tools{padding:10px}.grid{gap:9px}.card-body{padding:10px 11px 12px}.card h2{font-size:15px}.home-strip{padding:10px}.mini{min-width:min(82vw,300px)}.cinema-footer-shell{min-height:92px;margin:30px -10px calc(-1 * (var(--cinema-bottom-nav) + 26px));padding:18px 14px 26px;display:grid;place-items:center;text-align:center}.cinema-footer-shell span:last-of-type{display:none}.cinema-footer-shell strong{font-size:10px}.cinema-footer-shell .footer-tmdb{font-size:8px}
    }
    @media(max-width:479px){.grid{grid-template-columns:1fr}.catalog-heading{display:block}.catalog-count{margin-top:10px;text-align:left;border-left:0;padding-left:0}.hero{padding:12px}.cinema-nav-item{padding:9px}.cinema-side-brand strong{font-size:17px}}
'''
    html = replace_once(html, "</style>", css + "\n  </style>", "html style end")

    js = r'''
<script>
(() => {
  'use strict';
  document.body.classList.add('cinema-image-chrome');
  const app=document.querySelector('.app'),header=app?.querySelector('header');
  if(!app||!header||document.getElementById('cinemaSidebar'))return;

  const marquee=document.createElement('div');
  marquee.className='cinema-marquee-title';
  marquee.innerHTML='<strong>シネマ蔵書館</strong><small>PRIVATE CINEMA ARCHIVE</small>';
  header.append(marquee);

  const tools=document.createElement('div');
  tools.className='cinema-header-tools';
  tools.innerHTML='<label class="cinema-header-search"><span aria-hidden="true">⌕</span><input id="cinemaHeaderSearch" type="search" placeholder="作品・俳優・監督で検索…" aria-label="作品・俳優・監督を検索"></label><button id="cinemaHeaderSearchButton" class="cinema-header-search-button" type="button" aria-label="作品目録を検索">⌕</button>';
  header.insertBefore(tools,header.querySelector('.header-actions'));

  const menuItems=[
    ['上映中','いま観られる作品','◉','continueSection'],
    ['次回上映','まもなく観る作品','▣','nextSection'],
    ['作品目録','すべての作品','▤','catalog'],
    ['検索','俳優・監督から探す','⌕','search'],
    ['診断','ライブラリ状態','◇','diagnostics'],
    ['再スキャン','作品を再確認','↻','rescan'],
  ];
  const navHtml=menuItems.map(([label,sub,icon,target])=>`<button class="cinema-nav-item" type="button" data-cinema-target="${target}"><span class="cinema-nav-icon" aria-hidden="true">${icon}</span><strong>${label}</strong><small>${sub}</small></button>`).join('');
  const sidebar=document.createElement('aside');
  sidebar.id='cinemaSidebar';sidebar.className='cinema-sidebar';sidebar.setAttribute('aria-label','シネマ蔵書館メニュー');
  sidebar.innerHTML=`<div class="cinema-side-brand"><strong>シネマ蔵書館</strong><small>PRIVATE CINEMA ARCHIVE</small></div><nav class="cinema-side-nav">${navHtml}</nav><div class="cinema-side-copy">よい映画を、いつまでも。<br>映画で、また会える。</div>`;
  document.body.append(sidebar);

  const overlay=document.createElement('div');overlay.id='cinemaDrawerOverlay';overlay.className='cinema-drawer-overlay';document.body.append(overlay);
  const toggle=document.createElement('button');toggle.id='cinemaMenuToggle';toggle.className='cinema-menu-toggle';toggle.type='button';toggle.setAttribute('aria-label','メニューを開く');toggle.setAttribute('aria-controls','cinemaSidebar');toggle.setAttribute('aria-expanded','false');toggle.textContent='☰';document.body.append(toggle);

  const tablet=document.createElement('nav');tablet.className='cinema-tablet-nav';tablet.setAttribute('aria-label','主要メニュー');tablet.innerHTML='<button type="button" data-cinema-target="continueSection">上映中</button><button type="button" data-cinema-target="nextSection">次回上映</button><button type="button" data-cinema-target="catalog">作品目録</button><button type="button" data-cinema-target="search">検索</button>';document.body.append(tablet);
  const bottom=document.createElement('nav');bottom.className='cinema-bottom-nav';bottom.setAttribute('aria-label','主要メニュー');bottom.innerHTML='<button type="button" data-cinema-target="continueSection"><span aria-hidden="true">◉</span>上映中</button><button type="button" data-cinema-target="nextSection"><span aria-hidden="true">▣</span>次回上映</button><button type="button" data-cinema-target="catalog"><span aria-hidden="true">▤</span>作品目録</button><button type="button" data-cinema-target="search"><span aria-hidden="true">⌕</span>検索</button>';document.body.append(bottom);

  const oldFooter=app.querySelector('.tmdb-credit');
  const footer=document.createElement('footer');footer.className='cinema-footer-shell';footer.innerHTML='<span>映画は、人生のよき友だ。</span><strong>PRIVATE CINEMA ARCHIVE</strong><span>よい映画で、よい時間を。</span><div class="footer-tmdb">This product uses the TMDB API but is not endorsed or certified by TMDB. · <a href="https://www.themoviedb.org" target="_blank" rel="noopener noreferrer">TMDB</a></div>';
  if(oldFooter)oldFooter.insertAdjacentElement('afterend',footer);else app.append(footer);

  const originalSearch=document.getElementById('search'),headerSearch=document.getElementById('cinemaHeaderSearch');
  if(originalSearch&&headerSearch){
    headerSearch.value=originalSearch.value||'';
    headerSearch.addEventListener('input',()=>{originalSearch.value=headerSearch.value;originalSearch.dispatchEvent(new Event('input',{bubbles:true}))});
    originalSearch.addEventListener('input',()=>{if(headerSearch.value!==originalSearch.value)headerSearch.value=originalSearch.value});
  }

  const openDrawer=()=>{sidebar.classList.add('open');overlay.classList.add('open');toggle.setAttribute('aria-expanded','true');toggle.textContent='×';toggle.setAttribute('aria-label','メニューを閉じる')};
  const closeDrawer=()=>{sidebar.classList.remove('open');overlay.classList.remove('open');toggle.setAttribute('aria-expanded','false');toggle.textContent='☰';toggle.setAttribute('aria-label','メニューを開く')};
  toggle.addEventListener('click',()=>sidebar.classList.contains('open')?closeDrawer():openDrawer());overlay.addEventListener('click',closeDrawer);document.addEventListener('keydown',e=>{if(e.key==='Escape')closeDrawer()});

  const scrollToTarget=(target)=>{
    if(target==='diagnostics'){location.href='/'+'diagnostics'+'.html';return}
    if(target==='rescan'){document.getElementById('scanButton')?.click();closeDrawer();return}
    const showLibrary=()=>{if(location.hash!=='#/library')location.hash='#/library'};
    if(target==='search'){showLibrary();setTimeout(()=>{const el=document.getElementById('search');el?.scrollIntoView({behavior:'smooth',block:'center'});el?.focus()},180);closeDrawer();return}
    showLibrary();setTimeout(()=>{let el=document.getElementById(target);if(el?.hidden&&target!=='catalog')el=document.getElementById('catalog');el?.scrollIntoView({behavior:'smooth',block:'start'})},180);closeDrawer();
  };
  document.querySelectorAll('[data-cinema-target]').forEach(button=>button.addEventListener('click',()=>scrollToTarget(button.dataset.cinemaTarget)));
  document.getElementById('cinemaHeaderSearchButton')?.addEventListener('click',()=>scrollToTarget('search'));

  const markActive=()=>{const y=window.scrollY+Math.max(90,innerHeight*.18);const ids=['continueSection','nextSection','catalog'];let active='';for(const id of ids){const el=document.getElementById(id);if(el&&!el.hidden&&el.offsetTop<=y)active=id}document.querySelectorAll('.cinema-side-nav [data-cinema-target]').forEach(b=>b.classList.toggle('active',b.dataset.cinemaTarget===active))};
  window.addEventListener('scroll',markActive,{passive:true});window.addEventListener('resize',()=>{if(innerWidth>=1200)closeDrawer()},{passive:true});setTimeout(markActive,300);
})();
</script>
'''
    html = replace_once(html, "</body>", js + "\n</body>", "html body end")

HTML.write_text(html, encoding="utf-8")
