import os, sqlite3, secrets, hashlib, hmac, re, time, uuid
from pathlib import Path
from contextlib import contextmanager
from fastapi import FastAPI, HTTPException, Header, UploadFile, File, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from cloud_backend import CLOUD_ENABLED, PARTIAL, postgres_conn, upload_object, signed_media_url, remove_objects, private_bucket_ready
import psycopg
import logging
logger=logging.getLogger('brrs')

BASE=Path(__file__).resolve().parent
DATA=Path(os.getenv('BRRS_DATA_DIR',str(BASE/'data')))
UPLOAD=Path(os.getenv('BRRS_UPLOAD_DIR',str(BASE/'uploads')))
DATA.mkdir(parents=True,exist_ok=True); UPLOAD.mkdir(parents=True,exist_ok=True)
DB=DATA/'brrs.db'; MAX_BYTES=int(os.getenv('BRRS_MAX_UPLOAD_MB','25'))*1024*1024
ALLOWED_VOTES={'正確宣判','錯誤宣判','需要更多角度'}
app=FastAPI(title='BRRS V3.0')

@contextmanager
def conn():
 if CLOUD_ENABLED:
  with postgres_conn() as c:
   yield c
  return
 c=sqlite3.connect(DB,timeout=30)
 c.row_factory=sqlite3.Row
 c.execute('PRAGMA foreign_keys=ON')
 try:
  yield c
 except Exception:
  c.rollback()
  raise
 else:
  c.commit()
 finally:
  c.close()

with conn() as c:
 c.executescript('''CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,passhash TEXT NOT NULL,created INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS sessions(tokenhash TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS groups(id TEXT PRIMARY KEY,name TEXT NOT NULL,invite TEXT UNIQUE NOT NULL,owner TEXT NOT NULL,created INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS members(group_id TEXT NOT NULL,user_id TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'member',PRIMARY KEY(group_id,user_id));
 CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY,group_id TEXT NOT NULL,author TEXT NOT NULL,title TEXT NOT NULL,game TEXT,period TEXT,category TEXT,original TEXT,rule TEXT,notes TEXT,video TEXT,source_url TEXT,start REAL NOT NULL DEFAULT 0,"end" REAL NOT NULL DEFAULT 0,created INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS comments(id TEXT PRIMARY KEY,case_id TEXT NOT NULL,author TEXT NOT NULL,body TEXT NOT NULL,created INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS votes(case_id TEXT NOT NULL,user_id TEXT NOT NULL,choice TEXT NOT NULL,PRIMARY KEY(case_id,user_id));''')

def obj(row):return dict(row) if row else None
def fail(code,msg):raise HTTPException(code,msg)
def hash_pw(password,salt=None):
 salt=salt or secrets.token_bytes(16)
 return salt.hex()+':'+hashlib.pbkdf2_hmac('sha256',password.encode(),salt,260000).hex()
def check_pw(password,stored):
 try:
  s,h=stored.split(':');return hmac.compare_digest(hash_pw(password,bytes.fromhex(s)),stored)
 except Exception:return False

def user(authorization: str|None=Header(default=None)):
 if not authorization or not authorization.startswith('Bearer ') or len(authorization)<=7:fail(401,'請先登入')
 digest=hashlib.sha256(authorization[7:].encode()).hexdigest()
 with conn() as c:
  r=c.execute('SELECT users.id,users.name,users.email FROM sessions JOIN users ON users.id=sessions.user_id WHERE tokenhash=? AND expires>?',(digest,int(time.time()))).fetchone()
 if not r:fail(401,'登入已過期，請重新登入')
 return obj(r)

def member(c,gid,uid):
 r=c.execute('SELECT role FROM members WHERE group_id=? AND user_id=?',(gid,uid)).fetchone()
 if not r:fail(403,'你不是此群組成員')
 return r['role']
def get_case(c,cid,uid):
 r=c.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone()
 if not r:fail(404,'找不到判例')
 member(c,r['group_id'],uid)
 return r

class Register(BaseModel):name:str=Field(min_length=1,max_length=60);email:str;password:str=Field(min_length=8,max_length=128)
class Login(BaseModel):email:str;password:str
class GroupIn(BaseModel):name:str=Field(min_length=1,max_length=80)
class InviteIn(BaseModel):code:str
class CaseIn(BaseModel):group_id:str;title:str=Field(min_length=1,max_length=160);game:str='';period:str='';category:str='';original:str='';rule:str='';notes:str='';source_url:str='';start:float=0;end:float=0
class CommentIn(BaseModel):body:str=Field(min_length=1,max_length=2000)
class VoteIn(BaseModel):choice:str=Field(min_length=1,max_length=80)

@app.get('/api/health')
def health():
 try:
  with conn() as c: c.execute('SELECT 1').fetchone()
  storage_ok=private_bucket_ready() if CLOUD_ENABLED else False
  return {'status':'ok','database':'cloud-postgres' if CLOUD_ENABLED else 'local-ephemeral','video_storage':'supabase-private' if storage_ok else 'not-configured','configuration_incomplete':PARTIAL or (CLOUD_ENABLED and not storage_ok)}
 except Exception:fail(503,'資料庫暫時無法使用')

@app.post('/api/register')
def register(p:Register):
 email=p.email.strip().lower()
 if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):fail(400,'Email 格式錯誤')
 with conn() as c:
  try:c.execute('INSERT INTO users VALUES(?,?,?,?,?)',(uuid.uuid4().hex,p.name.strip(),email,hash_pw(p.password),int(time.time())))
  except (sqlite3.IntegrityError,psycopg.IntegrityError):fail(409,'Email 已註冊')
 return {'ok':True}

@app.post('/api/login')
def login(p:Login):
 with conn() as c:
  r=c.execute('SELECT * FROM users WHERE email=?',(p.email.strip().lower(),)).fetchone()
  if not r or not check_pw(p.password,r['passhash']):fail(401,'帳號或密碼錯誤')
  token=secrets.token_urlsafe(40)
  c.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),r['id'],int(time.time())+7*86400))
 return {'token':token,'user':{'id':r['id'],'name':r['name'],'email':r['email']}}

@app.post('/api/logout')
def logout(authorization:str|None=Header(default=None),u=Depends(user)):
 with conn() as c:c.execute('DELETE FROM sessions WHERE tokenhash=?',(hashlib.sha256(authorization[7:].encode()).hexdigest(),))
 return {'ok':True}

@app.get('/api/me')
def me(u=Depends(user)):return u

@app.get('/api/groups')
def groups(u=Depends(user)):
 with conn() as c:return [obj(x) for x in c.execute('SELECT groups.id,groups.name,groups.invite,members.role FROM groups JOIN members ON groups.id=members.group_id WHERE members.user_id=? ORDER BY groups.created DESC',(u['id'],))]

@app.post('/api/groups')
def create_group(p:GroupIn,u=Depends(user)):
 gid=uuid.uuid4().hex;code=secrets.token_urlsafe(9)
 with conn() as c:
  c.execute('INSERT INTO groups VALUES(?,?,?,?,?)',(gid,p.name.strip(),code,u['id'],int(time.time())))
  c.execute('INSERT INTO members VALUES(?,?,?)',(gid,u['id'],'owner'))
 return {'id':gid,'invite':code}

@app.post('/api/groups/join')
def join(p:InviteIn,u=Depends(user)):
 with conn() as c:
  r=c.execute('SELECT id FROM groups WHERE invite=?',(p.code.strip(),)).fetchone()
  if not r:fail(404,'邀請碼不存在')
  c.execute('INSERT OR IGNORE INTO members VALUES(?,?,?)',(r['id'],u['id'],'member'))
 return {'ok':True}

@app.delete('/api/groups/{gid}')
def delete_group(gid:str,u=Depends(user)):
 # Only the group owner can remove the group and all of its cases.
 videos=[]
 with conn() as c:
  g=c.execute('SELECT id,name,owner FROM groups WHERE id=?',(gid,)).fetchone()
  if not g:fail(404,'找不到群組')
  if g['owner']!=u['id']:fail(403,'只有群組建立者可以刪除群組')
  videos=[r['video'] for r in c.execute('SELECT video FROM cases WHERE group_id=? AND video IS NOT NULL',(gid,))]
  c.execute('DELETE FROM votes WHERE case_id IN (SELECT id FROM cases WHERE group_id=?)',(gid,))
  c.execute('DELETE FROM comments WHERE case_id IN (SELECT id FROM cases WHERE group_id=?)',(gid,))
  c.execute('DELETE FROM cases WHERE group_id=?',(gid,))
  c.execute('DELETE FROM members WHERE group_id=?',(gid,))
  c.execute('DELETE FROM groups WHERE id=?',(gid,))
 # Remove uploaded video files only after database changes are committed.
 if CLOUD_ENABLED:
  try:remove_objects(videos)
  except Exception:logger.exception('Failed to clean group videos from cloud storage')
 else:
  for name in videos:(UPLOAD/name).unlink(missing_ok=True)
 return {'ok':True,'deleted_cases':len(videos)}


@app.delete('/api/cases/{cid}')
def delete_case(cid:str,u=Depends(user)):
 with conn() as c:
  r=get_case(c,cid,u['id'])
  if r['author']!=u['id'] and member(c,r['group_id'],u['id'])!='owner':
   fail(403,'只有判例建立者或群組建立者可以刪除判例')
  video=r['video']
  c.execute('DELETE FROM votes WHERE case_id=?',(cid,))
  c.execute('DELETE FROM comments WHERE case_id=?',(cid,))
  c.execute('DELETE FROM cases WHERE id=?',(cid,))
 if video:
  if CLOUD_ENABLED:
   try:remove_objects([video])
   except Exception:logger.exception('Failed to remove case video from cloud storage')
  else:(UPLOAD/video).unlink(missing_ok=True)
 return {'ok':True}


@app.get('/api/cases')
def cases(group_id:str,u=Depends(user)):
 with conn() as c:
  member(c,group_id,u['id'])
  return [obj(x) for x in c.execute('SELECT cases.*,users.name AS author_name FROM cases JOIN users ON users.id=cases.author WHERE group_id=? ORDER BY created DESC',(group_id,))]

@app.post('/api/cases')
def create_case(p:CaseIn,u=Depends(user)):
 if p.start<0 or p.end<0 or (p.end and p.end<p.start):fail(400,'影片時間不正確')
 if p.source_url and not p.source_url.startswith(('https://','http://')):fail(400,'影片連結需為 HTTP(S)')
 with conn() as c:
  member(c,p.group_id,u['id']);cid=uuid.uuid4().hex
  c.execute('INSERT INTO cases VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(cid,p.group_id,u['id'],p.title.strip(),p.game,p.period,p.category,p.original,p.rule,p.notes,None,p.source_url,p.start,p.end,int(time.time())))
 return {'id':cid}

@app.post('/api/cases/{cid}/video')
async def upload_video(cid:str,file:UploadFile=File(...),u=Depends(user)):
 ext=Path(file.filename or '').suffix.lower()
 if ext not in {'.mp4','.webm','.mov','.m4v'}:fail(400,'僅支援 MP4、WebM、MOV、M4V')
 if file.content_type and not (file.content_type.startswith('video/') or file.content_type=='application/octet-stream'):fail(400,'請上傳影片檔案')
 with conn() as c:
  existing=get_case(c,cid,u['id'])
  if existing['author']!=u['id'] and member(c,existing['group_id'],u['id'])!='owner':fail(403,'只有上傳者或群組管理員可替換影片')
 name=uuid.uuid4().hex+ext;target=UPLOAD/name;total=0
 try:
  with target.open('wb') as out:
   while chunk:=await file.read(1024*1024):
    total+=len(chunk)
    if total>MAX_BYTES:fail(413,'影片超過上傳限制')
    out.write(chunk)
  if not total:fail(400,'影片內容為空')
  if CLOUD_ENABLED:
   upload_object(name,target,{'mp4':'video/mp4','webm':'video/webm','mov':'video/quicktime','m4v':'video/x-m4v'}[ext[1:]])
  with conn() as c:
   r=get_case(c,cid,u['id'])
   if r['author']!=u['id'] and member(c,r['group_id'],u['id'])!='owner':fail(403,'只有上傳者或群組管理員可替換影片')
   old=r['video'];c.execute('UPDATE cases SET video=? WHERE id=?',(name,cid))
  if old:
   if CLOUD_ENABLED:
    try:remove_objects([old])
    except Exception:logger.exception('Failed to remove replaced cloud video')
   else:(UPLOAD/old).unlink(missing_ok=True)
 except Exception:
  if CLOUD_ENABLED:
   try:remove_objects([name])
   except Exception:logger.exception('Cloud upload rollback failed')
  target.unlink(missing_ok=True)
  raise
 finally:
  if CLOUD_ENABLED:target.unlink(missing_ok=True)
 return {'ok':True,'size':total}

@app.get('/api/cases/{cid}/video')
def get_video(cid:str,token:str=''):
 # HTML video tags cannot attach Authorization headers; use short-lived signed URL below instead.
 fail(403,'請透過授權播放連結觀看')

@app.get('/api/cases/{cid}/play')
def play(cid:str,u=Depends(user)):
 with conn() as c:
  r=get_case(c,cid,u['id'])
  if not r['video']:fail(404,'尚未上傳影片')
  if CLOUD_ENABLED:
   try:return {'url':signed_media_url(r['video'],600)}
   except Exception:
    logger.exception('Cloud signed video URL failed')
    fail(503,'雲端影片暫時無法播放')
  exp=int(time.time())+600
  sig=hmac.new(secret_key(),f'{cid}:{r["video"]}:{exp}'.encode(),hashlib.sha256).hexdigest()
 return {'url':f'/api/media/{cid}?exp={exp}&sig={sig}'}

def secret_key():
 path=DATA/'media.key'
 if not path.exists():
  try:
   with path.open('xb') as f:f.write(secrets.token_bytes(32))
  except FileExistsError:pass
 return path.read_bytes()

@app.get('/api/media/{cid}')
def media(cid:str,exp:int,sig:str):
 if exp<int(time.time()):fail(403,'播放連結已過期')
 with conn() as c:
  r=c.execute('SELECT video FROM cases WHERE id=?',(cid,)).fetchone()
 if not r or not r['video']:fail(404,'影片不存在')
 expected=hmac.new(secret_key(),f'{cid}:{r["video"]}:{exp}'.encode(),hashlib.sha256).hexdigest()
 if not hmac.compare_digest(expected,sig):fail(403,'無效的播放連結')
 target=UPLOAD/r['video']
 if not target.exists():fail(404,'影片檔案不存在')
 return FileResponse(target,media_type={'mp4':'video/mp4','webm':'video/webm','mov':'video/quicktime','m4v':'video/x-m4v'}.get(target.suffix.lstrip('.'),'application/octet-stream'))

@app.get('/api/cases/{cid}/discussion')
def discussion(cid:str,u=Depends(user)):
 with conn() as c:
  get_case(c,cid,u['id'])
  comments=[obj(x) for x in c.execute('SELECT comments.*,users.name AS author_name FROM comments JOIN users ON users.id=comments.author WHERE case_id=? ORDER BY created',(cid,))]
  votes=[obj(x) for x in c.execute('SELECT choice,COUNT(*) AS count FROM votes WHERE case_id=? GROUP BY choice',(cid,))]
  mine=c.execute('SELECT choice FROM votes WHERE case_id=? AND user_id=?',(cid,u['id'])).fetchone()
 return {'comments':comments,'votes':votes,'my_vote':mine['choice'] if mine else None}

@app.post('/api/cases/{cid}/comments')
def add_comment(cid:str,p:CommentIn,u=Depends(user)):
 with conn() as c:
  get_case(c,cid,u['id']);c.execute('INSERT INTO comments VALUES(?,?,?,?,?)',(uuid.uuid4().hex,cid,u['id'],p.body.strip(),int(time.time())))
 return {'ok':True}

@app.post('/api/cases/{cid}/votes')
def vote(cid:str,p:VoteIn,u=Depends(user)):
 if p.choice not in ALLOWED_VOTES:fail(422,'請選擇有效投票選項')
 with conn() as c:
  get_case(c,cid,u['id'])
  try:
   c.execute('INSERT INTO votes VALUES(?,?,?)',(cid,u['id'],p.choice))
  except (sqlite3.IntegrityError,psycopg.IntegrityError):
   fail(409,'此帳號已對這個判例投票，不能重複投票或更改選項')
 return {'ok':True}

app.mount('/static',StaticFiles(directory=BASE/'static'),name='static')
@app.get('/')
def index():return FileResponse(BASE/'static'/'index.html')