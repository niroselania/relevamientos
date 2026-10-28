#!/usr/bin/env python3
"""Dependency-free inventory app backed by SQLite."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import base64, datetime, io, json, os, posixpath, re, sqlite3, unicodedata, uuid, zipfile
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parent
DATA=Path(os.environ.get('DATA_DIR','/data')); DATA.mkdir(parents=True,exist_ok=True)
DB=DATA/'relevamiento.db'; USER=os.environ.get('APP_USER',''); PASSWORD=os.environ.get('APP_PASSWORD','')
ROW_COLORS={'none','orange','yellow','green','blue','red','purple'}
XLS_NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL_NS='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PKG_REL_NS='http://schemas.openxmlformats.org/package/2006/relationships'
def connect():
    db=sqlite3.connect(DB,timeout=30); db.row_factory=sqlite3.Row; return db
def initialize():
    with connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE IF NOT EXISTS categories(id TEXT PRIMARY KEY,name TEXT,fields TEXT,position INTEGER)')
        db.execute("CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,category_id TEXT,data TEXT,position INTEGER DEFAULT 0,updated_at TEXT DEFAULT CURRENT_TIMESTAMP,color TEXT NOT NULL DEFAULT 'none')")
        columns={row['name'] for row in db.execute('PRAGMA table_info(records)')}
        if 'color' not in columns: db.execute("ALTER TABLE records ADD COLUMN color TEXT NOT NULL DEFAULT 'none'")
        if 'source_row' not in columns: db.execute('ALTER TABLE records ADD COLUMN source_row INTEGER')
        if db.execute('SELECT COUNT(*) FROM categories').fetchone()[0]==0:
            for pos,c in enumerate(json.loads((ROOT/'seed.json').read_text(encoding='utf-8'))['categories']):
                db.execute('INSERT INTO categories VALUES(?,?,?,?)',(c['id'],c['name'],json.dumps(c['fields'],ensure_ascii=False),pos))
                for order,r in enumerate(c['records']): db.execute('INSERT INTO records(id,category_id,data,position,source_row) VALUES(?,?,?,?,?)',(r['id'],c['id'],json.dumps(r['values'],ensure_ascii=False),order,r.get('sourceRow')))
def categories():
    with connect() as db:
        result=[]
        for c in db.execute('SELECT * FROM categories ORDER BY position'):
            records=db.execute('SELECT id,data,color,updated_at FROM records WHERE category_id=? ORDER BY position,rowid',(c['id'],)).fetchall()
            result.append({'id':c['id'],'name':c['name'],'fields':json.loads(c['fields']),'records':[{'id':r['id'],'values':json.loads(r['data']),'color':r['color'],'updatedAt':r['updated_at']} for r in records]})
        return result

def norm(value):
    text=unicodedata.normalize('NFD',str(value or ''))
    return ''.join(ch for ch in text if unicodedata.category(ch)!='Mn').casefold().strip()

def column_index(reference):
    letters=re.match(r'([A-Z]+)',reference.upper())
    if not letters:return 0
    result=0
    for char in letters.group(1):result=result*26+ord(char)-64
    return result-1

def parse_xlsx(raw):
    """Read workbook rows with the Python standard library (no pip dependency)."""
    try: archive=zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile: raise ValueError('El archivo no parece ser un Excel .xlsx válido')
    with archive:
        names=set(archive.namelist())
        if 'xl/workbook.xml' not in names:raise ValueError('No encontré la estructura de un libro Excel')
        workbook=ET.fromstring(archive.read('xl/workbook.xml'))
        relroot=ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        relationships={rel.attrib['Id']:rel.attrib['Target'] for rel in relroot.findall(f'{{{PKG_REL_NS}}}Relationship')}
        shared=[]
        if 'xl/sharedStrings.xml' in names:
            root=ET.fromstring(archive.read('xl/sharedStrings.xml'))
            shared=[''.join(t.text or '' for t in item.iter(f'{{{XLS_NS}}}t')) for item in root.findall(f'{{{XLS_NS}}}si')]
        custom_formats={}
        styles={}
        if 'xl/styles.xml' in names:
            root=ET.fromstring(archive.read('xl/styles.xml'))
            fmts=root.find(f'{{{XLS_NS}}}numFmts')
            if fmts is not None:
                for item in fmts.findall(f'{{{XLS_NS}}}numFmt'):custom_formats[int(item.attrib['numFmtId'])]=item.attrib.get('formatCode','')
            xfs=root.find(f'{{{XLS_NS}}}cellXfs')
            if xfs is not None:
                for i,xf in enumerate(xfs.findall(f'{{{XLS_NS}}}xf')):
                    fmt=int(xf.attrib.get('numFmtId','0')); code=custom_formats.get(fmt,'')
                    styles[i]=fmt in set(range(14,23))|{45,46,47} or bool(re.search(r'[yd]',re.sub(r'"[^"]*"|\\.|\[[^]]*\]','',code),re.I))
        sheets=[]
        for sheet in workbook.find(f'{{{XLS_NS}}}sheets'):
            target=relationships.get(sheet.attrib.get(f'{{{REL_NS}}}id'))
            if not target:continue
            path=target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join('xl',target))
            if path not in names:continue
            root=ET.fromstring(archive.read(path)); rows=[]
            for row in root.findall(f'.//{{{XLS_NS}}}sheetData/{{{XLS_NS}}}row'):
                row_no=int(row.attrib.get('r','0')); cells=[]
                for cell in row.findall(f'{{{XLS_NS}}}c'):
                    idx=column_index(cell.attrib.get('r','A1'))
                    while len(cells)<=idx:cells.append(None)
                    kind=cell.attrib.get('t',''); v=cell.find(f'{{{XLS_NS}}}v')
                    if kind=='inlineStr':value=''.join(t.text or '' for t in cell.iter(f'{{{XLS_NS}}}t'))
                    elif v is None:value=None
                    elif kind=='s':value=shared[int(v.text)]
                    elif kind=='b':value='Sí' if v.text=='1' else 'No'
                    else:
                        text=v.text or ''
                        try:
                            number=float(text)
                            if styles.get(int(cell.attrib.get('s','0')),False):
                                date=datetime.datetime(1899,12,30)+datetime.timedelta(days=number)
                                value=date.date().isoformat() if date.time()==datetime.time() else date.isoformat(timespec='seconds')
                            elif number.is_integer():value=str(int(number))
                            else:value=text
                        except (ValueError,OverflowError):value=text
                    cells[idx]=value
                if any(v is not None and str(v).strip() for v in cells):rows.append((row_no,cells))
            sheets.append((sheet.attrib.get('name',''),rows))
        return sheets

def field_signature(fields):
    count={}; signatures=[]
    for field in fields:
        label=norm(field.get('label','')); count[label]=count.get(label,0)+1; signatures.append((label,count[label]))
    return signatures

def usable_serial(value):
    value=norm(value)
    return value if value and value not in {'-','--','---','n/a','na','s/d','sin serie'} else ''

def record_fingerprint(values,keys):
    return tuple(norm(values.get(key)) for key in keys)

def import_workbook(raw):
    sheets=parse_xlsx(raw)
    if not sheets:raise ValueError('El Excel no contiene pestañas legibles')
    sheet_map={norm(name):rows for name,rows in sheets}
    if not any(name in sheet_map for name in ('computadoras','colectora datos','tablet','faltantes','dadas de baja')):
        raise ValueError('No encontré las pestañas del relevamiento en este Excel')
    with connect() as db:
        cats={norm(c['name']):c for c in db.execute('SELECT * FROM categories')}
        missing=set(cats)-set(sheet_map)
        if missing:raise ValueError('Importación cancelada: faltan pestañas requeridas: '+', '.join(cats[key]['name'] for key in sorted(missing)))
        # La planilla original tiene una pestaña de bajas sin encabezados.
        if 'dadas de baja' in sheet_map and sheet_map['dadas de baja']:
            computer_rows=sheet_map.get('computadoras',[])
            if computer_rows:sheet_map['dadas de baja']=[(sheet_map['dadas de baja'][0][0],computer_rows[0][1][:9])]+sheet_map['dadas de baja']
        summary={'updated':0,'added':0,'removed':0,'sheets':0,'unmatchedSheets':[]}
        for sheet_name,rows in sheets:
            key=norm(sheet_name)
            if key not in cats:
                summary['unmatchedSheets'].append(sheet_name); continue
            if not rows:continue
            category=cats[key]; category_id=category['id']
            rows=sheet_map.get(key,rows)
            header_row,header_values=rows[0]
            headers=header_values; data_rows=rows[1:]
            headers=[str(h).strip() if h is not None and str(h).strip() else f'Campo {i+1}' for i,h in enumerate(headers)]
            old_fields=json.loads(category['fields']); old_sig=field_signature(old_fields)
            old_by_sig={sig:field for sig,field in zip(old_sig,old_fields)}
            new_keys=[]; new_fields=[]; next_key=max([int(m.group(1)) for f in old_fields if (m:=re.fullmatch(r'f(\d+)',f['key']))] or [0])+1
            occurrence={}
            for label in headers:
                normalized=norm(label); occurrence[normalized]=occurrence.get(normalized,0)+1; sig=(normalized,occurrence[normalized])
                existing=old_by_sig.get(sig); field_key=existing['key'] if existing else f'f{next_key}'
                if not existing:next_key+=1
                new_keys.append(field_key);new_fields.append({'key':field_key,'label':label})
            new_sigs=field_signature(new_fields);new_sigset=set(new_sigs)
            for sig,field in zip(old_sig,old_fields):
                if sig not in new_sigset:new_fields.append(field)
            all_records=db.execute('SELECT id,data,color,source_row,position FROM records WHERE category_id=? ORDER BY position,rowid',(category_id,)).fetchall()
            # Re-key old records if a sheet added or moved a column.
            remapped={}
            for record in all_records:
                old_values=json.loads(record['data']); values={}
                for sig,field in zip(old_sig,old_fields):
                    target=old_by_sig[sig]['key'] if sig in new_sigset else field['key']
                    values[target]=old_values.get(field['key'])
                remapped[record['id']]=values
                db.execute('UPDATE records SET data=? WHERE id=?',(json.dumps(values,ensure_ascii=False),record['id']))
            db.execute('UPDATE categories SET fields=? WHERE id=?',(json.dumps(new_fields,ensure_ascii=False),category_id))
            # Build matching indexes on serial numbers, exact values, and source
            # row number. Existing records absent from the file are never deleted.
            serial_fields=[f['key'] for f in new_fields if 'serie' in norm(f['label'])]
            serial_index={}; fingerprint_index={}; source_index={}
            imported_keys=new_keys
            for record in all_records:
                values=remapped[record['id']]
                for fkey in serial_fields:
                    serial=usable_serial(values.get(fkey))
                    if serial:serial_index.setdefault(serial,[]).append(record['id'])
                fingerprint_index.setdefault(record_fingerprint(values,imported_keys),[]).append(record['id'])
                if record['source_row'] is not None:source_index.setdefault(record['source_row'],[]).append(record['id'])
            used=set();pos=db.execute('SELECT COALESCE(MAX(position),-1)+1 FROM records WHERE category_id=?',(category_id,)).fetchone()[0]
            for source_row,values_list in data_rows:
                if not any(v is not None and str(v).strip() for v in values_list):continue
                incoming={}
                for i,fkey in enumerate(new_keys):
                    value=values_list[i] if i<len(values_list) else None
                    incoming[fkey]=str(value).strip() if value is not None else ''
                serials={usable_serial(incoming.get(fkey)) for fkey in serial_fields}; serials.discard('')
                candidates={rid for serial in serials for rid in serial_index.get(serial,[]) if rid not in used}
                match=next(iter(candidates)) if len(candidates)==1 else None
                if match is None:
                    fp=record_fingerprint(incoming,imported_keys); exact=[rid for rid in fingerprint_index.get(fp,[]) if rid not in used]
                    if len(exact)==1:match=exact[0]
                if match is None:
                    same_row=[rid for rid in source_index.get(source_row,[]) if rid not in used]
                    if len(same_row)==1:match=same_row[0]
                if match:
                    merged=remapped[match];merged.update(incoming);used.add(match)
                    db.execute('UPDATE records SET data=?,source_row=? WHERE id=?',(json.dumps(merged,ensure_ascii=False),source_row,match));summary['updated']+=1
                else:
                    for field in new_fields:incoming.setdefault(field['key'],'')
                    rid=str(uuid.uuid4())
                    db.execute("INSERT INTO records(id,category_id,data,position,source_row) VALUES(?,?,?,?,?)",(rid,category_id,json.dumps(incoming,ensure_ascii=False),pos,source_row));pos+=1;used.add(rid);summary['added']+=1
            obsolete=[record['id'] for record in all_records if record['id'] not in used]
            if obsolete:
                db.executemany('DELETE FROM records WHERE id=?',[(rid,) for rid in obsolete]);summary['removed']+=len(obsolete)
            summary['sheets']+=1
        return summary
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
        if n>25000000:raise ValueError('El archivo supera el tamaño permitido (18 MB)')
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
        path=urlparse(self.path).path
        if path=='/api/import':
            try:
                p=self.payload(); name=str(p.get('fileName','')).lower(); encoded=p.get('file','')
                if not name.endswith('.xlsx'):raise ValueError('Elegí un archivo Excel .xlsx')
                if not isinstance(encoded,str):raise ValueError('El archivo no es válido')
                raw=base64.b64decode(encoded,validate=True)
                if len(raw)>18000000:raise ValueError('El archivo supera el límite de 18 MB')
                return self.json(200,import_workbook(raw))
            except (ValueError,KeyError,json.JSONDecodeError,ET.ParseError,zipfile.BadZipFile) as e:return self.json(400,{'error':str(e)})
        if path!='/api/records':return self.json(404,{'error':'No encontrado'})
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
