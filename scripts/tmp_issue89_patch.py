from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"marker not found in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


Path("windows-installer/src/app_version.py").write_text('APP_VERSION = "1.1.0"\n', encoding="utf-8")
replace_once(
    "windows-installer/installer/VideoLibrary.iss",
    '#define MyAppVersion "1.0.0"',
    '#define MyAppVersion "1.1.0"',
)

html_path = Path("windows-installer/src/video-library.html")
html = html_path.read_text(encoding="utf-8")

css_marker = "    .detail[hidden],.catalog[hidden],.home-strip[hidden]{display:none}"
css_insert = (
    "    .credits{margin-top:18px;padding-top:16px;border-top:1px solid var(--line);display:grid;gap:12px}"
    ".credit-row{display:grid;grid-template-columns:140px minmax(0,1fr);gap:12px;align-items:start}"
    ".credit-label{font-size:12px;color:var(--muted);padding-top:7px}"
    ".credit-people{display:flex;gap:7px;flex-wrap:wrap}"
    ".person-link{border:1px solid var(--line);border-radius:999px;padding:6px 10px;background:var(--panel2);color:var(--accent2);cursor:pointer}"
    ".person-link:hover,.person-link:focus-visible{border-color:var(--accent);outline:none}"
    ".person-filter{margin-bottom:12px;text-align:left}.person-filter strong{color:var(--accent2)}\n"
)
if css_marker not in html:
    raise SystemExit("credits CSS marker not found")
html = html.replace(css_marker, css_insert + css_marker, 1)

state_old = "const PAGE=60,state={offset:0,total:0,q:'',category:'',sort:'title',loading:false},$=id=>document.getElementById(id),works=$('works'),loadWrap=$('loadWrap');"
state_new = "const PAGE=60,state={offset:0,total:0,q:'',category:'',sort:'title',person:'',loading:false},$=id=>document.getElementById(id),works=$('works'),loadWrap=$('loadWrap');"
if state_old not in html:
    raise SystemExit("state marker not found")
html = html.replace(state_old, state_new, 1)

helper_marker = "function techValue(v,fallback='未取得'){return v===null||v===undefined||v===''?fallback:String(v)}\n"
helpers = r"""function splitCreditPeople(value){const raw=String(value||'').trim();if(!raw)return[];const items=raw.split(/\s*(?:、|,|，|;|；|\||\r?\n|\s+\/\s+)\s*/u).map(x=>x.trim()).filter(Boolean);return[...new Set(items)]}
function creditRow(label,value){const names=splitCreditPeople(value);if(!names.length)return null;const row=node('div','credit-row'),people=node('div','credit-people');row.append(node('strong','credit-label',label));for(const name of names){const b=node('button','person-link',name);b.type='button';b.title=`${name} の登録作品を表示`;b.onclick=()=>{location.hash=`#/person/${encodeURIComponent(name)}`};people.append(b)}row.append(people);return row}
async function showPersonWorks(name){const person=String(name||'').trim();if(!person){location.hash='#/library';return}state.person=person;state.q=person;state.category='';$('search').value=person;$('detail').hidden=true;$('catalog').hidden=false;$('continueSection').hidden=true;$('nextSection').hidden=true;document.querySelectorAll('.chip').forEach(x=>x.classList.toggle('active',(x.dataset.category||'')===''));const msg=node('div','notice person-filter');msg.append('人物「',node('strong','',person),'」が関わる登録作品');$('message').replaceChildren(msg);await loadWorks(true)}
"""
if helper_marker not in html:
    raise SystemExit("helper marker not found")
html = html.replace(helper_marker, helper_marker + helpers, 1)

hero_marker = "h.append(line);r.append(h);if(w.groups.length)"
hero_replacement = "h.append(line);const credits=node('div','credits'),director=creditRow('監督／演出',w.director),cast=creditRow('主な出演者／声優',w.cast);if(director)credits.append(director);if(cast)credits.append(cast);if(credits.childElementCount)h.append(credits);r.append(h);if(w.groups.length)"
if hero_marker not in html:
    raise SystemExit("hero marker not found")
html = html.replace(hero_marker, hero_replacement, 1)

route_old = r"function route(){const m=location.hash.match(/^#\/work\/(\d+)$/);if(m){showWork(+m[1]);return}$('detail').hidden=true;$('catalog').hidden=false;loadHome();if(!works.children.length)loadWorks(true)}"
route_new = r"function route(){const p=location.hash.match(/^#\/person\/(.+)$/);if(p){let name=p[1];try{name=decodeURIComponent(name)}catch{}showPersonWorks(name);return}const m=location.hash.match(/^#\/work\/(\d+)$/);if(m){showWork(+m[1]);return}if(state.person){state.person='';state.q='';$('search').value=''}$('message').replaceChildren();$('detail').hidden=true;$('catalog').hidden=false;loadHome();if(!works.children.length)loadWorks(true)}"
if route_old not in html:
    raise SystemExit("route marker not found")
html = html.replace(route_old, route_new, 1)

search_old = "state.q=e.target.value.trim();loadWorks(true)"
search_new = "state.person='';$('message').replaceChildren();state.q=e.target.value.trim();loadWorks(true)"
if search_old not in html:
    raise SystemExit("search handler marker not found")
html = html.replace(search_old, search_new, 1)

category_old = "state.category=b.dataset.category||'';document.querySelectorAll('.chip')"
category_new = "state.person='';$('message').replaceChildren();state.category=b.dataset.category||'';document.querySelectorAll('.chip')"
if category_old not in html:
    raise SystemExit("category handler marker not found")
html = html.replace(category_old, category_new, 1)

back_old = "$('back').onclick=()=>location.hash='#/library'"
back_new = "$('back').onclick=()=>location.hash=state.person?`#/person/${encodeURIComponent(state.person)}`:'#/library'"
if back_old not in html:
    raise SystemExit("back handler marker not found")
html = html.replace(back_old, back_new, 1)
html_path.write_text(html, encoding="utf-8")

Path("tests/test_release_v100.py").write_text(
    '''from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReleaseV100Tests(unittest.TestCase):
    def test_v100_acceptance_docs_are_preserved(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        notes = (ROOT / "docs" / "39-1.0.0-release.md").read_text(encoding="utf-8")
        self.assertIn("### 1.0.0: 正式版", readme)
        self.assertIn("実動画4,845件", readme)
        self.assertIn("applicationNoRoute = 0", readme)
        self.assertIn("元データ異常24件", readme)
        self.assertIn("DIRECT: 1,826件", notes)
        self.assertIn("TRANSCODE: 3,019件", notes)
        self.assertIn("repairCandidateCount = 0", notes)


if __name__ == "__main__":
    unittest.main()
''',
    encoding="utf-8",
)

Path("tests/test_credits_people_ui_v110.py").write_text(
    '''from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from app_version import APP_VERSION
from library_service import _work_filters


class CreditsPeopleUiV110Tests(unittest.TestCase):
    def test_version_and_installer_are_1_1_0(self):
        self.assertEqual(APP_VERSION, "1.1.0")
        installer = (ROOT / "windows-installer" / "installer" / "VideoLibrary.iss").read_text(encoding="utf-8")
        self.assertIn('#define MyAppVersion "1.1.0"', installer)

    def test_work_search_already_includes_director_and_cast(self):
        sql, params = _work_filters("テスト出演者", None)
        self.assertIn("director_or_direction", sql)
        self.assertIn("main_cast_or_voice_actors", sql)
        self.assertEqual(len(params), 4)
        self.assertTrue(all(value == "%テスト出演者%" for value in params))

    def test_ui_displays_credits_and_person_route(self):
        html = (SRC / "video-library.html").read_text(encoding="utf-8")
        self.assertIn("監督／演出", html)
        self.assertIn("主な出演者／声優", html)
        self.assertIn("splitCreditPeople", html)
        self.assertIn("creditRow", html)
        self.assertIn("#/person/${encodeURIComponent(name)}", html)
        self.assertIn("/^#\\/person\\/(.+)$/", html)
        self.assertIn("人物「", html)

    def test_credit_split_does_not_split_foreign_name_middle_dot(self):
        html = (SRC / "video-library.html").read_text(encoding="utf-8")
        splitter = html[html.index("function splitCreditPeople"):html.index("function creditRow")]
        self.assertNotIn("|・", splitter)


if __name__ == "__main__":
    unittest.main()
''',
    encoding="utf-8",
)

Path("docs/40-1.1.0-credits-person-links.md").write_text(
    '''# 1.1.0 既存クレジット表示と人物クリック作品検索

## 目的
TMDb連携より先に、すでに監査済みメタデータからSQLiteへ保存している `director_or_direction` と `main_cast_or_voice_actors` をWeb UIで活用する。

## 実装
- 作品詳細に `監督／演出` と `主な出演者／声優` を表示する。
- クレジット文字列を読取専用で人物チップへ展開する。
- 区切りは読点・カンマ・セミコロン・縦棒・改行・空白で囲まれた `/` に限定する。外国人名で一般的な中黒 `・` は分割しない。
- 人物チップを押すと `#/person/<URL encoded name>` へ遷移する。
- 人物作品一覧は既存の `GET /api/works?q=...` を再利用する。この検索は作品名だけでなく `director_or_direction` / `main_cast_or_voice_actors` も対象としている。
- 人物検索中は「人物『…』が関わる登録作品」と表示する。
- 人物一覧から作品を開いた場合、「← 作品一覧」で元の人物検索へ戻る。

## 安全性
- この段階ではTMDbや外部サイトへ通信しない。
- SQLiteスキーマは変更しない。
- 元動画・字幕・メタデータ・利用者状態は変更しない。
- クレジットが空の作品は該当行を表示しない。

## 今後
次段階でTMDb作品ID・人物ID・poster/backdropのローカルキャッシュを追加し、人物IDを使った同姓同名分離へ移行する。
''',
    encoding="utf-8",
)

readme = Path("README.md")
text = readme.read_text(encoding="utf-8")
marker = '対象動画拡張子: `.mkv`, `.mp4`, `.avi`, `.webm`, `.mpg`, `.flv`, `.m4v`, `.mov`, `.wmv`\n'
section = '''### 1.1.0: クレジット表示と人物別作品検索（第1段階）
- 既存メタデータの `監督／演出`、`主な出演者／声優` を作品詳細に表示
- 人物名をクリックすると、その人物が関わる登録作品一覧を表示
- 人物別一覧は既存の作品検索APIを再利用し、この段階では外部通信を追加しない
- 外国人名の中黒 `・` を人物区切りとして扱わず、クレジット文字列を安全側で分割
- TMDb連携、人物ID、ポスター／背景画像、レトロ映画館UIは次段階で追加

'''
if marker not in text:
    raise SystemExit("README version marker not found")
text = text.replace(marker, section + marker, 1)
doc_marker = '- [0.9.2 実ライブラリ全件再生監査](docs/33-0.9.2-playback-audit.md)\n'
if doc_marker in text:
    text = text.replace(
        doc_marker,
        doc_marker + '- [1.1.0 既存クレジット表示と人物クリック作品検索](docs/40-1.1.0-credits-person-links.md)\n',
        1,
    )
readme.write_text(text, encoding="utf-8")
