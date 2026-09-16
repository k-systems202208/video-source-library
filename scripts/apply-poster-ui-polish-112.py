from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected text not found in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new), encoding="utf-8")


# Home APIs: include the already-cached TMDb poster URL.
path = "windows-installer/src/user_state.py"
replace(
    path,
    """               w.id AS work_id, w.official_title AS work_title,\n               sg.display_name AS group_name,\n               uvs.position_ms, uvs.duration_ms, uvs.last_played_at\n        FROM user_video_state uvs\n        JOIN videos v ON v.id = uvs.video_id\n        JOIN works w ON w.id = v.work_id\n        LEFT JOIN series_groups sg ON sg.id = v.series_group_id\n""",
    """               w.id AS work_id, w.official_title AS work_title,\n               sg.display_name AS group_name,\n               uvs.position_ms, uvs.duration_ms, uvs.last_played_at,\n               t.match_status AS tmdb_match_status, t.poster_path AS tmdb_poster_path\n        FROM user_video_state uvs\n        JOIN videos v ON v.id = uvs.video_id\n        JOIN works w ON w.id = v.work_id\n        LEFT JOIN series_groups sg ON sg.id = v.series_group_id\n        LEFT JOIN tmdb_work_links t ON t.work_id = w.id\n""",
)
replace(
    path,
    """        items.append({\"videoId\": int(row[\"video_id\"]), \"workId\": int(row[\"work_id\"]), \"workTitle\": row[\"work_title\"], \"groupName\": row[\"group_name\"], \"episodeOrType\": row[\"episode_or_type\"], \"episodeTitle\": row[\"episode_title\"], \"contentType\": row[\"content_type\"], \"positionMs\": position, \"durationMs\": duration, \"percent\": percent, \"lastPlayedAt\": row[\"last_played_at\"]})\n""",
    """        items.append({\"videoId\": int(row[\"video_id\"]), \"workId\": int(row[\"work_id\"]), \"workTitle\": row[\"work_title\"], \"groupName\": row[\"group_name\"], \"episodeOrType\": row[\"episode_or_type\"], \"episodeTitle\": row[\"episode_title\"], \"contentType\": row[\"content_type\"], \"positionMs\": position, \"durationMs\": duration, \"percent\": percent, \"lastPlayedAt\": row[\"last_played_at\"], \"posterUrl\": f'/tmdb-image/poster/{int(row[\"work_id\"])}' if row[\"tmdb_match_status\"] == \"MATCHED\" and row[\"tmdb_poster_path\"] else None})\n""",
)
replace(
    path,
    """            SELECT v.id, v.episode_or_type, v.episode_title,\n                   w.id AS work_id, w.official_title AS work_title,\n                   sg.display_name AS group_name\n            FROM videos v\n            JOIN works w ON w.id = v.work_id\n            LEFT JOIN series_groups sg ON sg.id = v.series_group_id\n""",
    """            SELECT v.id, v.episode_or_type, v.episode_title,\n                   w.id AS work_id, w.official_title AS work_title,\n                   sg.display_name AS group_name,\n                   t.match_status AS tmdb_match_status, t.poster_path AS tmdb_poster_path\n            FROM videos v\n            JOIN works w ON w.id = v.work_id\n            LEFT JOIN series_groups sg ON sg.id = v.series_group_id\n            LEFT JOIN tmdb_work_links t ON t.work_id = w.id\n""",
)
replace(
    path,
    """            result.append({\"videoId\": int(candidate[\"id\"]), \"workId\": int(candidate[\"work_id\"]), \"workTitle\": candidate[\"work_title\"], \"groupName\": candidate[\"group_name\"], \"episodeOrType\": candidate[\"episode_or_type\"], \"episodeTitle\": candidate[\"episode_title\"]})\n""",
    """            result.append({\"videoId\": int(candidate[\"id\"]), \"workId\": int(candidate[\"work_id\"]), \"workTitle\": candidate[\"work_title\"], \"groupName\": candidate[\"group_name\"], \"episodeOrType\": candidate[\"episode_or_type\"], \"episodeTitle\": candidate[\"episode_title\"], \"posterUrl\": f'/tmdb-image/poster/{int(candidate[\"work_id\"])}' if candidate[\"tmdb_match_status\"] == \"MATCHED\" and candidate[\"tmdb_poster_path\"] else None})\n""",
)

# UI: poster-forward home strips, card polish, resilient detail poster fallback.
path = "windows-installer/src/video-library.html"
replace(
    path,
    ".home-strip{margin:0 0 22px}.home-strip h2{font-size:16px;margin:0 0 10px}.strip{display:flex;gap:10px;overflow:auto}.mini{min-width:260px;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:13px;cursor:pointer}.mini strong{display:block}.mini small{color:var(--muted)}.progress{height:5px;background:#303641;border-radius:99px;margin-top:9px;overflow:hidden}.progress>span{display:block;height:100%;background:var(--accent)}",
    ".home-strip{margin:0 0 22px}.home-strip h2{font-size:16px;margin:0 0 10px}.strip{display:flex;gap:12px;overflow:auto;padding:2px 2px 8px}.mini{min-width:300px;max-width:360px;background:var(--panel);border:1px solid var(--line);border-radius:14px;display:grid;grid-template-columns:76px minmax(0,1fr);overflow:hidden;cursor:pointer;transition:transform .16s ease,border-color .16s ease,box-shadow .16s ease}.mini:hover,.mini:focus-within{transform:translateY(-2px);border-color:#5d5138;box-shadow:0 10px 28px rgba(0,0,0,.24)}.mini-poster{width:76px;height:114px;object-fit:cover;display:block;background:linear-gradient(145deg,#29231a,#111318)}.mini-poster-fallback{width:76px;height:114px;display:flex;align-items:center;justify-content:center;background:linear-gradient(145deg,#29231a,#111318);color:var(--accent2);font-size:22px;font-weight:800}.mini-body{min-width:0;padding:12px 13px}.mini strong{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.mini small{color:var(--muted);display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.progress{height:5px;background:#303641;border-radius:99px;margin-top:9px;overflow:hidden}.progress>span{display:block;height:100%;background:var(--accent)}",
)
replace(
    path,
    ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;min-height:150px;display:flex;flex-direction:column;cursor:pointer}.badge,.ep-no{font-size:11px;color:var(--accent2)}.card h2{font-size:18px}",
    ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px}.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;min-height:150px;display:flex;flex-direction:column;cursor:pointer;transition:transform .18s ease,border-color .18s ease,box-shadow .18s ease}.card:hover,.card:focus-within{transform:translateY(-3px);border-color:#5d5138;box-shadow:0 14px 34px rgba(0,0,0,.28)}.badge,.ep-no{font-size:11px;color:var(--accent2)}.card h2{font-size:18px;line-height:1.35;margin:8px 0;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}",
)
replace(
    path,
    ".poster{position:relative;aspect-ratio:2/3;background:linear-gradient(145deg,#29231a,#111318);border-bottom:1px solid var(--line);overflow:hidden}.poster img{width:100%;height:100%;display:block;object-fit:cover}.poster-fallback{height:100%;display:flex;align-items:center;justify-content:center;padding:18px;text-align:center;color:var(--accent2);font-weight:700}.card{padding:0;overflow:hidden}.card-body{padding:14px 16px 16px;display:flex;flex-direction:column;flex:1}",
    ".poster{position:relative;aspect-ratio:2/3;background:linear-gradient(145deg,#29231a,#111318);border-bottom:1px solid var(--line);overflow:hidden}.poster::after{content:\"\";position:absolute;inset:auto 0 0;height:24%;background:linear-gradient(transparent,rgba(0,0,0,.28));pointer-events:none}.poster img{width:100%;height:100%;display:block;object-fit:cover;transition:transform .3s ease}.card:hover .poster img{transform:scale(1.025)}.poster-fallback{height:100%;display:flex;align-items:center;justify-content:center;padding:18px;text-align:center;color:var(--accent2);font-weight:700}.card{padding:0;overflow:hidden}.card-body{padding:14px 16px 16px;display:flex;flex-direction:column;flex:1}",
)
replace(
    path,
    ".hero-poster{width:150px;aspect-ratio:2/3;object-fit:cover;border-radius:10px;border:1px solid var(--line);box-shadow:0 10px 28px rgba(0,0,0,.45)}.hero-body{min-width:0}",
    ".hero-poster{width:150px;aspect-ratio:2/3;object-fit:cover;border-radius:10px;border:1px solid var(--line);box-shadow:0 10px 28px rgba(0,0,0,.45)}.hero-poster-fallback{display:flex;align-items:center;justify-content:center;padding:14px;text-align:center;background:linear-gradient(145deg,#29231a,#111318);color:var(--accent2);font-weight:800}.hero-body{min-width:0}",
)
replace(
    path,
    "@media(max-width:440px){.grid{grid-template-columns:1fr}.mini{min-width:230px}",
    "@media(max-width:440px){.grid{grid-template-columns:1fr}.mini{min-width:270px}",
)
replace(
    path,
    "function renderStrip(secId,stripId,items,progress){const sec=$(secId),strip=$(stripId);strip.replaceChildren();sec.hidden=!items.length;for(const x of items){const c=node('div','mini');c.append(node('strong','',x.workTitle));c.append(node('small','',[x.groupName,x.episodeOrType,x.episodeTitle].filter(Boolean).join(' · ')));if(progress&&x.percent!==null){const p=node('div','progress'),b=node('span');b.style.width=Math.max(0,Math.min(100,x.percent))+'%';p.append(b);c.append(p);c.append(node('small','',`${ft(x.positionMs)} から再開`))}c.onclick=()=>openInWork(x.workId,x.videoId);strip.append(c)}}",
    "function renderStrip(secId,stripId,items,progress){const sec=$(secId),strip=$(stripId);strip.replaceChildren();sec.hidden=!items.length;for(const x of items){const c=node('div','mini'),media=node('div');if(x.posterUrl){const img=document.createElement('img');img.className='mini-poster';img.src=x.posterUrl;img.alt=`${x.workTitle} ポスター`;img.loading='lazy';img.onerror=()=>media.replaceChildren(node('div','mini-poster-fallback',(x.workTitle||'?').trim().slice(0,1)||'?'));media.append(img)}else media.append(node('div','mini-poster-fallback',(x.workTitle||'?').trim().slice(0,1)||'?'));const body=node('div','mini-body');body.append(node('strong','',x.workTitle));body.append(node('small','',[x.groupName,x.episodeOrType,x.episodeTitle].filter(Boolean).join(' · ')));if(progress&&x.percent!==null){const p=node('div','progress'),b=node('span');b.style.width=Math.max(0,Math.min(100,x.percent))+'%';p.append(b);body.append(p);body.append(node('small','',`${ft(x.positionMs)} から再開`))}c.append(media,body);c.onclick=()=>openInWork(x.workId,x.videoId);strip.append(c)}}",
)
replace(
    path,
    "const layout=node('div','hero-layout');if(w.posterUrl){const img=document.createElement('img');img.className='hero-poster';img.src=w.posterUrl;img.alt=`${w.title} ポスター`;img.onerror=()=>img.remove();layout.append(img)}const heroBody=node('div','hero-body')",
    "const layout=node('div','hero-layout'),posterSlot=node('div');if(w.posterUrl){const img=document.createElement('img');img.className='hero-poster';img.src=w.posterUrl;img.alt=`${w.title} ポスター`;img.onerror=()=>posterSlot.replaceChildren(node('div','hero-poster hero-poster-fallback',w.title));posterSlot.append(img)}else posterSlot.append(node('div','hero-poster hero-poster-fallback',w.title));layout.append(posterSlot);const heroBody=node('div','hero-body')",
)

# Functional regression test for home poster URLs + static UI contracts.
Path("tests/test_poster_ui_polish_v110.py").write_text(r'''from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
sys.path.insert(0, str(SRC))

from database import initialize_database, now_iso
from user_state import continue_watching, next_up


class PosterUiPolishV110Tests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        initialize_database(self.connection)
        stamp = now_iso()
        self.connection.execute("INSERT INTO users(id,display_name,is_owner,is_active,created_at,updated_at) VALUES(1,'Owner',1,1,?,?)", (stamp, stamp))
        self.connection.execute("INSERT INTO works(id,external_work_no,category,official_title,media_file_count,created_at,updated_at) VALUES(1,1,'国内ドラマ','Poster Test',2,?,?)", (stamp, stamp))
        self.connection.execute("INSERT INTO videos(id,work_id,external_file_no,episode_or_type,episode_sort_key,episode_title,content_type,created_at,updated_at) VALUES(1,1,1,'第1話','0001','First','EPISODE',?,?)", (stamp, stamp))
        self.connection.execute("INSERT INTO videos(id,work_id,external_file_no,episode_or_type,episode_sort_key,episode_title,content_type,created_at,updated_at) VALUES(2,1,2,'第2話','0002','Second','EPISODE',?,?)", (stamp, stamp))
        self.connection.execute("INSERT INTO video_files(video_id,filename,relative_path,extension,is_available,created_at,updated_at) VALUES(1,'1.mp4','1.mp4','.mp4',1,?,?)", (stamp, stamp))
        self.connection.execute("INSERT INTO video_files(video_id,filename,relative_path,extension,is_available,created_at,updated_at) VALUES(2,'2.mp4','2.mp4','.mp4',1,?,?)", (stamp, stamp))
        self.connection.execute("INSERT INTO user_video_state(user_id,video_id,watched,position_ms,duration_ms,last_played_at,created_at,updated_at) VALUES(1,1,0,60000,120000,?,?,?)", (stamp, stamp, stamp))
        self.connection.execute("INSERT INTO tmdb_work_links(work_id,media_type,tmdb_id,match_status,poster_path,created_at,updated_at) VALUES(1,'tv',123,'MATCHED','/poster.jpg',?,?)", (stamp, stamp))
        self.connection.commit()

    def tearDown(self):
        self.connection.close()

    def test_continue_watching_exposes_local_cached_poster_url(self):
        item = continue_watching(self.connection, 1)["items"][0]
        self.assertEqual(item["posterUrl"], "/tmdb-image/poster/1")

    def test_next_up_exposes_local_cached_poster_url(self):
        item = next_up(self.connection, 1)["items"][0]
        self.assertEqual(item["videoId"], 2)
        self.assertEqual(item["posterUrl"], "/tmdb-image/poster/1")

    def test_ui_has_thumbnail_and_resilient_detail_fallback(self):
        html = (SRC / "video-library.html").read_text(encoding="utf-8")
        self.assertIn("mini-poster", html)
        self.assertIn("mini-poster-fallback", html)
        self.assertIn("hero-poster-fallback", html)
        self.assertIn("img.loading='lazy'", html)
        self.assertIn("card:hover .poster img", html)

    def test_existing_person_links_remain(self):
        html = (SRC / "video-library.html").read_text(encoding="utf-8")
        self.assertIn("#/person/${encodeURIComponent(name)}", html)
        self.assertIn("監督／演出", html)
        self.assertIn("主な出演者／声優", html)


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")

Path("docs/51-1.1.0-poster-ui-polish.md").write_text('''# 1.1.0 ポスター表示仕上げ\n\n## 背景\n\nmatcher v7実機監査で440作品のTMDb照合を完了し、MATCHED 435件は全件ポスターキャッシュ済みとなった。\n\n## 対応\n\n- 作品一覧カードのポスター表示を仕上げ。\n  - hover時の浮き上がりと枠強調\n  - ポスター画像の軽いズーム\n  - 作品名を2行までに収める\n  - 画像取得失敗時は従来どおりタイトルフォールバック\n- 「続きから見る」「次に見る」に作品ポスターを追加。\n  - APIは既存のローカルTMDbキャッシュURLだけを返す\n  - ポスターなし／読込失敗時は作品名先頭文字を表示\n- 作品詳細はポスターなし／読込失敗時にも同じサイズのフォールバックを表示し、レイアウトを維持。\n- 人物リンク、TMDb matcher、動画・字幕・視聴状態には変更を加えない。\n- 表示バージョンは1.1.0を維持。\n\n## テスト\n\n- continue-watching が `posterUrl` を返す\n- next-up が `posterUrl` を返す\n- UIにホーム用サムネイルとフォールバックが存在する\n- 詳細ポスターのフォールバックが存在する\n- 既存の監督／出演者リンクを維持する\n''', encoding="utf-8")

# Remove one-shot patch machinery before the product commit.
Path("scripts/apply-poster-ui-polish-112.py").unlink()
Path(".github/workflows/apply-poster-ui-polish-112.yml").unlink()
