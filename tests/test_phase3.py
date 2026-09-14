from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "windows-installer" / "src"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SRC)); sys.path.insert(0, str(TESTS))
from app_config import configured_video_root, load_config
from database import SCHEMA_VERSION, connect, initialize_database
from metadata_importer import import_file
from sample_metadata import build_metadata
from scanner import latest_scan_status, normalize_relative_path, resolve_video_file, scan_library
from server import create_server, parse_range_header

class Phase3ScannerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); base=Path(self.temp.name); self.db_path=base/'library.db'; self.video_root=base/'videos'; self.video_root.mkdir(); self.metadata_path=base/'fixture.json'; self.payload=build_metadata(work_count=6,video_count=6); self.metadata_path.write_text(json.dumps(self.payload,ensure_ascii=False),encoding='utf-8'); import_file(self.metadata_path,self.db_path)
        for work in self.payload['works'][:5]:
            entry=work['files'][0]; data=f"video-{entry['file_no']:02d}-0123456789".encode('ascii'); relative=normalize_relative_path(entry['relative_path']); path=self.video_root.joinpath(*relative.split('/')); path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(data)
        new_path=self.video_root/'sample'/'new'/'unregistered.mp4'; new_path.parent.mkdir(parents=True,exist_ok=True); new_path.write_bytes(b'new-file')
    def tearDown(self): self.temp.cleanup()
    def test_schema2_migration_table_exists(self):
        with connect(self.db_path) as c:
            initialize_database(c); self.assertEqual(c.execute('SELECT schema_version FROM schema_info').fetchone()[0],2); self.assertEqual(SCHEMA_VERSION,2); self.assertIsNotNone(c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='scan_discoveries'").fetchone())
    def test_scan_matched_missing_and_new(self):
        with connect(self.db_path) as c:
            r=scan_library(c,self.video_root); self.assertEqual((r['filesFound'],r['filesMatched'],r['filesMissing'],r['filesNew'],r['errors']),(6,5,1,1,0)); rows=c.execute("SELECT v.external_file_no,vf.scan_status,vf.is_available FROM videos v JOIN video_files vf ON vf.video_id=v.id ORDER BY v.external_file_no").fetchall(); self.assertEqual([x['scan_status'] for x in rows[:5]],['MATCHED']*5); self.assertEqual(rows[5]['scan_status'],'MISSING'); self.assertEqual(c.execute('SELECT COUNT(*) FROM scan_discoveries').fetchone()[0],1); self.assertEqual(latest_scan_status(c)['latest']['filesMatched'],5)
    def test_scan_does_not_delete_personal_state_for_missing_file(self):
        with connect(self.db_path) as c:
            now='2026-09-14T00:00:00+09:00'; c.execute("INSERT INTO users(display_name,is_owner,is_active,created_at,updated_at) VALUES ('Owner',1,1,?,?)",(now,now)); u=c.execute('SELECT id FROM users').fetchone()[0]; v=c.execute('SELECT id FROM videos WHERE external_file_no=6').fetchone()[0]; c.execute("INSERT INTO user_video_state(user_id,video_id,favorite,watched,play_count,position_ms,created_at,updated_at) VALUES (?,?,1,0,3,4567,?,?)",(u,v,now,now)); c.commit(); scan_library(c,self.video_root); self.assertEqual(tuple(c.execute('SELECT favorite,play_count,position_ms FROM user_video_state WHERE video_id=?',(v,)).fetchone()),(1,3,4567))
    def test_path_traversal_is_rejected(self):
        outside=Path(self.temp.name)/'outside.mp4'; outside.write_bytes(b'secret')
        with connect(self.db_path) as c:
            v=c.execute('SELECT id FROM videos WHERE external_file_no=1').fetchone()[0]; c.execute("UPDATE video_files SET relative_path='../outside.mp4',is_available=1 WHERE video_id=?",(v,)); c.commit(); self.assertIsNone(resolve_video_file(c,self.video_root,v))
    def test_config_video_root(self):
        p=Path(self.temp.name)/'config.json'; p.write_text(json.dumps({'videoRoot':str(self.video_root)}),encoding='utf-8'); self.assertEqual(load_config(p)['videoRoot'],str(self.video_root)); self.assertEqual(configured_video_root(config_path=p),self.video_root)

class RangeParserTests(unittest.TestCase):
    def test_common_ranges(self): self.assertEqual(parse_range_header(None,10),None); self.assertEqual(parse_range_header('bytes=2-5',10),(2,5)); self.assertEqual(parse_range_header('bytes=8-',10),(8,9)); self.assertEqual(parse_range_header('bytes=-3',10),(7,9))

class Phase3HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); base=Path(self.temp.name); self.db_path=base/'library.db'; self.video_root=base/'videos'; self.video_root.mkdir(); p=base/'fixture.json'; payload=build_metadata(work_count=6,video_count=6); p.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8'); import_file(p,self.db_path); first=payload['works'][0]['files'][0]; self.data=b'0123456789abcdef'; rel=normalize_relative_path(first['relative_path']); f=self.video_root.joinpath(*rel.split('/')); f.parent.mkdir(parents=True,exist_ok=True); f.write_bytes(self.data)
        with connect(self.db_path) as c: scan_library(c,self.video_root); self.video_id=int(c.execute('SELECT id FROM videos WHERE external_file_no=1').fetchone()[0])
        self.server=create_server(self.db_path,host='127.0.0.1',port=0,video_root=self.video_root); self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start(); self.base_url=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self): self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2); self.temp.cleanup()
    def test_full_and_range_video_delivery(self):
        with urlopen(f'{self.base_url}/video/{self.video_id}') as r: self.assertEqual(r.status,200); self.assertEqual(r.headers['Accept-Ranges'],'bytes'); self.assertEqual(r.read(),self.data)
        req=Request(f'{self.base_url}/video/{self.video_id}',headers={'Range':'bytes=2-5'})
        with urlopen(req) as r: self.assertEqual(r.status,206); self.assertEqual(r.headers['Content-Range'],f'bytes 2-5/{len(self.data)}'); self.assertEqual(r.read(),b'2345')
    def test_invalid_range_returns_416(self):
        req=Request(f'{self.base_url}/video/{self.video_id}',headers={'Range':'bytes=999-1000'})
        with self.assertRaises(HTTPError) as x:urlopen(req)
        self.assertEqual(x.exception.code,416); self.assertEqual(x.exception.headers['Content-Range'],f'bytes */{len(self.data)}')
    def test_scan_api_and_status_do_not_expose_root_path(self):
        with urlopen(Request(f'{self.base_url}/api/scan',data=b'',method='POST')) as r:self.assertEqual(json.loads(r.read())['status'],'SUCCESS')
        with urlopen(f'{self.base_url}/api/scan/status') as r:text=r.read().decode('utf-8'); data=json.loads(text); self.assertTrue(data['videoRootConfigured']); self.assertNotIn(str(self.video_root),text)
    def test_video_api_does_not_expose_physical_path(self):
        with urlopen(f'{self.base_url}/api/videos/{self.video_id}') as r:text=r.read().decode('utf-8')
        self.assertNotIn('relative_path',text); self.assertNotIn('relativePath',text); self.assertNotIn(str(self.video_root),text)
    def test_ui_contains_player_and_scan_control(self):
        with urlopen(f'{self.base_url}/') as r:html=r.read().decode('utf-8')
        self.assertIn('再スキャン',html); self.assertIn("document.createElement('video')",html)

if __name__=='__main__':unittest.main()
