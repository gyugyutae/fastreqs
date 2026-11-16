"""컨트롤러 부품이 함께 쓰는 협력 객체와 도우미.

RequirementController는 ChatCollector, AnalysisRunner, ApprovalProcessor로
나뉜다. 세 부품은 이 ControllerContext 하나로 저장소·분석 서비스·문서
리포지토리·화면에 접근한다.
"""

import threading
from dataclasses import dataclass

from . import documents as doc
from .records import CandidateStatus


@dataclass(frozen=True)
class ControllerSettings:
    """컨트롤러 동작 설정.

    Attributes:
        endings: 분석을 시작하는 종료 키워드 목록.
        bot_id: 멘션 판별에 쓰는 봇 사용자 ID.
    """

    endings: tuple
    bot_id: str


class ControllerContext:
    """컨트롤러 부품이 공유하는 의존 객체와 채널 잠금.

    Attributes:
        store: 대화·후보·작업 상태 저장소(StateStore).
        analyzer: 후보 추출·충돌 검사(RequirementAnalyzer).
        repository: 요구사항 문서 읽기·저장(RequirementDocumentRepository).
        view: 사용자 화면(RequirementView).
        settings: 종료 키워드와 봇 ID(ControllerSettings).
    """

    def __init__(self, store, analyzer, repository, view, settings):
        """협력 객체를 주입받는다."""
        self.store = store
        self.analyzer = analyzer
        self.repository = repository
        self.view = view
        self.settings = settings
        self._guard = threading.RLock()
        self._binding_locks = {}

    def binding_lock(self, binding_id):
        """채널마다 하나인 반영 잠금을 돌려준다."""
        with self._guard:
            return self._binding_locks.setdefault(
                binding_id, threading.RLock())

    def channel_of(self, binding_id):
        """채널 연결 ID의 Slack 채널 ID를 돌려준다."""
        return self.store.get('binding', binding_id)['channel']

    def notify_source(self, source, text):
        """입력 경로(채널 또는 회의록 스레드)에 안내 메시지를 보낸다."""
        self.view.notify(self.channel_of(source['binding']), text,
                         thread=source['thread'])

    def pending_candidates(self, source_id):
        """입력 경로의 미결 Story 후보 목록을 돌려준다."""
        return [record for record in
                self.store.find_candidates(source=source_id)
                if record.is_active and record.kind == doc.KIND_STORY]

    def put_impact(self, binding_id, story_id, kind, status):
        """기술 문서 영향(갱신 검토 필요 여부)을 기록한다."""
        self.store.put('impact', {
            'id': f'{binding_id}:{kind}:{story_id}', 'binding': binding_id,
            'target': story_id, 'kind': kind, 'status': status})

    def present_candidate(self, record):
        """후보를 상태에 맞는 화면(질문·충돌 선택·승인 제안)으로 보인다.

        게시한 메시지 위치(스레드, ts)를 후보에 저장한다.
        """
        channel_id = self.channel_of(record.binding)
        if record.status == CandidateStatus.CONFLICTED:
            ts = self.view.ask_conflict_choice(channel_id, record,
                                               record.thread)
        elif record.status == CandidateStatus.CLARIFYING:
            ts = self.view.ask_question(channel_id, record, record.thread)
        else:
            ts = self.view.propose_change(channel_id, record, record.thread)
        with self.store.transaction():
            current = self.store.get_candidate(record.id)
            current.thread = record.thread or ts
            current.message = ts
            self.store.put_candidate(current)
