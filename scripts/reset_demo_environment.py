"""데모를 처음 상태로 되돌리는 운영 스크립트.

DB와 문서 폴더를 백업한 뒤, 연결(binding)과 키는 남기고 나머지 상태를
지우며 문서를 초기 템플릿으로 바꾼다.

사용 예:
    python -m scripts.reset_demo_environment
"""

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from fastreqs.config import ROOT, Config
from fastreqs.documents import (
    DOCUMENT_NAMES,
    USER_STORIES,
    parse_sections,
    read_documents,
)
from fastreqs.store import StateStore

FIXTURE_FOLDER = ROOT / 'demo-fixtures' / 'team-search'
INITIAL_STORIES = ['US-001', 'US-002', 'US-003']


def back_up(store, data_dir, bindings):
    """DB와 연결된 문서 폴더를 시각별 백업 폴더에 복사한다."""
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = data_dir / 'backups' / ('full-reset-' + stamp)
    backup.mkdir(parents=True)
    with sqlite3.connect(backup / 'mvp.db') as target:
        store.db.backup(target)
    for binding in bindings:
        shutil.copytree(binding['folder'], backup / binding['channel'])
    return backup


def main():
    """백업 후 상태와 문서를 초기화하고 결과를 검증한다."""
    config = Config.load()
    store = StateStore(config.data_dir)
    bindings = store.find_all('binding')
    backup = back_up(store, config.data_dir, bindings)
    for binding in bindings:
        for name in DOCUMENT_NAMES:
            shutil.copy2(FIXTURE_FOLDER / name, Path(binding['folder']) / name)
    with store.transaction():
        store.db.execute("DELETE FROM records WHERE kind != 'binding'")
        for binding in bindings:
            store.get_or_create_source(binding['id'])
    for binding in bindings:
        documents = read_documents(binding['folder'])
        stories = list(parse_sections(documents[USER_STORIES]))
        assert stories == INITIAL_STORIES
        assert 'US-005' not in ''.join(documents.values())
    print('RESET_OK')
    print('BACKUP', backup)
    print('KEYS_AND_BINDINGS_PRESERVED')


if __name__ == '__main__':
    main()
