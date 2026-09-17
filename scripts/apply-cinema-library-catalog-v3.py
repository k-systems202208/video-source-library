from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "windows-installer" / "src" / "video-library.html"
TEST = ROOT / "tests" / "test_cinema_library_catalog_v3_v110.py"
DOC = ROOT / "docs" / "56-1.1.0-cinema-library-catalog-v3.md"

text = HTML.read_text(encoding="utf-8")
if "CINEMA_LIBRARY_CATALOG_V3" in text:
    raise SystemExit("catalog v3 already applied")

old_catalog = '''    <section class="catalog" id="catalog">\n      <div class="toolbar"><input id="search" class="search" type="search" placeholder="作品・俳優・監督を検索..."><select id="sort" class="sort"><option value="title">作品名順</option><option value="year">年順</option><option value="added">登録順</option></select></div>\n      <div class="chips" id="categories"></div><div id="message"></div><div class="grid" id="works"></div>\n      <div class="load" id="loadWrap" hidden><button class="primary" id="loadMore">さらに表示</button></div>\n    </section>'''
new_catalog = '''    <section class="catalog" id="catalog">\n      <div class="catalog-heading">\n        <div class="catalog-title-block"><div class="catalog-kicker">PRIVATE SCREENING CATALOG</div><h2>作品目録 <small>CATALOG</small></h2><p>この蔵書館に収められた作品から、次の一本を。</p></div>\n        <div class="catalog-count"><strong id="catalogCount">— 作品</strong><small>ARCHIVED TITLES</small></div>\n      </div>\n      <div class="toolbar catalog-tools">\n        <label class="catalog-tool search-tool"><span>目録検索 <small>SEARCH</small></span><input id="search" class="search" type="search" placeholder="作品名・俳優・監督を検索..."></label>\n        <label class="catalog-tool sort-tool"><span>並び順 <small>ORDER</small></span><select id="sort" class="sort"><option value="title">作品名順</option><option value="year">年順</option><option value="added">登録順</option></select></label>\n      </div>\n      <div class="category-heading"><span>分類</span><small>GENRE / CATEGORY</small></div>\n      <div class="chips" id="categories"></div><div id="message"></div><div class="grid" id="works"></div>\n      <div class="load" id="loadWrap" hidden><button class="primary" id="loadMore">さらに表示</button></div>\n    </section>'''
if old_catalog not in text:
    raise SystemExit("catalog markup target not found")
text = text.replace(old_catalog, new_catalog, 1)

old_load = "state.total=d.total;for(const w of d.items)works.append(card(w));"
new_load = "state.total=d.total;const catalogCount=$('catalogCount');if(catalogCount)catalogCount.textContent=`${Number(d.total||0).toLocaleString()} 作品`;for(const w of d.items)works.append(card(w));"
if old_load not in text:
    raise SystemExit("loadWorks target not found")
text = text.replace(old_load, new_load, 1)

css = r'''
    /* CINEMA_LIBRARY_CATALOG_V3 */
    .header-actions{gap:14px;align-items:center;padding-left:24px;border-left:1px solid rgba(184,139,62,.25)}
    .header-actions>div{position:relative;min-width:250px;padding-top:12px;text-align:left}
    .header-actions>div::before{content:"ARCHIVE STATUS";position:absolute;top:0;left:0;color:#957044;font:700 7px/1 Georgia,"Times New Roman",serif;letter-spacing:.22em}
    .header-actions .user,.header-actions .stats,.header-actions .scan-status{font-size:10px;line-height:1.45;color:#9d8f7b}
    #scanButton{padding:8px 11px;border-radius:2px;font-size:11px;color:#cdb68f;border-color:#62482f;background:#17110e}
    #scanButton:hover{border-color:#a37b43;color:#f0ddb5}
    .home-strip{position:relative;margin:0 0 28px;padding:16px 17px 14px;border:1px solid #4d3928;border-radius:4px;background:linear-gradient(180deg,rgba(31,23,18,.92),rgba(17,13,11,.96));box-shadow:0 10px 26px rgba(0,0,0,.18)}
    .home-strip::before{content:"";position:absolute;inset:5px;border:1px solid rgba(184,139,62,.08);pointer-events:none}
    .home-strip h2{position:relative;margin:0 0 13px;padding:0 0 9px;border-bottom:1px solid #5d432b;font-size:19px;letter-spacing:.09em}
    .home-strip h2 small{margin-left:2px;font-size:8px;letter-spacing:.24em}
    .home-strip .section-icon{font-size:8px;color:#c79b4b}
    .strip{position:relative;gap:14px;padding-bottom:5px}
    .mini{min-width:330px;max-width:390px;grid-template-columns:92px minmax(0,1fr);border-radius:3px;border-color:#60472f;background:linear-gradient(145deg,#251b15,#15110e);box-shadow:0 6px 18px rgba(0,0,0,.25),inset 0 0 0 1px rgba(211,163,76,.035)}
    .mini::after{content:"NOW IN ARCHIVE";position:absolute;right:10px;bottom:8px;color:#765a37;font:700 6px/1 Georgia,"Times New Roman",serif;letter-spacing:.16em;pointer-events:none}
    #nextSection .mini::after{content:"NEXT PROGRAM"}
    .mini{position:relative}
    .mini-poster,.mini-poster-fallback{width:92px;height:138px;border-right:1px solid #725333;background:#0d0a08}
    .mini-body{padding:13px 14px 20px}
    .mini strong{font-family:"Yu Mincho","Hiragino Mincho ProN",Georgia,serif;font-size:15px;line-height:1.45;color:#f0dfbd;letter-spacing:.025em}
    .mini small{margin-top:5px;color:#9e907d;font-size:10px}
    .mini .progress{margin-top:11px;height:3px;background:#35271d}
    .catalog{margin-top:8px;padding-top:4px}
    .catalog-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin:0 0 17px;padding:0 2px 13px;border-bottom:1px solid #674a2e}
    .catalog-title-block{min-width:0}
    .catalog-kicker{margin-bottom:6px;color:#a67a40;font:700 8px/1 Georgia,"Times New Roman",serif;letter-spacing:.28em}
    .catalog-heading h2{display:flex;align-items:baseline;gap:10px;margin:0;color:#efdfbf;font-family:"Yu Mincho","Hiragino Mincho ProN",Georgia,serif;font-size:24px;letter-spacing:.09em;font-weight:600}
    .catalog-heading h2 small{color:#a77a40;font:700 8px/1 Georgia,"Times New Roman",serif;letter-spacing:.25em}
    .catalog-heading p{margin:6px 0 0;color:#8f8270;font-family:"Yu Mincho","Hiragino Mincho ProN",serif;font-size:11px;letter-spacing:.06em}
    .catalog-count{flex:0 0 auto;min-width:122px;padding:8px 11px 7px;border-left:1px solid #62472e;text-align:right}
    .catalog-count strong{display:block;color:#d7bb84;font:500 16px/1.2 "Yu Mincho","Hiragino Mincho ProN",serif;letter-spacing:.05em}
    .catalog-count small{display:block;margin-top:4px;color:#755a38;font:700 6px/1 Georgia,"Times New Roman",serif;letter-spacing:.17em}
    .catalog-tools{grid-template-columns:minmax(0,1fr) 190px;gap:12px;margin:0 0 13px;padding:14px;border:1px solid #493728;border-radius:3px;background:linear-gradient(180deg,#1d1612,#14100d)}
    .catalog-tool{display:grid;gap:6px;min-width:0}
    .catalog-tool>span{color:#b59c76;font-family:"Yu Mincho","Hiragino Mincho ProN",serif;font-size:10px;letter-spacing:.08em}
    .catalog-tool>span small{margin-left:5px;color:#705637;font:700 6px/1 Georgia,"Times New Roman",serif;letter-spacing:.18em}
    .catalog-tools .search,.catalog-tools .sort{width:100%;border-radius:2px;border-color:#59412b;background:#0f0c0a;color:#eee0c5;padding:10px 12px;outline:none}
    .catalog-tools .search:focus,.catalog-tools .sort:focus{border-color:#b28648;box-shadow:0 0 0 1px rgba(178,134,72,.16)}
    .catalog-tools .search::placeholder{color:#6f6558}
    .category-heading{display:flex;align-items:baseline;gap:8px;margin:0 0 7px;padding-left:2px;color:#b69b72;font-family:"Yu Mincho","Hiragino Mincho ProN",serif;font-size:10px;letter-spacing:.10em}
    .category-heading small{color:#6e5435;font:700 6px/1 Georgia,"Times New Roman",serif;letter-spacing:.18em}
    .chips{gap:6px;padding:0 0 17px}
    .chip{position:relative;border-radius:2px;padding:7px 12px 7px 16px;background:linear-gradient(180deg,#201711,#15100d);border-color:#584029;color:#bfa984;font-family:"Yu Mincho","Hiragino Mincho ProN",serif;font-size:11px}
    .chip::before{content:"";position:absolute;left:7px;top:50%;width:3px;height:3px;border:1px solid #8a6638;transform:translateY(-50%) rotate(45deg)}
    .chip:hover{border-color:#9b713e;color:#f1dcae}
    .chip.active{background:linear-gradient(180deg,#762326,#51171a);border-color:#c49a50;color:#fff0ca;box-shadow:inset 0 0 0 1px rgba(255,222,161,.08)}
    .chip.active::before{background:#d4a95c;border-color:#efd18f}
    .catalog .grid{grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:20px 16px}
    .catalog .card{position:relative;border-radius:3px;border-color:#59412d;background:linear-gradient(155deg,#211812,#14100d);box-shadow:0 9px 22px rgba(0,0,0,.28),inset 0 0 0 1px rgba(211,163,76,.025)}
    .catalog .card:hover,.catalog .card:focus-within{transform:translateY(-4px);border-color:#b18446;box-shadow:0 16px 34px rgba(0,0,0,.42),0 0 0 1px rgba(197,154,74,.10)}
    .catalog .poster{padding:8px;background:linear-gradient(180deg,#16100d,#0c0908);border-bottom-color:#684b2e}
    .catalog .poster img,.catalog .poster-fallback{border:1px solid #7e5a32;box-shadow:0 6px 18px rgba(0,0,0,.52)}
    .catalog .card-body{padding:12px 13px 14px}
    .catalog .card .badge{min-height:14px;color:#b28a4b;font-size:9px;letter-spacing:.07em}
    .catalog .card h2{margin:7px 0 8px;color:#f0dfbf;font-size:16px;line-height:1.42;letter-spacing:.035em}
    .catalog .card .source{color:#7d7264;font-size:9px}
    .catalog .card .meta{margin-top:3px;color:#998b77;font-size:10px}
    .catalog .card-foot{margin-top:11px;padding-top:8px;border-top:1px solid #453326;color:#8c7e6b;font-size:9px}
    .catalog .card-foot .available{color:#a9c99e}
    .catalog .load{margin-top:24px;padding-top:16px;border-top:1px solid #443326}
    .catalog .load .primary{border-radius:2px;padding:9px 18px;background:linear-gradient(180deg,#7c2527,#54181a);border-color:#bf9047;color:#ffeac0}
    #message:not(:empty){margin:0 0 14px}
    @media(max-width:900px){
      .header-actions{padding-left:15px}.header-actions>div{min-width:210px}.catalog .grid{grid-template-columns:repeat(auto-fill,minmax(170px,1fr))}
    }
    @media(max-width:700px){
      .header-actions{width:100%;padding:11px 0 0;border-left:0;border-top:1px solid rgba(184,139,62,.22)}.header-actions>div{min-width:0;flex:1}.catalog-heading{align-items:flex-start}.catalog-count{min-width:105px}.catalog-tools{grid-template-columns:1fr}.catalog .grid{grid-template-columns:1fr 1fr;gap:13px 10px}.home-strip{padding:13px 12px 11px}.mini{min-width:290px;grid-template-columns:82px minmax(0,1fr)}.mini-poster,.mini-poster-fallback{width:82px;height:123px}
    }
    @media(max-width:440px){
      .catalog-heading{display:block}.catalog-count{margin-top:10px;padding:7px 0 0;border-left:0;border-top:1px solid #3f3024;text-align:left}.catalog-count small{display:inline;margin-left:7px}.catalog .grid{grid-template-columns:1fr 1fr}.catalog .card-body{padding:10px}.catalog .card h2{font-size:13px}.catalog .poster{padding:5px}.mini{min-width:268px}.catalog-heading h2{font-size:21px}
    }
'''
marker = "\n  </style>"
if marker not in text:
    raise SystemExit("style end not found")
text = text.replace(marker, css + marker, 1)
HTML.write_text(text, encoding="utf-8")

TEST.write_text('''from __future__ import annotations\n\nfrom pathlib import Path\nimport unittest\n\nROOT = Path(__file__).resolve().parents[1]\nHTML = ROOT / "windows-installer" / "src" / "video-library.html"\n\n\nclass CinemaLibraryCatalogV3Tests(unittest.TestCase):\n    @classmethod\n    def setUpClass(cls) -> None:\n        cls.html = HTML.read_text(encoding="utf-8")\n\n    def test_catalog_v3_marker_and_headings_exist(self) -> None:\n        self.assertIn("CINEMA_LIBRARY_CATALOG_V3", self.html)\n        self.assertIn("PRIVATE SCREENING CATALOG", self.html)\n        self.assertIn("作品目録 <small>CATALOG</small>", self.html)\n        self.assertIn("ARCHIVED TITLES", self.html)\n\n    def test_catalog_search_order_and_category_are_preserved(self) -> None:\n        self.assertIn('id="search"', self.html)\n        self.assertIn('id="sort"', self.html)\n        self.assertIn('id="categories"', self.html)\n        self.assertIn("目録検索 <small>SEARCH</small>", self.html)\n        self.assertIn("並び順 <small>ORDER</small>", self.html)\n        self.assertIn("GENRE / CATEGORY", self.html)\n\n    def test_catalog_count_tracks_filtered_total(self) -> None:\n        self.assertIn('id="catalogCount"', self.html)\n        self.assertIn("catalogCount.textContent=`${Number(d.total||0).toLocaleString()} 作品`", self.html)\n\n    def test_home_sections_and_existing_behaviour_remain(self) -> None:\n        self.assertIn("上映中 <small>NOW SHOWING</small>", self.html)\n        self.assertIn("次回上映 <small>COMING SOON</small>", self.html)\n        self.assertIn("c.onclick=()=>openInWork(x.workId,x.videoId)", self.html)\n        self.assertIn("c.onclick=()=>location.hash=`#/work/${w.id}`", self.html)\n        self.assertIn("const PAGE=60", self.html)\n\n    def test_detail_v2_is_retained(self) -> None:\n        self.assertIn("CINEMA_LIBRARY_DETAIL_V2", self.html)\n        self.assertIn("FEATURE PRESENTATION", self.html)\n        self.assertIn("上映プログラム", self.html)\n        self.assertIn("上映目録", self.html)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''', encoding="utf-8")

DOC.write_text('''# 1.1.0 シネマ蔵書館 第3段階: トップ／作品目録\n\nIssue #125。Run #179で仕上げた作品詳細画面のデザイン言語を、トップ／作品目録へ展開する。\n\n## 変更内容\n- 「上映中 / NOW SHOWING」「次回上映 / COMING SOON」を上映案内カード風に強化\n- 作品目録に `PRIVATE SCREENING CATALOG` / `作品目録 / CATALOG` と検索結果件数を追加\n- 検索・並び替えを目録検索の操作盤として整理\n- カテゴリを券札／館内メニュー風に統一\n- ポスターカードを詳細画面と同じ真鍮・えんじ・アイボリーの階層へ統一\n- ヘッダー右側の管理情報を控えめにし、看板を主役化\n- モバイル2列表示を維持\n\n## 維持するもの\n- 表示バージョン `1.1.0`\n- 検索、カテゴリ、並び替え、60件ページングのロジック\n- 再生、TMDb、人物リンク、お気に入り、DBスキーマ\n- 第2段階の作品詳細デザイン\n\n## テスト\n`tests/test_cinema_library_catalog_v3_v110.py` で、見出し、検索・並び替え・カテゴリ、件数同期、上映中／次回上映、既存詳細画面の維持を確認する。\n''', encoding="utf-8")
