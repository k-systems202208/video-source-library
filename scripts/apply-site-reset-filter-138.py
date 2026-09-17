from pathlib import Path

root = Path(__file__).resolve().parents[1]
html_path = root / "windows-installer" / "src" / "video-library.html"
html = html_path.read_text(encoding="utf-8")

replacements = [
    (
        '<div class="cinema-nav-brand"><span aria-hidden="true">◉</span><strong>シネマ蔵書館</strong><small>PRIVATE CINEMA ARCHIVE</small></div>',
        '<button class="cinema-nav-brand cinema-home-reset" id="cinemaNavBrandReset" type="button" aria-label="シネマ蔵書館を初期状態で再読み込み"><span aria-hidden="true">◉</span><strong>シネマ蔵書館</strong><small>PRIVATE CINEMA ARCHIVE</small></button>',
    ),
    (
        '<div class="brand"><div class="brand-kicker">PRIVATE CINEMA ARCHIVE</div><h1><span class="brand-mark" aria-hidden="true">◉</span> シネマ蔵書館</h1><p>映画で、また会える。</p></div>',
        '<button class="brand cinema-home-reset" id="headerBrandReset" type="button" aria-label="シネマ蔵書館を初期状態で再読み込み"><div class="brand-kicker">PRIVATE CINEMA ARCHIVE</div><h1><span class="brand-mark" aria-hidden="true">◉</span> シネマ蔵書館</h1><p>映画で、また会える。</p></button>',
    ),
    (
        '    .cinema-nav-art{position:absolute;left:0;right:0;bottom:0;height:42%;background:url(\'/cinema-sidebar.svg\') center bottom/cover no-repeat;opacity:.82;pointer-events:none;mask-image:linear-gradient(transparent,#000 25%)}',
        '    .cinema-nav-art{position:absolute;left:0;right:0;bottom:0;height:42%;background:url(\'/cinema-sidebar.svg\') center bottom/cover no-repeat;opacity:.82;pointer-events:none;mask-image:linear-gradient(transparent,#000 25%)}\n    .cinema-home-reset{appearance:none;background:transparent;border:0;color:inherit;cursor:pointer}.brand.cinema-home-reset{text-align:left;padding:0}.cinema-nav-brand.cinema-home-reset{width:100%;border-bottom:1px solid rgba(193,147,75,.5)}.cinema-home-reset:focus-visible{outline:1px solid #c39243;outline-offset:3px}.cinema-home-reset:hover h1,.cinema-home-reset:hover strong{color:#fff3d4}',
    ),
    (
        "document.querySelectorAll('.cinema-nav-item[data-route]').forEach(b=>b.onclick=()=>{const next=b.dataset.route;if(location.hash===next)route();else location.hash=next;setCinemaNav(false)});",
        "document.querySelectorAll('.cinema-nav-item[data-route]').forEach(b=>b.onclick=()=>{const next=b.dataset.route;if(location.hash===next)route();else location.hash=next;setCinemaNav(false)});\nfunction resetCinemaHome(){history.replaceState(null,'',location.pathname+location.search);location.reload()}\n$('cinemaNavBrandReset').onclick=resetCinemaHome;$('headerBrandReset').onclick=resetCinemaHome;",
    ),
    (
        "async function showPeopleDirectory(role){const isDirector=role==='directors';state.person='';",
        "function clearPersonSearchFilter(){if(!state.person)return false;state.person='';state.q='';$('search').value='';$('headerSearch').value='';return true}\nasync function showPeopleDirectory(role){const isDirector=role==='directors';clearPersonSearchFilter();",
    ),
    (
        "async function showLibraryRoute(target='catalog'){if(state.person){state.person='';state.q='';$('search').value='';$('headerSearch').value=''}$('message').replaceChildren();$('detail').hidden=true;$('peopleDirectory').hidden=true;$('catalog').hidden=false;await loadHome();if(!works.children.length)await loadWorks(true);updateCinemaNavActive();",
        "async function showLibraryRoute(target='catalog'){clearPersonSearchFilter();$('message').replaceChildren();$('detail').hidden=true;$('peopleDirectory').hidden=true;$('catalog').hidden=false;await loadHome();await loadWorks(true);updateCinemaNavActive();",
    ),
]

for old, new in replacements:
    count = html.count(old)
    if count != 1:
        raise SystemExit(f"Expected exactly one match, found {count}: {old[:100]}")
    html = html.replace(old, new, 1)

html_path.write_text(html, encoding="utf-8")

test_path = root / "tests" / "test_home_reset_person_filter_v110.py"
test_path.write_text(r'''from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "windows-installer" / "src" / "video-library.html").read_text(encoding="utf-8")


class HomeResetPersonFilterTests(unittest.TestCase):
    def test_both_cinema_brand_names_are_reset_buttons(self):
        self.assertIn('id="cinemaNavBrandReset"', HTML)
        self.assertIn('id="headerBrandReset"', HTML)
        self.assertIn("history.replaceState(null,'',location.pathname+location.search);location.reload()", HTML)
        self.assertIn("$('cinemaNavBrandReset').onclick=resetCinemaHome", HTML)
        self.assertIn("$('headerBrandReset').onclick=resetCinemaHome", HTML)

    def test_person_filter_is_cleared_before_returning_to_library(self):
        self.assertIn('function clearPersonSearchFilter()', HTML)
        self.assertIn("state.person='';state.q='';$('search').value='';$('headerSearch').value=''", HTML)
        self.assertIn("async function showLibraryRoute(target='catalog'){clearPersonSearchFilter();", HTML)
        self.assertIn("await loadHome();await loadWorks(true);updateCinemaNavActive();", HTML)
        self.assertNotIn("if(!works.children.length)await loadWorks(true)", HTML)

    def test_people_directory_also_releases_previous_person_filter(self):
        self.assertIn("async function showPeopleDirectory(role){const isDirector=role==='directors';clearPersonSearchFilter();", HTML)


if __name__ == '__main__':
    unittest.main()
''', encoding="utf-8")

doc_path = root / "docs" / "60-1.1.0-home-reset-person-filter.md"
doc_path.write_text('''# 1.1.0 サイト名初期化と人物フィルター解除\n\n## 対応内容\n\n- 左サイドバーとヘッダーの「シネマ蔵書館」をボタン化し、クリック時にURLハッシュを除去してからページを再読み込みする。\n- これにより作品詳細や人物名鑑など、どの画面からでも初期状態へ戻れる。\n- 人物別作品フィルターを解除する共通処理を追加。\n- 上映中・次回上映・作品目録へ戻る際は作品一覧を必ず再取得し、検索欄だけ空で古い人物フィルター結果が残る状態を防止する。\n- 人物名鑑へ移動する際も直前の人物検索状態を解除する。\n\n## 維持する仕様\n\n- 表示バージョン 1.1.0\n- PC / タブレット / スマートフォンのレスポンシブUI\n- 通常検索、カテゴリ、並び順、再生、TMDb、人物リンク、お気に入り\n''', encoding="utf-8")
