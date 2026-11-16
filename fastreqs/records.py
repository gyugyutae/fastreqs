"""후보 레코드와 결정 요청을 표현하는 데이터 클래스.

후보는 저장소(StateStore)에는 JSON 딕셔너리로 저장되지만, 코드 안에서는
CandidateRecord로 다룬다. 상태는 문자열 대신 CandidateStatus를 쓴다.

사용 예:
    record = CandidateRecord.from_dict(store.get('candidate', record_id))
    if record.is_active:
        record.status = CandidateStatus.REJECTED
    store.put('candidate', record.to_dict())
"""

from dataclasses import asdict, dataclass, field, fields
from enum import Enum

KIND_CONFLICT = 'conflict'
KEEP_NEW = 'new'


class CandidateStatus(str, Enum):
    """후보 처리 상태."""

    PENDING = 'pending'
    CLARIFYING = 'clarifying'
    CONFLICTED = 'conflicted'
    APPLYING = 'applying'
    APPLIED = 'applied'
    REJECTED = 'rejected'
    REPLACED = 'replaced'
    STALE = 'stale'
    APPLY_FAILED = 'apply_failed'


ACTIVE_STATUSES = frozenset({
    CandidateStatus.PENDING,
    CandidateStatus.CLARIFYING,
    CandidateStatus.CONFLICTED,
})


@dataclass
class CandidateRecord:
    """승인을 기다리는 요구사항 후보(설계의 Candidate).

    Attributes:
        id: 후보 ID.
        binding: 채널 연결 ID.
        source: 후보가 나온 입력 경로 ID.
        kind: 'story', 'spec', 'adr', 'conflict' 중 하나.
        target: 대상 Story ID.
        status: 처리 상태.
        payload: 후보 내용(Candidate 직렬화 또는 기술 변경 내용).
        docs: 후보를 만들 때 읽은 문서 내용.
        plan: 승인하면 저장할 {파일명: 새 내용}.
        version: 버튼에 담기는 후보 버전.
        thread: 후보 대화가 이어지는 Slack 스레드 ts.
        message: 후보 카드 메시지 ts.
        created: 생성 시각.
        story_hash: 기술 후보가 기준으로 삼은 Story 해시.
        conflict: 충돌 정보 {'requirement_ids': [...], 'reason': ...}.
        actor: 결정한 사용자 ID.
        decided_at: 결정 시각.
    """

    id: str
    binding: str
    source: str
    kind: str
    target: str
    status: CandidateStatus
    payload: dict
    docs: dict
    plan: dict = field(default_factory=dict)
    version: int = 1
    thread: str | None = None
    message: str | None = None
    created: str = ''
    story_hash: str = ''
    conflict: dict | None = None
    actor: str | None = None
    decided_at: str | None = None

    @property
    def is_active(self):
        """아직 결정되지 않은 후보인지 돌려준다."""
        return self.status in ACTIVE_STATUSES

    @property
    def conflict_ids(self):
        """충돌한 기존 요구사항 ID 목록을 돌려준다."""
        return list((self.conflict or {}).get('requirement_ids', []))

    def to_dict(self):
        """저장용 딕셔너리로 바꾼다."""
        data = asdict(self)
        data['status'] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data):
        """저장된 딕셔너리에서 레코드를 만든다. 모르는 키는 무시한다."""
        names = {item.name for item in fields(cls)}
        values = {key: value for key, value in data.items() if key in names}
        values['status'] = CandidateStatus(values['status'])
        return cls(**values)


@dataclass(frozen=True)
class Decision:
    """버튼으로 들어온 사용자 결정 요청.

    Attributes:
        binding_id: 버튼을 누른 채널 연결 ID.
        candidate_id: 결정 대상 후보 ID.
        version: 버튼에 담긴 후보 버전.
        user_id: 결정한 사용자 ID.
    """

    binding_id: str
    candidate_id: str
    version: int
    user_id: str


@dataclass(frozen=True)
class CandidateOptions:
    """새 후보를 만들 때의 선택 사항.

    Attributes:
        thread: 이어 쓸 Slack 스레드 ts(정정·재생성 때 이전 후보의 자리).
        target: 이미 예약한 Story ID.
        conflicts: 충돌 검사에서 찾은 Conflict 목록.
    """

    thread: str | None = None
    target: str | None = None
    conflicts: tuple = ()
