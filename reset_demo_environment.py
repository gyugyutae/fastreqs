from fastreqs.config import Config, ROOT
from fastreqs.store import Store
from fastreqs.documents import read, sections
from datetime import datetime
import sqlite3, shutil
c=Config.load();s=Store(c.data_dir)
backup=c.data_dir/'backups'/('full-reset-'+datetime.now().strftime('%Y%m%d-%H%M%S'));backup.mkdir(parents=True)
with sqlite3.connect(backup/'mvp.db') as target:s.db.backup(target)
bindings=s.all('binding')
for b in bindings:
    shutil.copytree(b['folder'],backup/b['channel'])
    for name in ['prd.md','user-stories.md','spec.md','adr.md']:
        shutil.copy2(ROOT/'demo-fixtures'/'team-search'/name, __import__('pathlib').Path(b['folder'])/name)
with s.tx():
    s.db.execute("DELETE FROM records WHERE kind != 'binding'")
    for b in bindings:s.source(b['id'])
for b in bindings:
    docs=read(b['folder'])
    assert list(sections(docs['user-stories.md']))==['US-001','US-002','US-003']
    assert 'US-005' not in ''.join(docs.values())
print('RESET_OK');print('BACKUP',backup)
print('KEYS_AND_BINDINGS_PRESERVED')
