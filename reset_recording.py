from fastreqs.config import Config
from fastreqs.store import Store
from pathlib import Path
from datetime import datetime
import sqlite3, shutil
c=Config.load();s=Store(c.data_dir)
backup=c.data_dir/'backups'/datetime.now().strftime('%Y%m%d-%H%M%S');backup.mkdir(parents=True)
with sqlite3.connect(backup/'mvp.db') as destination:s.db.backup(destination)
for b in s.all('binding'):shutil.copytree(b['folder'],backup/b['channel'])
files=[x for x in s.all('source') if x.get('content') is not None]
with s.tx():
    for source in files:
        for p in s.all('candidate',source=source['id']):
            if p['status'] in ('pending','clarifying','conflicted'):
                p['status']='replaced';s.put('candidate',p)
        for e in s.all('event',source=source['id']):
            s.db.execute('DELETE FROM records WHERE kind=? AND id=?',('event',e['id']))
        s.db.execute('DELETE FROM records WHERE kind=? AND id=?',('source',source['id']))
print('RECORDING_RESET',len(files));print('BACKUP',backup)
