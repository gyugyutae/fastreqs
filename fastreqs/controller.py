"""요구사항 컨트롤러(설계의 RequirementController, «Controller»).

설계 오퍼레이션과의 대응(설계 camelCase -> 코드 snake_case):
    collectChat(channelId, content)        -> collect_chat()
    startAnalysis(channelId, trigger)      -> start_analysis()
    onApproved(candidateId, userId)        -> on_approved()
    onRejected(candidateId, userId)        -> on_rejected()
    onSelected(conflictId, keepId, userId) -> on_selected()
    checkAllConflicts(channelId)           -> check_all_conflicts()

컨트롤러는 유스케이스 순서만 조정하고, 실제 일은 세 부품에 나눠 맡긴다.
    ChatCollector     대화 수집과 시작 조건 판별
    AnalysisRunner    분석 실행, 충돌 검사 요청, 후보 저장
    ApprovalProcessor 승인·거절·충돌 선택, 저장, 재시작 복구

사용 예:
    settings = ControllerSettings(endings=config.endings, bot_id=bot_id)
    controller = RequirementController(store, analyzer, repository, view,
                                       settings)
    controller.collect_chat(workspace_id, slack_event)
"""

from .analysis_runner import AnalysisRunner
from .approval_processor import ApprovalProcessor
from .chat_collector import ChatCollector
from .controller_context import ControllerContext, ControllerSettings

__all__ = ['ControllerSettings', 'RequirementController']


class RequirementController:
    """대화 수집부터 승인·저장까지 요구사항 변경 흐름을 조정한다.

    Attributes:
        context: 부품이 공유하는 협력 객체(ControllerContext).
        collector: 대화 수집 부품.
        runner: 분석 실행 부품.
        processor: 결정 처리 부품.
    """

    def __init__(self, store, analyzer, repository, view, settings):
        """협력 객체를 주입받아 세 부품을 조립한다.

        Args:
            store: 상태 저장소(StateStore).
            analyzer: 분석 서비스(RequirementAnalyzer).
            repository: 문서 리포지토리(RequirementDocumentRepository).
            view: 화면(RequirementView).
            settings: 종료 키워드와 봇 ID(ControllerSettings).
        """
        self.context = ControllerContext(store, analyzer, repository, view,
                                         settings)
        self.runner = AnalysisRunner(self.context)
        self.processor = ApprovalProcessor(self.context,
                                           self.runner.create_candidate)
        self.collector = ChatCollector(self.context, self.start_analysis,
                                       self.check_all_conflicts)

    @property
    def store(self):
        """상태 저장소."""
        return self.context.store

    @property
    def analyzer(self):
        """분석 서비스(테스트에서 바꿔 끼울 수 있다)."""
        return self.context.analyzer

    @analyzer.setter
    def analyzer(self, value):
        self.context.analyzer = value

    # ----- 설계 오퍼레이션 -----

    def collect_chat(self, workspace_id, event, download=None):
        """collectChat: Slack 메시지를 저장하고 시작 조건이면 처리를 시작한다.

        Args:
            workspace_id: Slack 워크스페이스 ID.
            event: Slack message 이벤트 딕셔너리.
            download: 첨부 파일을 문자열로 내려받는 함수.
        """
        self.collector.collect(workspace_id, event, download)

    def start_analysis(self, source_id, correction=None):
        """startAnalysis: 입력 경로의 새 대화를 분석해 후보를 제안한다.

        Args:
            source_id: 입력 경로 ID.
            correction: 보완·정정할 후보 정보. 일반 분석이면 None.
        """
        self.runner.start(source_id, correction)

    def on_approved(self, decision):
        """onApproved: 승인된 후보를 문서에 저장한다.

        Args:
            decision: 결정 요청(Decision).

        Returns:
            사용자에게 보여줄 결과 메시지.
        """
        return self.processor.approve(decision)

    def on_rejected(self, decision):
        """onRejected: 후보를 거절한다. 문서는 바꾸지 않는다.

        Returns:
            사용자에게 보여줄 결과 메시지.
        """
        return self.processor.reject(decision)

    def on_selected(self, decision, keep):
        """onSelected: 충돌한 요구사항 중 고른 하나만 남긴다.

        Args:
            decision: 결정 요청(Decision).
            keep: 살릴 기존 Story ID, 또는 새 후보를 살리면 'new'.

        Returns:
            사용자에게 보여줄 결과 메시지.
        """
        return self.processor.select(decision, keep)

    def check_all_conflicts(self, binding_id):
        """checkAllConflicts: 채널 문서 전체의 요구사항 충돌을 확인한다."""
        self.runner.check_all_conflicts(binding_id)

    # ----- 운영 보조 -----

    def retry_analysis(self, binding_id, source_id):
        """[다시 분석] 버튼 요청을 처리한다."""
        self.runner.retry(binding_id, source_id)

    def create_candidate(self, source, candidate, documents, options=None):
        """분석 결과 하나로 후보 레코드를 만든다(트랜잭션 안에서 호출)."""
        return self.runner.create_candidate(source, candidate, documents,
                                            options)

    def pending_candidates(self, source_id):
        """입력 경로의 미결 Story 후보 목록을 돌려준다."""
        return self.context.pending_candidates(source_id)

    def resume_open_candidates(self):
        """재시작 후 아직 결정되지 않은 후보를 다시 보여준다."""
        for record in self.store.find_candidates():
            if record.is_active:
                self.context.present_candidate(record)

    def recover_pending_operations(self):
        """재시작 시 끝나지 않은 저장 작업을 판별한다."""
        self.processor.recover()
