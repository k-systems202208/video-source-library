from pathlib import Path
import re

path = Path('windows-installer/src/video-library.html')
text = path.read_text(encoding='utf-8')

if 'CINEMA_LIBRARY_FINAL_POLISH' in text:
    raise SystemExit('final polish already applied')

css = r'''
    /* CINEMA_LIBRARY_FINAL_POLISH */
    .header-actions{opacity:.72;transition:opacity .18s ease}
    .header-actions:hover,.header-actions:focus-within{opacity:.96}
    .header-actions>div::before{color:#765936;font-size:6px}
    .header-actions .user,.header-actions .stats,.header-actions .scan-status{font-size:9px;line-height:1.5;color:#817666}
    #scanButton{padding:7px 10px;font-size:10px;color:#a9977a;border-color:#503b29;background:#14100d}
    #scanButton:hover,#scanButton:focus-visible{color:#ead7ae;border-color:#917044;background:#1b140f}
    .strip-shell{position:relative}
    .strip{scroll-behavior:smooth;scrollbar-width:thin;scrollbar-color:#65492f #17110e}
    .strip::-webkit-scrollbar{height:7px}.strip::-webkit-scrollbar-track{background:#17110e}.strip::-webkit-scrollbar-thumb{background:#65492f;border-radius:10px;border:1px solid #2d2118}
    .strip-scroll-hint{position:absolute;z-index:5;right:0;top:0;bottom:7px;width:68px;padding:0 10px 0 24px;border:0;border-radius:0;background:linear-gradient(90deg,transparent 0%,rgba(17,13,11,.72) 42%,rgba(17,13,11,.97) 76%);color:#dbb76f;cursor:pointer;display:flex;align-items:center;justify-content:flex-end;transition:opacity .15s ease,color .15s ease}
    .strip-scroll-hint[hidden]{display:none}
    .strip-scroll-hint span{display:grid;place-items:center;width:29px;height:44px;border:1px solid #765630;background:rgba(31,23,18,.88);font:400 30px/1 Georgia,"Times New Roman",serif;box-shadow:0 5px 14px rgba(0,0,0,.32)}
    .strip-scroll-hint:hover,.strip-scroll-hint:focus-visible{color:#fff0c8}.strip-scroll-hint:hover span,.strip-scroll-hint:focus-visible span{border-color:#c4984e;background:#2b1d13}
    .cinema-poster-fallback{position:relative;display:flex!important;flex-direction:column;align-items:center;justify-content:center;gap:8px;width:100%;height:100%;padding:18px;background:radial-gradient(circle at 50% 34%,rgba(126,86,39,.20),transparent 38%),repeating-linear-gradient(135deg,rgba(255,255,255,.012) 0 1px,transparent 1px 6px),linear-gradient(180deg,#17110e,#090706)!important;color:#d9bf8b!important;font-family:"Yu Mincho","Hiragino Mincho ProN",Georgia,serif;text-align:center;overflow:hidden}
    .cinema-poster-fallback::before{content:"";position:absolute;inset:7px;border:1px solid rgba(184,139,62,.34);pointer-events:none}
    .poster-fallback-mark{position:relative;z-index:1;display:grid;place-items:center;width:34px;height:34px;border:1px solid #9b723d;border-radius:50%;color:#c99b4c;font-size:14px;box-shadow:inset 0 0 0 4px rgba(184,139,62,.05)}
    .poster-fallback-title{position:relative;z-index:1;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;max-width:100%;color:#ead8b5;font-size:12px;line-height:1.45;letter-spacing:.04em}
    .poster-fallback-label{position:relative;z-index:1;color:#705638;font:700 5px/1.35 Georgia,"Times New Roman",serif;letter-spacing:.18em}
    .mini-poster-fallback.cinema-poster-fallback{width:92px;height:138px;padding:8px;gap:5px;border-right:1px solid #725333}
    .mini-poster-fallback .poster-fallback-mark{width:25px;height:25px;font-size:10px}
    .mini-poster-fallback .poster-fallback-title{-webkit-line-clamp:3;font-size:8px;line-height:1.35;letter-spacing:.02em}
    .mini-poster-fallback .poster-fallback-label{font-size:4px;letter-spacing:.10em}
    button:focus-visible,.card:focus-visible,.mini:focus-visible,.search:focus-visible,.sort:focus-visible{outline:1px solid #d4aa5c!important;outline-offset:2px}
    .card:focus-visible,.mini:focus-visible{border-color:#bd8f48;box-shadow:0 0 0 1px rgba(212,170,92,.10),0 14px 34px rgba(0,0,0,.34)}
    @media(max-width:700px){
      .header-actions{opacity:.86}.strip-scroll-hint{width:48px;padding-left:15px}.strip-scroll-hint span{width:24px;height:38px;font-size:24px}.mini-poster-fallback.cinema-poster-fallback{width:82px;height:123px}.poster-fallback-label{letter-spacing:.10em}
    }
    @media(max-width:440px){.strip-scroll-hint{width:42px;padding-right:6px}.strip-scroll-hint span{width:22px;height:34px;font-size:21px}}
'''
text = text.replace('\n\n  </style>', '\n\n' + css + '\n  </style>', 1)

old_continue = '<section id="continueSection" class="home-strip" hidden><h2><span class="section-icon" aria-hidden="true">●</span> 上映中 <small>NOW SHOWING</small></h2><div id="continueStrip" class="strip"></div></section>'
new_continue = '<section id="continueSection" class="home-strip" hidden><h2><span class="section-icon" aria-hidden="true">●</span> 上映中 <small>NOW SHOWING</small></h2><div class="strip-shell"><div id="continueStrip" class="strip"></div><button class="strip-scroll-hint" type="button" data-strip-target="continueStrip" aria-label="上映中の次の作品を表示"><span aria-hidden="true">›</span></button></div></section>'
old_next = '<section id="nextSection" class="home-strip" hidden><h2><span class="section-icon" aria-hidden="true">◆</span> 次回上映 <small>COMING SOON</small></h2><div id="nextStrip" class="strip"></div></section>'
new_next = '<section id="nextSection" class="home-strip" hidden><h2><span class="section-icon" aria-hidden="true">◆</span> 次回上映 <small>COMING SOON</small></h2><div class="strip-shell"><div id="nextStrip" class="strip"></div><button class="strip-scroll-hint" type="button" data-strip-target="nextStrip" aria-label="次回上映の次の作品を表示"><span aria-hidden="true">›</span></button></div></section>'
for old, new in ((old_continue,new_continue),(old_next,new_next)):
    if text.count(old) != 1:
        raise SystemExit('home strip markup target not found exactly once')
    text = text.replace(old,new,1)

node_line = "function node(t,c,x){const e=document.createElement(t);if(c)e.className=c;if(x!==undefined)e.textContent=x;return e}"
helpers = node_line + "\n" + r'''function posterFallback(title,compact=false){const f=node('div',compact?'mini-poster-fallback cinema-poster-fallback':'poster-fallback cinema-poster-fallback');f.append(node('span','poster-fallback-mark','◉'),node('strong','poster-fallback-title',String(title||'作品')),node('small','poster-fallback-label','POSTER NOT AVAILABLE'));return f}
function makeOpenable(c,open){c.tabIndex=0;c.setAttribute('role','button');c.onclick=open;c.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open()}}}
function updateStripHint(sec,strip){const hint=sec.querySelector('.strip-scroll-hint');if(!hint)return;const overflow=strip.scrollWidth>strip.clientWidth+4,atEnd=strip.scrollLeft+strip.clientWidth>=strip.scrollWidth-4;hint.hidden=!overflow||atEnd}
function setupStripNavigation(sec,strip){const hint=sec.querySelector('.strip-scroll-hint');if(strip.dataset.navReady!=='1'){strip.dataset.navReady='1';strip.addEventListener('scroll',()=>updateStripHint(sec,strip),{passive:true});strip.addEventListener('wheel',e=>{if(!window.matchMedia('(pointer:fine)').matches)return;if(Math.abs(e.deltaY)<=Math.abs(e.deltaX))return;const max=strip.scrollWidth-strip.clientWidth;if(max<=4)return;const forward=e.deltaY>0&&strip.scrollLeft<max-2,backward=e.deltaY<0&&strip.scrollLeft>2;if(!forward&&!backward)return;e.preventDefault();strip.scrollBy({left:e.deltaY,behavior:'smooth'})},{passive:false});window.addEventListener('resize',()=>updateStripHint(sec,strip),{passive:true});if(hint)hint.onclick=()=>strip.scrollBy({left:Math.max(260,strip.clientWidth*.72),behavior:'smooth'})}requestAnimationFrame(()=>updateStripHint(sec,strip))}'''
if text.count(node_line) != 1:
    raise SystemExit('node helper target not found')
text = text.replace(node_line,helpers,1)

pattern = re.compile(r"function renderStrip\(secId,stripId,items,progress\)\{.*?\}\nasync function loadScan", re.S)
replacement = r'''function renderStrip(secId,stripId,items,progress){const sec=$(secId),strip=$(stripId);strip.replaceChildren();sec.hidden=!items.length;for(const x of items){const c=node('div','mini'),media=node('div');if(x.posterUrl){const img=document.createElement('img');img.className='mini-poster';img.src=x.posterUrl;img.alt=`${x.workTitle} ポスター`;img.loading='lazy';img.onerror=()=>media.replaceChildren(posterFallback(x.workTitle,true));media.append(img)}else media.append(posterFallback(x.workTitle,true));const body=node('div','mini-body');body.append(node('strong','',x.workTitle));body.append(node('small','',[x.groupName,x.episodeOrType,x.episodeTitle].filter(Boolean).join(' · ')));if(progress&&x.percent!==null){const p=node('div','progress'),b=node('span');b.style.width=Math.max(0,Math.min(100,x.percent))+'%';p.append(b);body.append(p);body.append(node('small','',`${ft(x.positionMs)} から再開`))}c.append(media,body);makeOpenable(c,()=>openInWork(x.workId,x.videoId));strip.append(c)}setupStripNavigation(sec,strip)}
async function loadScan'''
text, n = pattern.subn(replacement,text,count=1)
if n != 1:
    raise SystemExit('renderStrip target not found')

old_card = "function card(w){const c=node('article','card'),poster=node('div','poster');if(w.posterUrl){const img=document.createElement('img');img.src=w.posterUrl;img.alt=`${w.title} ポスター`;img.loading='lazy';img.onerror=()=>{poster.replaceChildren(node('div','poster-fallback',w.title))};poster.append(img)}else poster.append(node('div','poster-fallback',w.title));c.append(poster);const body=node('div','card-body');body.append(node('div','badge',w.category+(w.favorite?' · ★ お気に入り':'')));body.append(node('h2','',w.title));body.append(node('div','source',w.sourceTitle&&w.sourceTitle!==w.title?w.sourceTitle:''));if(w.progress.total)body.append(node('div','meta',`視聴 ${w.progress.watched}/${w.progress.total} (${w.progress.percent}%)`));const f=node('div','card-foot');f.append(node('span','',w.yearOrPeriod||'年不明'));f.append(node('span',w.availableVideoCount?'available':'',w.availableVideoCount?`${w.availableVideoCount}/${w.videoCount} 利用可`:`${w.videoCount}動画`));body.append(f);c.append(body);c.onclick=()=>location.hash=`#/work/${w.id}`;return c}"
new_card = "function card(w){const c=node('article','card'),poster=node('div','poster');if(w.posterUrl){const img=document.createElement('img');img.src=w.posterUrl;img.alt=`${w.title} ポスター`;img.loading='lazy';img.onerror=()=>{poster.replaceChildren(posterFallback(w.title))};poster.append(img)}else poster.append(posterFallback(w.title));c.append(poster);const body=node('div','card-body');body.append(node('div','badge',w.category+(w.favorite?' · ★ お気に入り':'')));body.append(node('h2','',w.title));body.append(node('div','source',w.sourceTitle&&w.sourceTitle!==w.title?w.sourceTitle:''));if(w.progress.total)body.append(node('div','meta',`視聴 ${w.progress.watched}/${w.progress.total} (${w.progress.percent}%)`));const f=node('div','card-foot');f.append(node('span','',w.yearOrPeriod||'年不明'));f.append(node('span',w.availableVideoCount?'available':'',w.availableVideoCount?`${w.availableVideoCount}/${w.videoCount} 利用可`:`${w.videoCount}動画`));body.append(f);c.append(body);makeOpenable(c,()=>{location.hash=`#/work/${w.id}`});return c}"
if text.count(old_card) != 1:
    raise SystemExit('card target not found exactly once')
text = text.replace(old_card,new_card,1)

path.write_text(text,encoding='utf-8')
