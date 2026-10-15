#!/usr/bin/env python3
"""Dependency-free inventory app backed by SQLite."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import base64, json, os, sqlite3, uuid

ROOT=Path(__file__).resolve().parent
DATA=Path(os.environ.get('DATA_DIR','/data')); DATA.mkdir(parents=True,exist_ok=True)
DB=DATA/'relevamiento.db'; USER=os.environ.get('APP_USER',''); PASSWORD=os.environ.get('APP_PASSWORD','')
ROW_COLORS={'none','orange','yellow','green','blue','red','purple'}
def connect():
    db=sqlite3.connect(DB,timeout=30); db.row_factory=sqlite3.Row; return db
def initialize():
    with connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE IF NOT EXISTS categories(id TEXT PRIMARY KEY,name TEXT,fields TEXT,position INTEGER)')
        db.execute("CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,category_id TEXT,data TEXT,position INTEGER DEFAULT 0,updated_at TEXT DEFAULT CURRENT_TIMESTAMP,color TEXT NOT NULL DEFAULT 'none')")
        if 'color' not in {row['name'] for row in db.execute('PRAGMA table_info(records)')}:
            db.execute("ALTER TABLE records ADD COLUMN color TEXT NOT NULL DEFAULT 'none'")
        if db.execute('SELECT COUNT(*) FROM categories').fetchone()[0]==0:
            for pos,c in enumerate(json.loads((ROOT/'seed.json').read_text(encoding='utf-8'))['categories']):
                db.execute('INSERT INTO categories VALUES(?,?,?,?)',(c['id'],c['name'],json.dumps(c['fields'],ensure_ascii=False),pos))
                for order,r in enumerate(c['records']): db.execute('INSERT INTO records(id,category_id,data,position) VALUES(?,?,?,?)',(r['id'],c['id'],json.dumps(r['values'],ensure_ascii=False),order))
def categories():
    with connect() as db:
        result=[]
        for c in db.execute('SELECT * FROM categories ORDER BY position'):
            records=db.execute('SELECT id,data,color,updated_at FROM records WHERE category_id=? ORDER BY position,rowid',(c['id'],)).fetchall()
            result.append({'id':c['id'],'name':c['name'],'fields':json.loads(c['fields']),'records':[{'id':r['id'],'values':json.loads(r['data']),'color':r['color'],'updatedAt':r['updated_at']} for r in records]})
        return result
class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*a,**kw): super().__init__(*a,directory=str(ROOT),**kw)
    def log_message(self,fmt,*args): print('%s - %s'%(self.address_string(),fmt%args),flush=True)
    def end_headers(self):
        if urlparse(self.path).path in {'/','/index.html','/app.js','/styles.css'}:
            self.send_header('Cache-Control','no-store, no-cache, must-revalidate')
        super().end_headers()
    def auth(self):
        if not PASSWORD:return True
        try:
            scheme,value=self.headers.get('Authorization','').split(' ',1); u,p=base64.b64decode(value).decode().split(':',1); ok=scheme.lower()=='basic' and u==USER and p==PASSWORD
        except Exception:ok=False
        if not ok:self.send_response(401);self.send_header('WWW-Authenticate','Basic realm="Relevamiento de equipos", charset="UTF-8"');self.send_header('Content-Length','0');self.end_headers()
        return ok
    def json(self,status,obj):
        body=json.dumps(obj,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
    def payload(self):
        n=int(self.headers.get('Content-Length','0'))
        if n>1000000:raise ValueError('El contenido supera el tamaño permitido')
        return json.loads(self.rfile.read(n) or b'{}')
    def do_GET(self):
        if not self.auth():return
        path=urlparse(self.path).path
        if path=='/api/data':return self.json(200,{'categories':categories()})
        if path=='/health':return self.json(200,{'status':'ok'})
        if path.startswith('/api/'):return self.json(404,{'error':'No encontrado'})
        if path=='/':self.path='/index.html'
        return super().do_GET()
    def do_POST(self):
        if not self.auth():return
        if urlparse(self.path).path!='/api/records':return self.json(404,{'error':'No encontrado'})
        try:
            p=self.payload(); cid=str(p['categoryId']); values=p['values']; color=p.get('color','none'); rid=str(uuid.uuid4())
            if not isinstance(values,dict):raise ValueError('Campos no válidos')
            if color not in ROW_COLORS:raise ValueError('Color no válido')
            with connect() as db:
                if not db.execute('SELECT 1 FROM categories WHERE id=?',(cid,)).fetchone():return self.json(404,{'error':'Pestaña no encontrada'})
                pos=db.execute('SELECT COALESCE(MAX(position),-1)+1 FROM records WHERE category_id=?',(cid,)).fetchone()[0]
                db.execute('INSERT INTO records(id,category_id,data,position,color) VALUES(?,?,?,?,?)',(rid,cid,json.dumps(values,ensure_ascii=False),pos,color))
            return self.json(201,{'id':rid})
        except (ValueError,KeyError,json.JSONDecodeError) as e:return self.json(400,{'error':str(e)})
    def do_PUT(self):
        if not self.auth():return
        parts=urlparse(self.path).path.strip('/').split('/')
        if len(parts)!=3 or parts[:2]!=['api','records']:return self.json(404,{'error':'No encontrado'})
        try:
            p=self.payload(); values=p.get('values'); color=p.get('color','none')
            if not isinstance(values,dict):raise ValueError('Campos no válidos')
            if color not in ROW_COLORS:raise ValueError('Color no válido')
            with connect() as db:
                cur=db.execute('UPDATE records SET data=?,color=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(json.dumps(values,ensure_ascii=False),color,parts[2]))
                if cur.rowcount==0:return self.json(404,{'error':'Registro no encontrado'})
            return self.json(200,{'ok':True})
        except (ValueError,json.JSONDecodeError) as e:return self.json(400,{'error':str(e)})
    def do_DELETE(self):
        if not self.auth():return
        parts=urlparse(self.path).path.strip('/').split('/')
        if len(parts)!=3 or parts[:2]!=['api','records']:return self.json(404,{'error':'No encontrado'})
        with connect() as db:
            cur=db.execute('DELETE FROM records WHERE id=?',(parts[2],))
            if not cur.rowcount:return self.json(404,{'error':'Registro no encontrado'})
        return self.json(200,{'ok':True})
if __name__=='__main__':
    initialize();port=int(os.environ.get('PORT','8080'));print(f'Relevamiento escuchando en :{port}',flush=True);ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
