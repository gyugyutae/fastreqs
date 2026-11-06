from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Story(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(max_length=200)
    who: str = Field(max_length=1000)
    what: str = Field(max_length=2000)
    why: str = Field(max_length=2000)
    acceptance: list[str] = Field(max_length=10)

    def missing(self):
        fields = [name for name in ('title', 'who', 'what', 'why') if not getattr(self, name).strip()]
        if not self.acceptance or any(not x.strip() for x in self.acceptance):
            fields.append('acceptance')
        return fields

class ADRChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(max_length=200)
    context: str = Field(max_length=2000)
    decision: str = Field(max_length=2000)
    alternatives: str = Field(max_length=2000)
    consequences: str = Field(max_length=2000)
    supersedes: str = Field(pattern=r'^(ADR-\d{3,}|)$')

class Candidate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    why_evidence: str = Field(default='',max_length=2000)
    conflicted: bool = False
    action: Literal['add', 'update', 'delete']
    target_id: str = Field(pattern=r'^(US-\d{3,}|)$')
    story: Story | None
    evidence: str = Field(min_length=1,max_length=1500)
    question: str = Field(max_length=1000)
    spec_change: str = Field(max_length=6000)
    adr_change: ADRChange | None

    @model_validator(mode='after')
    def check_target(self):
        if any(line.startswith('#') for line in self.spec_change.splitlines()):
            raise ValueError('Spec 변경에는 제목 섹션을 넣지 마세요.')
        if self.adr_change and any('\n' in x or '\r' in x for x in self.adr_change.model_dump().values()):
            raise ValueError('ADR 필드는 한 줄이어야 합니다.')
        values = ([self.story.title, self.story.who, self.story.what, self.story.why, *self.story.acceptance] if self.story else [])
        if any('\n' in x or '\r' in x for x in values):
            raise ValueError('Story 필드는 한 줄이어야 합니다.')
        if self.action != 'add' and not self.target_id:
            raise ValueError('수정/삭제할 Story ID가 없습니다.')
        if self.action != 'delete' and self.story is None:
            raise ValueError('추가/수정할 유저스토리가 없습니다.')
        if self.action == 'add' and self.target_id:
            raise ValueError('추가 후보에 기존 ID를 지정할 수 없습니다.')
        return self

    def needs_answer(self):
        return self.action != 'delete' and bool(self.story.missing())

class Analysis(BaseModel):
    model_config = ConfigDict(extra='forbid')
    candidates: list[Candidate] = Field(max_length=8)
