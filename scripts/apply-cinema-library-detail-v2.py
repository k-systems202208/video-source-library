from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
html_path = ROOT / "windows-installer" / "src" / "video-library.html"
text = html_path.read_text(encoding="utf-8")

marker = "/* CINEMA_LIBRARY_DETAIL_V2 */"
if marker in text:
    raise SystemExit("detail v2 marker already exists")

old_title_block = "const heroBody=node('div','hero-body'),line=node('div','hero-line'),title=node('div');title.append(node('div','badge',w.category),node('h2','',w.title),node('div','meta',`視聴 ${w.progress.watched}/${w.progress.total} · 検出字幕 ${w.availableSubtitleCount??0}`));line.append(title);const a=node('div','hero-actions'),fav=node('button','action'+(w.favorite?' on':''),w.favorite?'★ お気に入り':'☆ お気に入り');fav.onclick=async()=>{w.favorite=!w.favorite;await api(`/api/me/works/${w.id}/favorite`,jo('PUT',{favorite:w.favorite}));fav.textContent=w.favorite?'★ お気に入り':'☆ お気に入り';fav.classList.toggle('on',w.favorite)};a.append(fav);line.append(a);heroBody.append(line);"
new_title_block = "const heroBody=node('div','hero-body'),line=node('div','hero-line'),title=node('div','hero-title-block');title.append(node('div','hero-kicker','FEATURE PRESENTATION'),node('div','badge',w.category),node('h2','',w.title),node('div','meta hero-meta',`視聴 ${w.progress.watched}/${w.progress.total} · 検出字幕 ${w.availableSubtitleCount??0}`));const a=node('div','hero-actions'),fav=node('button','action favorite-action'+(w.favorite?' on':''),w.favorite?'★ お気に入り':'☆ お気に入り');fav.onclick=async()=>{w.favorite=!w.favorite;await api(`/api/me/works/${w.id}/favorite`,jo('PUT',{favorite:w.favorite}));fav.textContent=w.favorite?'★ お気に入り':'☆ お気に入り';fav.classList.toggle('on',w.favorite)};a.append(fav);title.append(a);line.append(title);heroBody.append(line);"
if old_title_block not in text:
    raise SystemExit("hero title block not found")
text = text.replace(old_title_block, new_title_block, 1)

old_groups = "if(w.groups.length){const g=node('div','groups');w.groups.forEach((x,i)=>{const b=node('button','group'+(i===0?' active':''),`${x.name} (${x.watchedCount}/${x.videoCount})`);b.onclick=()=>{document.querySelectorAll('.group').forEach(q=>q.classList.toggle('active',q===b));loadEpisodes(w.id,x.id)};g.append(b)});r.append(g);const ep=node('div','episodes');ep.id='episodes';r.append(ep);const vd=node('div');vd.id='videoDetail';r.append(vd)}"
new_groups = "if(w.groups.length){const program=node('section','program-section'),programHead=node('div','section-heading');programHead.append(node('span','section-heading-jp','上映プログラム'),node('small','section-heading-en','PROGRAM'));const g=node('div','groups');w.groups.forEach((x,i)=>{const b=node('button','group'+(i===0?' active':''),`${x.name} (${x.watchedCount}/${x.videoCount})`);b.onclick=()=>{document.querySelectorAll('.group').forEach(q=>q.classList.toggle('active',q===b));loadEpisodes(w.id,x.id)};g.append(b)});program.append(programHead,g);r.append(program);const listing=node('section','screening-list'),listHead=node('div','section-heading');listHead.append(node('span','section-heading-jp','上映目録'),node('small','section-heading-en','SCREENING LIST'));const ep=node('div','episodes');ep.id='episodes';listing.append(listHead,ep);r.append(listing);const vd=node('div');vd.id='videoDetail';r.append(vd)}"
if old_groups not in text:
    raise SystemExit("groups block not found")
text = text.replace(old_groups, new_groups, 1)

old_episode_title = "main.append(node('div','',v.episodeTitle||'タイトル未設定'));"
new_episode_title = "main.append(node('div','episode-title',v.episodeTitle||'タイトル未設定'));"
if old_episode_title not in text:
    raise SystemExit("episode title block not found")
text = text.replace(old_episode_title, new_episode_title, 1)

css = r'''
    /* CINEMA_LIBRARY_DETAIL_V2 */
    .detail #back{
      margin:0 0 14px;padding:8px 14px;border-color:#745533;background:linear-gradient(180deg,#211812,#15100d);
      color:#e8d6b2;font-family:"Yu Mincho","Hiragino Mincho ProN",Georgia,serif;letter-spacing:.06em
    }
    .detail #back:hover{border-color:#c49a52;color:#fff1cf;background:#251912}
    .hero{
      padding:30px 32px 32px;border-color:#735431;background:#17110d;
      box-shadow:0 18px 54px rgba(0,0,0,.40),inset 0 0 0 1px rgba(215,171,91,.05)
    }
    .hero::after{content:"";position:absolute;left:18px;right:18px;bottom:8px;height:1px;background:linear-gradient(90deg,transparent,#8a6335,transparent);opacity:.65}
    .hero.has-backdrop::before{background:linear-gradient(90deg,rgba(13,10,8,.98) 0%,rgba(13,10,8,.92) 28%,rgba(13,10,8,.72) 66%,rgba(13,10,8,.84) 100%)}
    .hero-layout{grid-template-columns:205px minmax(0,1fr);gap:36px;align-items:start}
    .hero-poster{width:205px;border-radius:2px;border:2px solid #b88941;box-shadow:0 16px 38px rgba(0,0,0,.62),0 0 0 6px rgba(31,22,16,.88),0 0 0 7px #5a4024}
    .hero-poster-fallback{width:205px;min-height:307px;border-radius:2px}
    .hero-body{padding-top:3px}
    .hero-line{display:block}
    .hero-title-block{max-width:880px}
    .hero-kicker{margin-bottom:12px;color:#c59a4a;font:700 9px/1.2 Georgia,"Times New Roman",serif;letter-spacing:.28em}
    .hero-title-block>.badge{display:inline-block;margin-bottom:9px;color:#d7ab5c;font-size:11px;letter-spacing:.10em}
    .hero-body h2{margin:0 0 10px;font-size:clamp(32px,3.5vw,48px);line-height:1.12;letter-spacing:.055em;text-shadow:0 2px 5px #000}
    .hero-meta{font-size:12px;color:#b9aa92;letter-spacing:.03em}
    .hero-actions{margin-top:16px}
    .favorite-action{padding:8px 13px;border-radius:3px!important;background:linear-gradient(180deg,rgba(37,27,20,.94),rgba(21,16,12,.96))!important;border-color:#8b6738!important;color:#ead4a5!important;font-size:12px;letter-spacing:.04em;box-shadow:none}
    .favorite-action.on{background:linear-gradient(180deg,#762125,#501519)!important;border-color:#c49a52!important;color:#fff1cc!important}
    .overview{max-width:920px;margin:22px 0 0;padding:18px 0 4px;border-top:1px solid rgba(167,121,62,.42);font-size:15px;line-height:1.9;color:#e2d8c7}
    .credits{max-width:920px;margin-top:18px;padding-top:16px;border-top:1px solid rgba(167,121,62,.38);gap:11px}
    .credit-row{grid-template-columns:128px minmax(0,1fr);gap:16px}
    .credit-label{padding-top:6px;color:#c6ad82;font-size:11px;letter-spacing:.08em}
    .credit-people{gap:7px 8px}
    .person-link{padding:6px 12px;border-radius:3px;background:linear-gradient(180deg,rgba(43,31,22,.9),rgba(24,18,14,.94));border-color:#705333;color:#efd497;font-family:"Yu Mincho","Hiragino Mincho ProN",serif;font-size:12px;letter-spacing:.03em;box-shadow:inset 0 0 0 1px rgba(204,159,78,.04)}
    .person-link:hover,.person-link:focus-visible{background:#342419;border-color:#c59a4a;color:#fff0c9}
    .program-section,.screening-list{margin-top:24px}
    .section-heading{display:flex;align-items:baseline;gap:10px;margin:0 0 11px;padding:0 2px 8px;border-bottom:1px solid #64492e}
    .section-heading::after{content:"";height:1px;flex:1;background:linear-gradient(90deg,#8a6539,transparent)}
    .section-heading-jp{color:#ead9b7;font-family:"Yu Mincho","Hiragino Mincho ProN",Georgia,serif;font-size:17px;letter-spacing:.10em}
    .section-heading-en{color:#aa8044;font:700 8px/1 Georgia,"Times New Roman",serif;letter-spacing:.22em}
    .groups{margin:0;gap:7px}
    .group{position:relative;padding:9px 14px 9px 18px;border-radius:2px;background:linear-gradient(180deg,#211811,#15100d);border-color:#64482d;color:#d9c5a0;font-family:"Yu Mincho","Hiragino Mincho ProN",serif;font-size:12px;letter-spacing:.025em}
    .group::before{content:"";position:absolute;left:7px;top:50%;width:4px;height:4px;border:1px solid #a77a3d;transform:translateY(-50%) rotate(45deg)}
    .group:hover{border-color:#b88945;color:#fff0c8;background:#291c13}
    .group.active{background:linear-gradient(180deg,#7c2527,#531719);border-color:#c59a4a;color:#fff0cc;box-shadow:inset 0 0 0 1px rgba(255,221,159,.09),0 5px 14px rgba(0,0,0,.20)}
    .group.active::before{background:#d4a95c;border-color:#f1d99a}
    .screening-list{margin-top:19px}
    .episodes{gap:7px}
    .episode{grid-template-columns:72px minmax(0,1fr) 120px;gap:17px;padding:14px 17px;border-radius:3px;border-color:#4d3928;background:linear-gradient(180deg,rgba(30,23,18,.96),rgba(20,16,13,.98));transition:border-color .15s ease,background .15s ease,transform .15s ease}
    .episode:hover{border-color:#8e683a;background:linear-gradient(180deg,#261b14,#18120e);transform:translateX(2px)}
    .ep-no{align-self:stretch;display:flex;align-items:center;padding-right:13px;border-right:1px solid #61482e;color:#d2a34f;font-family:"Yu Mincho","Hiragino Mincho ProN",serif;font-size:10px;letter-spacing:.05em}
    .episode-title{color:#f0e2c7;font-family:"Yu Mincho","Hiragino Mincho ProN",Georgia,serif;font-size:16px;line-height:1.4;letter-spacing:.03em}
    .episode-main small{margin-top:5px;color:#8f8374;font-size:10px;letter-spacing:.025em}
    .episode-state{justify-content:flex-end;align-items:center;color:#d7c5a6;font-size:11px;white-space:nowrap}
    .episode-state.watched{color:#9ac89b}
    header{padding:16px 20px 18px;background:radial-gradient(circle at 11% 20%,rgba(133,37,38,.13),transparent 20rem),linear-gradient(180deg,#271c16,#17110e)}
    .brand-kicker{font-size:9px;letter-spacing:.30em}
    .brand h1{font-size:33px;letter-spacing:.075em}
    .brand-mark{width:27px;height:27px;border:1px solid #b88b3e;border-radius:50%;font-size:13px;vertical-align:middle;box-shadow:inset 0 0 0 3px rgba(184,139,62,.08)}
    .brand p{margin-top:7px;font-size:11px;letter-spacing:.16em;color:#d0b98f}
    @media(max-width:900px){
      .hero-layout{grid-template-columns:170px minmax(0,1fr);gap:28px}.hero-poster{width:170px}.hero-poster-fallback{width:170px;min-height:255px}.hero-body h2{font-size:36px}
    }
    @media(max-width:700px){
      .hero{padding:22px 18px 24px}.hero-layout{grid-template-columns:112px minmax(0,1fr);gap:20px}.hero-poster{width:112px;box-shadow:0 10px 24px rgba(0,0,0,.55),0 0 0 4px rgba(31,22,16,.88),0 0 0 5px #5a4024}.hero-poster-fallback{width:112px;min-height:168px}.hero-kicker{font-size:7px;margin-bottom:8px}.hero-body h2{font-size:28px}.overview{grid-column:1/-1;font-size:13px;line-height:1.75}.credits{grid-column:1/-1}.credit-row{grid-template-columns:1fr;gap:5px}.credit-label{padding-top:0}.episode{grid-template-columns:58px minmax(0,1fr);gap:11px;padding:12px}.episode-state{grid-column:2;justify-content:flex-start}.ep-no{padding-right:9px}.episode-title{font-size:14px}.section-heading-jp{font-size:15px}.brand h1{font-size:27px}
    }
    @media(max-width:440px){
      .hero-layout{grid-template-columns:90px minmax(0,1fr);gap:16px}.hero-poster{width:90px}.hero-poster-fallback{width:90px;min-height:135px}.hero-body h2{font-size:23px}.hero-actions{margin-top:11px}.favorite-action{padding:6px 9px;font-size:11px}.program-section,.screening-list{margin-top:20px}
    }
'''
if "  </style>" not in text:
    raise SystemExit("style closing tag not found")
text = text.replace("  </style>", css + "\n  </style>", 1)
html_path.write_text(text, encoding="utf-8")

# Regression tests for the second-stage visual hierarchy.
test_path = ROOT / "tests" / "test_cinema_library_detail_v2_v110.py"
test_path.write_text(r'''from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "windows-installer" / "src" / "video-library.html"


class CinemaLibraryDetailV2V110Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML.read_text(encoding="utf-8")

    def test_detail_v2_marker_and_mockup_hierarchy_exist(self):
        self.assertIn("CINEMA_LIBRARY_DETAIL_V2", self.html)
        self.assertIn("FEATURE PRESENTATION", self.html)
        self.assertIn("上映プログラム", self.html)
        self.assertIn("PROGRAM", self.html)
        self.assertIn("上映目録", self.html)
        self.assertIn("SCREENING LIST", self.html)

    def test_poster_title_and_episode_visual_classes_exist(self):
        self.assertIn("grid-template-columns:205px minmax(0,1fr)", self.html)
        self.assertIn("hero-title-block", self.html)
        self.assertIn("favorite-action", self.html)
        self.assertIn("episode-title", self.html)
        self.assertIn("program-section", self.html)
        self.assertIn("screening-list", self.html)

    def test_existing_behavior_hooks_are_preserved(self):
        self.assertIn("/favorite`,jo('PUT'", self.html)
        self.assertIn("#/person/${encodeURIComponent(name)}", self.html)
        self.assertIn("loadEpisodes(w.id,x.id)", self.html)
        self.assertIn("r.onclick=()=>showVideo(v.id)", self.html)
        self.assertIn("/playback/progress", self.html)

    def test_existing_image_and_detail_ids_are_preserved(self):
        for value in ("workDetail", "episodes", "videoDetail", "playerModal", "back"):
            self.assertIn(value, self.html)
        self.assertIn("w.backdropUrl", self.html)
        self.assertIn("w.posterUrl", self.html)

    def test_display_version_remains_1_1_0(self):
        version = (ROOT / "windows-installer" / "src" / "app_version.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "1.1.0"', version)


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")

doc_path = ROOT / "docs" / "55-1.1.0-cinema-library-detail-v2.md"
doc_path.write_text('''# 1.1.0 シネマ蔵書館 詳細画面 第2段階\n\n## 目的\nRun #177 のベースデザインを、採用したモックアップAのクラシック映画館・映画パンフレット風の階層へさらに近づける。\n\n## 変更内容\n- 詳細ポスターをデスクトップ約205pxへ拡大し、真鍮色の額縁を強化\n- タイトルに `FEATURE PRESENTATION` の小見出しを追加し、作品名を主役化\n- お気に入りを右端の大きな枠からタイトル情報内の小型ボタンへ移動\n- 監督・出演者リンクを丸型チップから銘板風へ変更\n- シリーズ切替を「上映プログラム / PROGRAM」として整理\n- 各話一覧を「上映目録 / SCREENING LIST」として整理\n- 各話タイトルを強調し、解像度・Codec・時間などの技術情報を控えめに表示\n- ヘッダーの看板感を強化\n- 700px / 440px 以下のレスポンシブ調整を追加\n\n## 変更しないもの\n- 再生ロジック\n- TMDb照合・画像取得\n- 人物リンクの遷移\n- お気に入り保存処理\n- DBスキーマ\n- 表示バージョン `1.1.0`\n\n## テスト\n- 第2段階の視覚階層とCSSマーカー\n- ポスター・背景・人物リンク・お気に入り・再生フックの維持\n- 既存のベースデザイン／ポスターUI／人物リンク回帰テスト\n''', encoding="utf-8")
