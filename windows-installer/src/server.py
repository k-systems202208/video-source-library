from __future__ import annotations

import argparse,json,os,re,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs,urlsplit
from app_config import configured_video_root,default_config_path
from database import SCHEMA_VERSION,connect,initialize_database,quick_check
from library_service import get_video,get_work,library_stats,list_work_videos,list_works
from scanner import latest_scan_status,mime_type_for_extension,resolve_video_file,scan_library
from user_state import PlaybackSessionStore,continue_watching,current_user,ensure_local_owner,favorite_videos,favorite_works,history,next_up,recent_works,record_progress,set_video_favorite,set_watched,set_work_favorite,start_playback

APP_NAME='VideoLibrary';API_VERSION=1;CHUNK_SIZE=1024*1024;MAX_JSON_BODY=64*1024
class RangeNotSatisfiable(ValueError):pass

def default_database_path()->Path:
    x=os.environ.get('LOCALAPPDATA');return Path(x)/'VideoLibrary'/'library.db' if x else Path.home()/'.video-library'/'library.db'
def default_html_path()->Path:return Path(__file__).with_name('video-library.html')
def _first(q,n):
    v=q.get(n);return v[0] if v else None
def _int_query(q,n):
    v=_first(q,n)
    if v in (None,''):return None
    try:return int(v)
    except ValueError as e:raise ValueError(f'{n} must be an integer') from e

def parse_range_header(header,size):
    if header is None:return None
    if size<=0:raise RangeNotSatisfiable('empty resource')
    t=header.strip()
    if not t.startswith('bytes='):raise RangeNotSatisfiable('unsupported range unit')
    spec=t[6:].strip()
    if not spec or ',' in spec or '-' not in spec:raise RangeNotSatisfiable('invalid byte range')
    a,b=spec.split('-',1)
    try:
        if a=='':
            s=int(b)
            if s<=0:raise RangeNotSatisfiable('invalid suffix range')
            return max(0,size-s),size-1
        start=int(a)
        if start<0 or start>=size:raise RangeNotSatisfiable('range starts beyond resource')
        end=size-1 if b=='' else int(b)
        if end<start:raise RangeNotSatisfiable('range end precedes start')
        return start,min(end,size-1)
    except ValueError as e:
        if isinstance(e,RangeNotSatisfiable):raise
        raise RangeNotSatisfiable('invalid byte range') from e

def make_handler(database_path,html_path,*,video_root=None,local_user_id:int):
    db_path=Path(database_path);ui_path=Path(html_path);root_path=Path(video_root).expanduser() if video_root is not None else None;scan_lock=threading.Lock();sessions=PlaybackSessionStore()
    class H(BaseHTTPRequestHandler):
        server_version='VideoLibrary/0.3'
        def _common(self):self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','same-origin')
        def _json(self,status,payload):
            body=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self._common();self.end_headers();self.wfile.write(body)
        def _error(self,status,code,msg):self._json(status,{'error':{'code':code,'message':msg}})
        def _html(self):
            if not ui_path.exists():self._error(500,'UI_NOT_FOUND','Web UIが見つかりません。');return
            body=ui_path.read_bytes();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(body)));self._common();self.end_headers();self.wfile.write(body)
        def _body(self):
            try:n=int(self.headers.get('Content-Length','0'))
            except ValueError as e:raise ValueError('invalid Content-Length') from e
            if n<0 or n>MAX_JSON_BODY:raise ValueError('request body is too large')
            if n==0:return {}
            try:x=json.loads(self.rfile.read(n).decode())
            except Exception as e:raise ValueError('invalid JSON body') from e
            if not isinstance(x,dict):raise ValueError('JSON body must be an object')
            return x
        def _origin_ok(self):
            o=self.headers.get('Origin')
            if not o:return True
            p=urlsplit(o);return bool(self.headers.get('Host') and p.netloc==self.headers.get('Host') and p.scheme in {'http','https'})
        def _serve_video(self,vid,head=False):
            if root_path is None:self._error(409,'VIDEO_ROOT_NOT_CONFIGURED','動画フォルダーが設定されていません。');return
            with connect(db_path) as c:r=resolve_video_file(c,root_path,vid)
            if r is None:self._error(404,'VIDEO_FILE_NOT_FOUND','動画ファイルが見つかりません。');return
            p,ext=r
            try:size=p.stat().st_size;br=parse_range_header(self.headers.get('Range'),size)
            except RangeNotSatisfiable:self.send_response(416);self.send_header('Content-Range',f'bytes */{p.stat().st_size}');self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length','0');self._common();self.end_headers();return
            except OSError:self._error(404,'VIDEO_FILE_NOT_FOUND','動画ファイルが見つかりません。');return
            status=200 if br is None else 206;start,end=(0,size-1) if br is None else br;length=end-start+1
            self.send_response(status);self.send_header('Content-Type',mime_type_for_extension('.'+ext.lstrip('.')));self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(length))
            if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self._common();self.end_headers()
            if head:return
            try:
                with p.open('rb') as f:
                    f.seek(start);left=length
                    while left>0:
                        b=f.read(min(CHUNK_SIZE,left))
                        if not b:break
                        self.wfile.write(b);left-=len(b)
            except (BrokenPipeError,ConnectionResetError):pass
        def do_GET(self):
            parsed=urlsplit(self.path);path=parsed.path;q=parse_qs(parsed.query,keep_blank_values=True)
            if path in ('/','/index.html'):self._html();return
            m=re.fullmatch(r'/video/(\d+)',path)
            if m:self._serve_video(int(m.group(1)));return
            try:
                with connect(db_path) as c:
                    if path=='/api/health':self._json(200,{'status':'ok','application':APP_NAME,'apiVersion':API_VERSION,'schemaVersion':SCHEMA_VERSION,'database':db_path.name,'quickCheck':quick_check(c),'videoRootConfigured':root_path is not None});return
                    if path=='/api/current-user':
                        u=current_user(c,local_user_id);self._json(200,{'authenticated':u is not None,'user':u});return
                    if path=='/api/stats':self._json(200,library_stats(c));return
                    if path=='/api/scan/status':
                        x=latest_scan_status(c);x['videoRootConfigured']=root_path is not None;self._json(200,x);return
                    if path=='/api/works':self._json(200,list_works(c,user_id=local_user_id,q=_first(q,'q'),category=_first(q,'category'),sort=_first(q,'sort') or 'title',limit=_first(q,'limit'),offset=_first(q,'offset')));return
                    if path=='/api/me/favorite-works':self._json(200,favorite_works(c,local_user_id));return
                    if path=='/api/me/favorite-videos':self._json(200,favorite_videos(c,local_user_id));return
                    if path=='/api/me/continue-watching':self._json(200,continue_watching(c,local_user_id));return
                    if path=='/api/me/next-up':self._json(200,next_up(c,local_user_id));return
                    if path=='/api/me/recent-works':self._json(200,recent_works(c,local_user_id));return
                    if path=='/api/me/history':self._json(200,history(c,local_user_id,limit=_int_query(q,'limit') or 100,offset=_int_query(q,'offset') or 0));return
                    m=re.fullmatch(r'/api/works/(\d+)/videos',path)
                    if m:
                        x=list_work_videos(c,int(m.group(1)),user_id=local_user_id,group_id=_int_query(q,'groupId'));self._json(200,x) if x is not None else self._error(404,'WORK_OR_GROUP_NOT_FOUND','作品またはグループが見つかりません。');return
                    m=re.fullmatch(r'/api/works/(\d+)',path)
                    if m:
                        x=get_work(c,int(m.group(1)),user_id=local_user_id);self._json(200,x) if x is not None else self._error(404,'WORK_NOT_FOUND','作品が見つかりません。');return
                    m=re.fullmatch(r'/api/videos/(\d+)',path)
                    if m:
                        x=get_video(c,int(m.group(1)),user_id=local_user_id);self._json(200,x) if x is not None else self._error(404,'VIDEO_NOT_FOUND','動画が見つかりません。');return
            except ValueError as e:self._error(400,'INVALID_QUERY',str(e));return
            except Exception:self._error(500,'INTERNAL_ERROR','サーバー内部でエラーが発生しました。');return
            self._error(404,'NOT_FOUND','指定されたリソースが見つかりません。')
        def do_HEAD(self):
            m=re.fullmatch(r'/video/(\d+)',urlsplit(self.path).path)
            if m:self._serve_video(int(m.group(1)),head=True);return
            self.send_response(405);self.send_header('Allow','GET, POST, PUT');self.send_header('Content-Length','0');self._common();self.end_headers()
        def do_PUT(self):
            if not self._origin_ok():self._error(403,'ORIGIN_NOT_ALLOWED','このOriginからの状態変更は許可されていません。');return
            path=urlsplit(self.path).path
            try:
                x=self._body()
                with connect(db_path) as c:
                    m=re.fullmatch(r'/api/me/works/(\d+)/favorite',path)
                    if m:
                        if not isinstance(x.get('favorite'),bool):raise ValueError('favorite must be boolean')
                        self._json(200,set_work_favorite(c,local_user_id,int(m.group(1)),x['favorite']));return
                    m=re.fullmatch(r'/api/me/videos/(\d+)/favorite',path)
                    if m:
                        if not isinstance(x.get('favorite'),bool):raise ValueError('favorite must be boolean')
                        self._json(200,set_video_favorite(c,local_user_id,int(m.group(1)),x['favorite']));return
                    m=re.fullmatch(r'/api/me/videos/(\d+)/watched',path)
                    if m:
                        if not isinstance(x.get('watched'),bool):raise ValueError('watched must be boolean')
                        self._json(200,set_watched(c,local_user_id,int(m.group(1)),x['watched']));return
            except LookupError as e:
                code=str(e);self._error(404,code,'作品が見つかりません。' if code=='WORK_NOT_FOUND' else '動画が見つかりません。');return
            except ValueError as e:self._error(400,'INVALID_REQUEST',str(e));return
            except Exception:self._error(500,'INTERNAL_ERROR','状態更新に失敗しました。');return
            self._error(404,'NOT_FOUND','指定されたリソースが見つかりません。')
        def do_POST(self):
            if not self._origin_ok():self._error(403,'ORIGIN_NOT_ALLOWED','このOriginからの状態変更は許可されていません。');return
            path=urlsplit(self.path).path
            if path=='/api/scan':
                if root_path is None:self._error(409,'VIDEO_ROOT_NOT_CONFIGURED','動画フォルダーが設定されていません。');return
                if not scan_lock.acquire(blocking=False):self._error(409,'SCAN_ALREADY_RUNNING','ライブラリスキャンは既に実行中です。');return
                try:
                    with connect(db_path) as c:x=scan_library(c,root_path)
                    self._json(200,x)
                except FileNotFoundError as e:self._error(400,'VIDEO_ROOT_NOT_FOUND',str(e))
                except Exception:self._error(500,'SCAN_FAILED','ライブラリスキャンに失敗しました。')
                finally:scan_lock.release()
                return
            try:
                m=re.fullmatch(r'/api/me/videos/(\d+)/playback/start',path)
                if m:
                    vid=int(m.group(1))
                    with connect(db_path) as c:resume=start_playback(c,local_user_id,vid)
                    sid=sessions.start(local_user_id,vid);self._json(200,{'videoId':vid,'playSessionId':sid,'resume':resume});return
                m=re.fullmatch(r'/api/me/videos/(\d+)/playback/progress',path)
                if m:
                    vid=int(m.group(1));x=self._body();sid=x.get('playSessionId');pos=x.get('positionMs');dur=x.get('durationMs');event=x.get('event','timeupdate')
                    if not isinstance(sid,str) or not sid:raise ValueError('playSessionId is required')
                    if not isinstance(pos,int) or isinstance(pos,bool):raise ValueError('positionMs must be an integer')
                    if dur is not None and (not isinstance(dur,int) or isinstance(dur,bool)):raise ValueError('durationMs must be an integer or null')
                    if event not in {'timeupdate','pause','ended','pagehide','visibilitychange'}:raise ValueError('invalid playback event')
                    inc=sessions.progress(sid,local_user_id,vid,pos,dur)
                    with connect(db_path) as c:s=record_progress(c,local_user_id,vid,position_ms=pos,duration_ms=dur,event=event,increment_play_count=inc)
                    self._json(200,{'videoId':vid,'state':s});return
            except LookupError:self._error(404,'VIDEO_NOT_FOUND','動画が見つかりません。');return
            except ValueError as e:self._error(400,'INVALID_REQUEST',str(e));return
            except Exception:self._error(500,'INTERNAL_ERROR','再生状態の更新に失敗しました。');return
            self._error(404,'NOT_FOUND','指定されたリソースが見つかりません。')
    return H

def create_server(database_path,*,host='127.0.0.1',port=8765,html_path=None,video_root=None,config_path=None):
    db=Path(database_path)
    with connect(db) as c:initialize_database(c);owner=ensure_local_owner(c)
    root=configured_video_root(config_path=config_path,override=video_root);return ThreadingHTTPServer((host,port),make_handler(db,html_path or default_html_path(),video_root=root,local_user_id=int(owner['id'])))
def main():
    p=argparse.ArgumentParser();p.add_argument('--database',type=Path,default=default_database_path());p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8765);p.add_argument('--config',type=Path,default=default_config_path());p.add_argument('--video-root',type=Path);a=p.parse_args();s=create_server(a.database,host=a.host,port=a.port,video_root=a.video_root,config_path=a.config);print(f'Video Library: http://{a.host}:{s.server_port}/')
    try:s.serve_forever()
    except KeyboardInterrupt:pass
    finally:s.server_close()
    return 0
if __name__=='__main__':raise SystemExit(main())
