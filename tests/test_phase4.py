from __future__ import annotations
import json,sqlite3,sys,tempfile,threading,unittest
from pathlib import Path
from urllib.request import Request,urlopen
ROOT=Path(__file__).resolve().parents[1];SRC=ROOT/'windows-installer'/'src';sys.path.insert(0,str(SRC))
from database import SCHEMA_VERSION,connect,initialize_database
from server import create_server
from user_state import PlaybackSessionStore,continue_watching,favorite_videos,favorite_works,next_up,record_progress,set_video_favorite,set_watched,set_work_favorite,start_playback

def seed(path):
    with connect(path) as c:
        initialize_database(c);t='2026-09-14T00:00:00+09:00';c.execute("INSERT INTO works(external_work_no,category,official_title,media_file_count,subtitle_file_count,subfolder_count,created_at,updated_at) VALUES(1,'テスト','Phase4 Work',3,0,1,?,?)",(t,t));w=int(c.execute('SELECT last_insert_rowid()').fetchone()[0]);c.execute("INSERT INTO series_groups(work_id,display_name,group_type,sort_order,created_at,updated_at) VALUES(?,'Season 1','SEASON',1,?,?)",(w,t,t));g=int(c.execute('SELECT last_insert_rowid()').fetchone()[0]);ids=[]
        for n,ct,title,key in [(1,'EPISODE','Episode 1','001'),(2,'EPISODE','Episode 2','002'),(3,'EXTRA','Extra','003')]:
            c.execute("INSERT INTO videos(work_id,series_group_id,external_file_no,episode_or_type,episode_sort_key,episode_title,content_type,created_at,updated_at) VALUES(?,?,?,'第'||printf('%02d',?),?,?,?,?,?)",(w,g,n,n,key,title,ct,t,t));v=int(c.execute('SELECT last_insert_rowid()').fetchone()[0]);ids.append(v);c.execute("INSERT INTO video_files(video_id,filename,relative_path,extension,playback_support,is_available,scan_status,created_at,updated_at) VALUES(?,?,?,'mp4','DIRECT',1,'MATCHED',?,?)",(v,f'v{n}.mp4',f'v{n}.mp4',t,t))
        for name in ('Alice','Bob'):c.execute("INSERT INTO users(display_name,is_owner,is_active,created_at,updated_at) VALUES(?,0,1,?,?)",(name,t,t))
        u=c.execute('SELECT id FROM users ORDER BY id').fetchall();c.commit();return {'work':w,'v1':ids[0],'v2':ids[1],'extra':ids[2],'alice':int(u[0][0]),'bob':int(u[1][0])}

class StateTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'l.db';self.i=seed(self.db)
    def tearDown(self):self.tmp.cleanup()
    def test_later_schema_migration_preserves_phase4_state(self):
        self.assertEqual(SCHEMA_VERSION,6)
        legacy=Path(self.tmp.name)/'old.db';r=sqlite3.connect(legacy);r.executescript("CREATE TABLE schema_info(schema_version INTEGER NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);INSERT INTO schema_info VALUES(2,'x','x');CREATE TABLE user_video_state(user_id INTEGER NOT NULL,video_id INTEGER NOT NULL,favorite INTEGER NOT NULL DEFAULT 0,watched INTEGER NOT NULL DEFAULT 0,play_count INTEGER NOT NULL DEFAULT 0,position_ms INTEGER NOT NULL DEFAULT 0,duration_ms INTEGER,last_played_at TEXT,completed_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(user_id,video_id));INSERT INTO user_video_state VALUES(9,8,1,0,3,12345,60000,'t',NULL,'c','u');");r.commit();r.close()
        with connect(legacy) as c:initialize_database(c);x=c.execute('SELECT favorite,play_count,position_ms,watched_override FROM user_video_state').fetchone();self.assertEqual(tuple(x),(1,3,12345,None));self.assertEqual(c.execute('SELECT schema_version FROM schema_info').fetchone()[0],6);self.assertIsNotNone(c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='subtitles'").fetchone())
    def test_favorites_are_independent_and_user_scoped(self):
        with connect(self.db) as c:
            set_work_favorite(c,self.i['alice'],self.i['work'],True);set_video_favorite(c,self.i['alice'],self.i['v1'],True);self.assertEqual(len(favorite_works(c,self.i['alice'])['items']),1);self.assertEqual(len(favorite_videos(c,self.i['alice'])['items']),1);self.assertEqual(favorite_works(c,self.i['bob'])['items'],[]);set_work_favorite(c,self.i['alice'],self.i['work'],False);self.assertEqual(favorite_works(c,self.i['alice'])['items'],[]);self.assertEqual(len(favorite_videos(c,self.i['alice'])['items']),1)
    def test_auto_watched_manual_override_and_continue(self):
        with connect(self.db) as c:
            record_progress(c,self.i['alice'],self.i['v1'],position_ms=1000,duration_ms=300000,event='timeupdate');self.assertEqual(c.execute('SELECT watched FROM user_video_state').fetchone()[0],0);record_progress(c,self.i['alice'],self.i['v1'],position_ms=270000,duration_ms=300000,event='timeupdate');self.assertEqual(c.execute('SELECT watched FROM user_video_state').fetchone()[0],1);set_watched(c,self.i['alice'],self.i['v1'],False);record_progress(c,self.i['alice'],self.i['v1'],position_ms=300000,duration_ms=300000,event='ended');self.assertEqual(c.execute('SELECT watched FROM user_video_state').fetchone()[0],0);start_playback(c,self.i['alice'],self.i['v1']);record_progress(c,self.i['alice'],self.i['v1'],position_ms=60000,duration_ms=600000,event='pause');self.assertEqual(continue_watching(c,self.i['alice'])['items'][0]['videoId'],self.i['v1'])
    def test_next_up_excludes_extra_and_play_count_once(self):
        with connect(self.db) as c:start_playback(c,self.i['alice'],self.i['v1']);record_progress(c,self.i['alice'],self.i['v1'],position_ms=60000,duration_ms=600000,event='pause');self.assertEqual(next_up(c,self.i['alice'])['items'][0]['videoId'],self.i['v2'])
        s=PlaybackSessionStore();sid=s.start(self.i['alice'],self.i['v1']);self.assertTrue(s.progress(sid,self.i['alice'],self.i['v1'],30000,600000));self.assertFalse(s.progress(sid,self.i['alice'],self.i['v1'],60000,600000))

class HttpTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'l.db';self.i=seed(self.db);self.s=create_server(self.db,host='127.0.0.1',port=0);self.th=threading.Thread(target=self.s.serve_forever,daemon=True);self.th.start();self.base=f'http://127.0.0.1:{self.s.server_port}'
    def tearDown(self):self.s.shutdown();self.s.server_close();self.th.join(timeout=2);self.tmp.cleanup()
    def req(self,path,method='GET',body=None):
        data=None;h={}
        if body is not None:data=json.dumps(body).encode();h['Content-Type']='application/json'
        with urlopen(Request(self.base+path,data=data,headers=h,method=method),timeout=10) as r:return json.loads(r.read().decode())
    def test_user_favorite_playback_and_ui(self):
        u=self.req('/api/current-user');self.assertTrue(u['user']['isOwner']);self.req(f"/api/me/works/{self.i['work']}/favorite",'PUT',{'favorite':True});self.assertTrue(self.req(f"/api/works/{self.i['work']}")['favorite']);x=self.req(f"/api/me/videos/{self.i['v1']}/playback/start",'POST');self.req(f"/api/me/videos/{self.i['v1']}/playback/progress",'POST',{'playSessionId':x['playSessionId'],'positionMs':60000,'durationMs':600000,'event':'pause'});self.assertEqual(self.req('/api/me/continue-watching')['items'][0]['videoId'],self.i['v1']);html=urlopen(self.base+'/').read().decode();self.assertIn('上映中',html);self.assertIn('動画お気に入り',html);self.assertIn('/playback/progress',html)
if __name__=='__main__':unittest.main()
