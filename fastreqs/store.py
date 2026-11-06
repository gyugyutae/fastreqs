"""SQLite JSON records with serialized transactions; secrets are never persisted."""
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone

def now(): return datetime.now(timezone.utc).isoformat()

class Store:
    def __init__(self, root):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / 'mvp.db', check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS records(kind TEXT,id TEXT,data TEXT,PRIMARY KEY(kind,id))')
        self.db.commit()
    @contextmanager
    def tx(self):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try: yield; self.db.commit()
            except Exception: self.db.rollback(); raise
    def put(self, kind, item):
        self.db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?)', (kind,item['id'],json.dumps(item,ensure_ascii=False)))
    def get(self, kind, ident):
        with self.lock:
            row=self.db.execute('SELECT data FROM records WHERE kind=? AND id=?',(kind,ident)).fetchone()
            if not row: raise ValueError('저장 항목을 찾지 못했습니다.')
            return json.loads(row[0])
    def all(self, record_kind, **filters):
        with self.lock:
            values=[json.loads(r[0]) for r in self.db.execute('SELECT data FROM records WHERE kind=? ORDER BY rowid',(record_kind,))]
            return [v for v in values if all(v.get(k)==x for k,x in filters.items())]
    def bind(self, workspace, channel, folder):
        from .documents import read
        folder=str(Path(folder).resolve()); read(folder)
        ident=workspace+'/'+channel
        with self.tx():
            for b in self.all('binding'):
                if b['folder']==folder and b['id']!=ident: raise ValueError('다른 채널에 연결된 폴더입니다.')
                if b['id']==ident and b['folder']!=folder: raise ValueError('기존 채널 연결은 다른 폴더로 바꿀 수 없습니다. 새 채널을 사용하세요.')
            b={'id':ident,'workspace':workspace,'channel':channel,'folder':folder}; self.put('binding',b)
            self.source(ident)
        return b
    def source(self, binding, thread=None, content=None):
        from .documents import digest
        ident=binding+('/file/'+digest(content) if content is not None else '/channel')
        existing=self.all('source',id=ident)
        if existing: return existing[0],False
        value={'id':ident,'binding':binding,'thread':thread,'content':content,'cursor':0,'busy':False,'followup':False}
        self.put('source',value); return value,True
    def event(self, source, ts, user, text,thread=None):
        ident=source+':'+ts
        with self.tx():
            if self.all('event',id=ident): return False
            seq=max([e['seq'] for e in self.all('event',source=source)] or [0])+1
            self.put('event',{'id':ident,'source':source,'seq':seq,'user':user,'text':text,'ts':ts,'thread':thread})
        return True
    def reserve(self,binding,prefix,docs):
        import re
        numbers=[int(x) for x in re.findall(prefix+r'-(\d+)', '\n'.join(docs.values()))]
        numbers += [int(r['value'].split('-')[1]) for r in self.all('reserved',binding=binding,prefix=prefix)]
        value=f'{prefix}-{max(numbers or [0])+1:03d}'
        self.put('reserved',{'id':binding+':'+value,'binding':binding,'prefix':prefix,'value':value})
        return value
    @staticmethod
    def ident(): return uuid.uuid4().hex
