"""AI 분석 결과를 검증하는 데이터 모델.

설계의 Requirement(요구사항) 개념을 Story·Candidate로 구체화한다.
모델이 돌려준 JSON은 이 모델을 통과해야만 후보로 쓰인다.

사용 예:
    analysis = Analysis.model_validate_json(raw_json)
    for candidate in analysis.candidates:
        candidate.needs_answer()
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_TITLE_LENGTH = 200
MAX_SHORT_TEXT_LENGTH = 1000
MAX_TEXT_LENGTH = 2000
MAX_EVIDENCE_LENGTH = 1500
MAX_SPEC_LENGTH = 6000
MAX_ACCEPTANCE_COUNT = 10
MAX_CANDIDATE_COUNT = 8

STORY_ID_OR_EMPTY = r'^(US-\d{3,}|)$'
MAX_CONFLICT_COUNT = 10
MAX_CONFLICT_IDS = 2
ADR_ID_OR_EMPTY = r'^(ADR-\d{3,}|)$'


def _has_line_break(value):
    """값에 줄바꿈 문자가 들어 있는지 돌려준다."""
    return '\n' in value or '\r' in value


class Story(BaseModel):
    """유저스토리 한 개(Who/What/Why/인수조건).

    Attributes:
        title: 짧은 기능명.
        who: 사용자 역할.
        what: 원하는 기능.
        why: 기능이 필요한 목적.
        acceptance: 검증 가능한 인수조건 목록.
    """

    model_config = ConfigDict(extra='forbid')
    title: str = Field(max_length=MAX_TITLE_LENGTH)
    who: str = Field(max_length=MAX_SHORT_TEXT_LENGTH)
    what: str = Field(max_length=MAX_TEXT_LENGTH)
    why: str = Field(max_length=MAX_TEXT_LENGTH)
    acceptance: list[str] = Field(max_length=MAX_ACCEPTANCE_COUNT)

    def find_missing_fields(self):
        """비어 있는 필수 필드 이름 목록을 돌려준다.

        Returns:
            'title', 'who', 'what', 'why', 'acceptance' 중 비어 있는 이름.
        """
        missing = [
            name for name in ('title', 'who', 'what', 'why')
            if not getattr(self, name).strip()
        ]
        has_blank_item = any(not item.strip() for item in self.acceptance)
        if not self.acceptance or has_blank_item:
            missing.append('acceptance')
        return missing

    def text_fields(self):
        """줄바꿈 검사가 필요한 모든 문자열 필드를 돌려준다."""
        return [self.title, self.who, self.what, self.why, *self.acceptance]


class ADRChange(BaseModel):
    """새 아키텍처 결정 기록(ADR) 초안.

    Attributes:
        title: 결정 제목.
        context: 배경.
        decision: 결정 내용.
        alternatives: 검토한 대안.
        consequences: 결과.
        supersedes: 대체하는 기존 ADR ID 또는 빈 문자열.
    """

    model_config = ConfigDict(extra='forbid')
    title: str = Field(max_length=MAX_TITLE_LENGTH)
    context: str = Field(max_length=MAX_TEXT_LENGTH)
    decision: str = Field(max_length=MAX_TEXT_LENGTH)
    alternatives: str = Field(max_length=MAX_TEXT_LENGTH)
    consequences: str = Field(max_length=MAX_TEXT_LENGTH)
    supersedes: str = Field(pattern=ADR_ID_OR_EMPTY)


class Candidate(BaseModel):
    """요구사항 변경 후보(설계의 RequirementCandidate).

    Attributes:
        why_evidence: Why를 뒷받침하는 원문 구절.
        answers_contradict: 사용자 답변끼리 상충하는지 여부(선택 질문 필요).
        action: 'add', 'update', 'delete' 중 하나.
        target_id: 수정·삭제할 Story ID. 추가면 빈 문자열.
        story: 추가·수정할 Story. 삭제면 None.
        evidence: 후보를 만든 입력 근거.
        question: 보완이 필요할 때 사용자에게 할 질문.
        spec_change: Spec 계약 변경 내용.
        adr_change: ADR 변경 초안 또는 None.
    """

    model_config = ConfigDict(extra='forbid')
    why_evidence: str = Field(default='', max_length=MAX_TEXT_LENGTH)
    answers_contradict: bool = False
    action: Literal['add', 'update', 'delete']
    target_id: str = Field(pattern=STORY_ID_OR_EMPTY)
    story: Story | None
    evidence: str = Field(min_length=1, max_length=MAX_EVIDENCE_LENGTH)
    question: str = Field(max_length=MAX_SHORT_TEXT_LENGTH)
    spec_change: str = Field(max_length=MAX_SPEC_LENGTH)
    adr_change: ADRChange | None

    @model_validator(mode='after')
    def check_target(self):
        """필드 사이의 규칙을 검사한다.

        Returns:
            검사를 통과한 자기 자신.

        Raises:
            ValueError: 제목 줄, 줄바꿈, 대상 ID 규칙을 어긴 경우.
        """
        spec_lines = self.spec_change.splitlines()
        if any(line.startswith('#') for line in spec_lines):
            raise ValueError('Spec 변경에는 제목 섹션을 넣지 마세요.')
        if self.adr_change is not None:
            adr_values = self.adr_change.model_dump().values()
            if any(_has_line_break(value) for value in adr_values):
                raise ValueError('ADR 필드는 한 줄이어야 합니다.')
        story_values = self.story.text_fields() if self.story else []
        if any(_has_line_break(value) for value in story_values):
            raise ValueError('Story 필드는 한 줄이어야 합니다.')
        if self.action != 'add' and not self.target_id:
            raise ValueError('수정/삭제할 Story ID가 없습니다.')
        if self.action != 'delete' and self.story is None:
            raise ValueError('추가/수정할 유저스토리가 없습니다.')
        if self.action == 'add' and self.target_id:
            raise ValueError('추가 후보에 기존 ID를 지정할 수 없습니다.')
        return self

    def needs_answer(self):
        """사용자 보완 답변(또는 상충 답변 선택)이 필요한지 돌려준다."""
        if self.answers_contradict:
            return True
        if self.action == 'delete':
            return False
        return bool(self.story.find_missing_fields())


class Analysis(BaseModel):
    """분석 서비스가 돌려주는 후보 묶음.

    Attributes:
        candidates: 요구사항 변경 후보 목록.
    """

    model_config = ConfigDict(extra='forbid')
    candidates: list[Candidate] = Field(max_length=MAX_CANDIDATE_COUNT)


class Conflict(BaseModel):
    """동시에 만족할 수 없는 요구사항 묶음(설계의 Conflict).

    Attributes:
        requirement_ids: 충돌하는 기존 Story ID. 후보 검사면 1개,
            전체 검사면 2개.
        reason: 동시에 만족할 수 없는 이유 한 문장.
    """

    model_config = ConfigDict(extra='forbid')
    requirement_ids: list[str] = Field(min_length=1,
                                       max_length=MAX_CONFLICT_IDS)
    reason: str = Field(min_length=1, max_length=MAX_SHORT_TEXT_LENGTH)


class ConflictReport(BaseModel):
    """충돌 검사 결과.

    Attributes:
        conflicts: 찾은 충돌 목록. 비어 있으면 충돌 없음.
    """

    model_config = ConfigDict(extra='forbid')
    conflicts: list[Conflict] = Field(max_length=MAX_CONFLICT_COUNT)
