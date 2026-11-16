"""대화·후보·작업 상태를 SQLite에 JSON 레코드로 저장하는 모듈.

요구사항 문서 자체는 저장하지 않는다(문서는 Markdown 파일이 기준).
키와 토큰도 저장하지 않는다.

사용 예:
    store = StateStore(data_dir)
    with store.transaction():
        store.put('candidate', record)
"""

import json
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .documents import compute_digest, read_documents
from .records import CandidateRecord

DATABASE_NAME = 'mvp.db'
CHANNEL_SOURCE_SUFFIX = '/channel'
FILE_SOURCE_INFIX = '/file/'


def utc_now():
    """현재 UTC 시각을 ISO-8601 문자열로 돌려준다."""
    return datetime.now(timezone.utc).isoformat()


def new_id():
    """새 내부 ID(UUID hex)를 돌려준다."""
    return uuid.uuid4().hex


def binding_key(workspace_id, channel_id):
    """워크스페이스와 채널로 연결 ID를 만든다."""
    return workspace_id + '/' + channel_id


class StateStore:
    """종류(kind)와 ID로 JSON 레코드를 저장·조회한다.

    Attributes:
        root: 데이터 폴더.
        db: SQLite 연결.
    """

    def __init__(self, root):
        """데이터 폴더와 테이블을 준비한다."""
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(
            self.root / DATABASE_NAME, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute(
            'CREATE TABLE IF NOT EXISTS records('
            'kind TEXT, id TEXT, data TEXT, PRIMARY KEY(kind, id))')
        self.db.commit()

    def close(self):
        """DB 연결을 닫는다."""
        self.db.close()

    @contextmanager
    def transaction(self):
        """직렬화된 쓰기 트랜잭션을 연다. 예외가 나면 롤백한다."""
        with self._lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

    def put(self, kind, record):
        """레코드를 저장한다(같은 ID면 덮어쓴다)."""
        data = json.dumps(record, ensure_ascii=False)
        self.db.execute(
            'INSERT OR REPLACE INTO records VALUES(?, ?, ?)',
            (kind, record['id'], data))

    def delete(self, kind, record_id):
        """레코드 하나를 지운다."""
        self.db.execute(
            'DELETE FROM records WHERE kind=? AND id=?', (kind, record_id))

    def get(self, kind, record_id):
        """레코드 하나를 돌려준다.

        Raises:
            ValueError: 레코드가 없는 경우.
        """
        with self._lock:
            row = self.db.execute(
                'SELECT data FROM records WHERE kind=? AND id=?',
                (kind, record_id)).fetchone()
        if not row:
            raise ValueError('저장 항목을 찾지 못했습니다.')
        return json.loads(row[0])

    def find_all(self, kind, /, **filters):
        """종류가 같고 필터 값이 모두 일치하는 레코드를 저장 순서로 돌려준다."""
        with self._lock:
            rows = self.db.execute(
                'SELECT data FROM records WHERE kind=? ORDER BY rowid',
                (kind,)).fetchall()
        records = [json.loads(row[0]) for row in rows]
        return [
            record for record in records
            if all(record.get(key) == value for key, value in filters.items())
        ]

    def get_candidate(self, candidate_id):
        """후보 하나를 CandidateRecord로 돌려준다."""
        return CandidateRecord.from_dict(self.get('candidate', candidate_id))

    def put_candidate(self, record):
        """CandidateRecord를 저장한다."""
        self.put('candidate', record.to_dict())

    def find_candidates(self, **filters):
        """필터에 맞는 후보를 CandidateRecord 목록으로 돌려준다."""
        return [CandidateRecord.from_dict(data)
                for data in self.find_all('candidate', **filters)]

    def bind(self, workspace_id, channel_id, folder):
        """채널과 문서 폴더를 연결한다.

        Returns:
            저장된 연결 레코드.

        Raises:
            ValueError: 폴더가 다른 채널에 연결됐거나 채널 폴더를 바꾸려는 경우.
        """
        folder = str(Path(folder).resolve())
        read_documents(folder)
        binding_id = binding_key(workspace_id, channel_id)
        with self.transaction():
            for binding in self.find_all('binding'):
                same_folder = binding['folder'] == folder
                same_channel = binding['id'] == binding_id
                if same_folder and not same_channel:
                    raise ValueError('다른 채널에 연결된 폴더입니다.')
                if same_channel and not same_folder:
                    raise ValueError('기존 채널 연결은 다른 폴더로 바꿀 수 '
                                     '없습니다. 새 채널을 사용하세요.')
            binding = {'id': binding_id, 'workspace': workspace_id,
                       'channel': channel_id, 'folder': folder}
            self.put('binding', binding)
            self.get_or_create_source(binding_id)
        return binding

    def get_or_create_source(self, binding_id, thread=None, content=None):
        """입력 경로(채널 또는 회의록 파일)를 찾거나 만든다.

        Returns:
            (source 레코드, 새로 만들었는지 여부).
        """
        if content is None:
            source_id = binding_id + CHANNEL_SOURCE_SUFFIX
        else:
            source_id = binding_id + FILE_SOURCE_INFIX + compute_digest(content)
        existing = self.find_all('source', id=source_id)
        if existing:
            return existing[0], False
        source = {'id': source_id, 'binding': binding_id, 'thread': thread,
                  'content': content, 'cursor': 0, 'busy': False,
                  'followup': False}
        self.put('source', source)
        return source, True

    def add_event(self, source_id, ts, user_id, text, thread=None):
        """새 대화 이벤트를 순번과 함께 저장한다.

        Returns:
            새로 저장했으면 True, 이미 있던 이벤트면 False.
        """
        event_id = source_id + ':' + ts
        with self.transaction():
            if self.find_all('event', id=event_id):
                return False
            events = self.find_all('event', source=source_id)
            sequence = max([event['seq'] for event in events] or [0]) + 1
            self.put('event', {'id': event_id, 'source': source_id,
                               'seq': sequence, 'user': user_id, 'text': text,
                               'ts': ts, 'thread': thread})
        return True

    def reserve_id(self, binding_id, prefix, documents):
        """문서와 예약 목록에서 쓰지 않은 다음 ID(예: US-004)를 예약한다."""
        pattern = re.escape(prefix) + r'-(\d+)'
        numbers = [int(number) for number in
                   re.findall(pattern, '\n'.join(documents.values()))]
        reserved = self.find_all('reserved', binding=binding_id, prefix=prefix)
        numbers += [int(record['value'].split('-')[1]) for record in reserved]
        value = f'{prefix}-{max(numbers or [0]) + 1:03d}'
        self.put('reserved', {'id': binding_id + ':' + value,
                              'binding': binding_id, 'prefix': prefix,
                              'value': value})
        return value
