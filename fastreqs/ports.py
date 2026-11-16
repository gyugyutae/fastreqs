"""계층 사이의 추상 인터페이스(포트).

컨트롤러는 구체 클래스(Slack, OpenRouter)가 아니라 이 인터페이스에만
의존한다(의존관계 역전). 인터페이스는 쓰는 쪽이 필요한 메서드만 갖도록
작게 나눴다(인터페이스 분리).
"""

from typing import Protocol


class LlmClient(Protocol):
    """구조화 JSON을 돌려주는 언어 모델 클라이언트."""

    def complete(self, system_prompt, user_content, schema):
        """프롬프트를 보내고 모델이 만든 JSON 문자열을 돌려준다."""


class RequirementAnalyzer(Protocol):
    """후보 추출과 충돌 검사(설계의 RequirementAnalysisService)."""

    def extract_requirements(self, conversation, context, clarification=None):
        """새 대화에서 요구사항 후보를 추출해 Analysis로 돌려준다."""

    def check_conflicts(self, documents, candidate=None):
        """요구사항 충돌(Conflict) 목록을 돌려준다(충돌 검사의 유일한 위치)."""


class RequirementView(Protocol):
    """사용자에게 제안과 결과를 보여주는 화면(설계의 SlackBot)."""

    def notify(self, channel_id, text, thread=None):
        """일반 안내 메시지를 보낸다."""

    def propose_change(self, channel_id, candidate, thread=None):
        """proposeChange: 승인·거절 버튼이 있는 변경 제안을 보인다."""

    def ask_question(self, channel_id, candidate, thread=None):
        """askQuestion: 보완 질문을 보이고 메시지 ts를 돌려준다."""

    def ask_conflict_choice(self, channel_id, candidate, thread=None):
        """askConflictChoice: 충돌 요구사항 중 하나를 고르게 한다."""

    def show_added(self, channel_id, candidate, thread=None):
        """showAdded: 추가·수정 완료를 알린다."""

    def show_removed(self, channel_id, requirement_id, thread=None):
        """showRemoved: 요구사항 제외 완료를 알린다."""

    def show_not_found(self, channel_id, requirement_id, thread=None):
        """showNotFound: 대상 요구사항이 없음을 알린다."""

    def show_no_conflict(self, channel_id):
        """showNoConflict: 충돌이 없음을 알린다."""

    def show_error(self, channel_id, source_id, detail, thread=None):
        """showError: 분석 실패를 [다시 분석] 버튼과 함께 알린다."""
