"""녹화를 다시 하기 위해 회의록 입력 경로만 지우는 운영 스크립트.

DB와 문서를 백업한 뒤 파일 입력 경로의 미결 후보는 replaced로 바꾸고,
그 경로의 대화 이벤트와 입력 경로 레코드를 지운다.

사용 예:
    python -m scripts.reset_recording
"""

import shutil
import sqlite3
from datetime import datetime

from fastreqs.config import Config
from fastreqs.records import CandidateStatus
from fastreqs.store import StateStore


def back_up(store, data_dir):
    """DB와 연결된 문서 폴더를 시각별 백업 폴더에 복사한다."""
    backup = data_dir / 'backups' / datetime.now().strftime('%Y%m%d-%H%M%S')
    backup.mkdir(parents=True)
    with sqlite3.connect(backup / 'mvp.db') as destination:
        store.db.backup(destination)
    for binding in store.find_all('binding'):
        shutil.copytree(binding['folder'], backup / binding['channel'])
    return backup


def main():
    """회의록 입력 경로와 그 후보·이벤트를 정리한다."""
    config = Config.load()
    store = StateStore(config.data_dir)
    backup = back_up(store, config.data_dir)
    file_sources = [source for source in store.find_all('source')
                    if source.get('content') is not None]
    with store.transaction():
        for source in file_sources:
            for record in store.find_candidates(source=source['id']):
                if record.is_active:
                    record.status = CandidateStatus.REPLACED
                    store.put_candidate(record)
            for event in store.find_all('event', source=source['id']):
                store.delete('event', event['id'])
            store.delete('source', source['id'])
    print('RECORDING_RESET', len(file_sources))
    print('BACKUP', backup)


if __name__ == '__main__':
    main()
