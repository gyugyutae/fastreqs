"""오프라인 모의 데모. Slack 연결이나 모델 호출 없이 정해진 응답을 쓴다.

시나리오: 회의록 추가(보완 질문) -> 다크 모드 제외 -> Spec 별도 승인 ->
기존 요구사항과 충돌하는 새 요구 선택(UC-01 충돌) -> 전체 충돌 확인(UC-03).

사용 예:
    python -m fastreqs replay
"""

import shutil
import tempfile
from pathlib import Path

from .analysis_service import RequirementAnalysisService
from .config import ROOT
from .controller import ControllerSettings, RequirementController
from .document_repository import RequirementDocumentRepository
from .documents import ADR, SPEC, USER_STORIES, read_documents
from .models import Analysis, Candidate, Conflict
from .records import KEEP_NEW, CandidateStatus, Decision
from .slack_bot import SlackBot
from .store import StateStore

FIXTURE_FOLDER = ROOT / 'demo-fixtures' / 'team-search'
MEETING_FILE = (ROOT / 'demo-fixtures' / 'meeting-inputs'
                / '01-monthly-report.md')
WORKSPACE_ID = 'DEMO'
CHANNEL_ID = 'CDEMO'
BINDING_ID = f'{WORKSPACE_ID}/{CHANNEL_ID}'
FIRST_STEP = 1
DELETE_STEP = 3
EXPORT_BLOCK_STEP = 4
MONTHLY_REPORT_WHY = '월간 실적 공유 시간을 줄이기 위해서'
REPORT_WHAT = '월을 선택하고 업무 건수와 완료 건수를 내려받는다'
REPORT_ACCEPTANCE = '선택한 월의 업무 건수와 완료 건수가 포함된다'
DARK_MODE_DECISION = '다크 모드는 삭제하는 것으로 정하겠습니다.'
EXPORT_BLOCK_REQUEST = ('<@BOT> 분석해줘. 보안 사고를 막기 위해서 업무 목록 '
                        '파일 내려받기는 모두 막아야 합니다.')
EXPORT_BLOCK_TITLE = '파일 내려받기 차단'
EXPORT_CONFLICT = Conflict(
    requirement_ids=['US-003'],
    reason='CSV 내보내기와 파일 내려받기 차단은 동시에 만족할 수 없다.')


class ScriptedAnalyzer(RequirementAnalysisService):
    """미리 정한 순서대로 후보를 돌려주는 가짜 분석 서비스.

    충돌 검사는 실제 서비스의 규칙을 그대로 쓴다(리스코프 치환).

    Attributes:
        step: 지금까지 호출된 횟수.
    """

    def __init__(self):
        """LLM 없이 시작한다."""
        super().__init__(llm_client=None)
        self.step = 0

    def extract_requirements(self, conversation, context, clarification=None):
        """호출 순서에 맞는 후보를 돌려준다."""
        self.step += 1
        if self.step == DELETE_STEP:
            candidate = Candidate(
                action='delete', target_id='US-002', story=None,
                evidence='다크 모드는 삭제하기로 정했습니다', question='',
                spec_change='', adr_change=None)
        elif self.step == EXPORT_BLOCK_STEP:
            candidate = Candidate(
                action='add', target_id='',
                story={'title': EXPORT_BLOCK_TITLE, 'who': '팀 관리자',
                       'what': '업무 목록 파일 내려받기를 막는다',
                       'why': '보안 사고를 막기 위해서',
                       'acceptance': ['파일 내려받기 버튼을 표시하지 않는다']},
                evidence='업무 목록 파일 내려받기는 모두 막아야 합니다',
                question='', spec_change='', adr_change=None)
        else:
            why = '' if self.step == FIRST_STEP else MONTHLY_REPORT_WHY
            candidate = Candidate(
                action='add', target_id='',
                story={'title': '월간 보고서', 'who': '팀 관리자',
                       'what': REPORT_WHAT, 'why': why,
                       'acceptance': [REPORT_ACCEPTANCE]},
                evidence='관리자가 월간 보고서를 내려받을 수 있어야 합니다',
                question='월간 보고서가 필요한 목적은 무엇인가요?',
                spec_change='', adr_change=None)
        return Analysis(candidates=[candidate])

    def check_conflicts(self, documents, candidate=None):
        """파일 내려받기 차단 후보만 US-003과 충돌한다고 돌려준다."""
        if candidate and candidate.story.title == EXPORT_BLOCK_TITLE:
            return [EXPORT_CONFLICT]
        return []


def _first_open(store, kind=None, status=CandidateStatus.PENDING):
    """조건에 맞는 첫 미결 후보를 돌려준다."""
    filters = {'status': status.value}
    if kind:
        filters['kind'] = kind
    return store.find_candidates(**filters)[0]


def _decision(record, user_id):
    """후보의 현재 버전으로 결정 요청을 만든다."""
    return Decision(BINDING_ID, record.id, record.version, user_id)


def _print_and_send(sent):
    """보낸 메시지를 화면에 찍는 가짜 전송 함수를 만든다."""
    def send(channel, text, **options):
        sent.append(text)
        print('\n' + text)
        return {'ts': str(len(sent))}
    return send


def _chat(controller, ts, text, **extra):
    """채널 대화 한 줄을 컨트롤러에 넣는다."""
    controller.collect_chat(WORKSPACE_ID, {
        'channel': CHANNEL_ID, 'user': 'U1', 'ts': ts, 'text': text,
        **extra})


def _play_meeting_file(controller, store):
    """시나리오 1: 회의록 업로드 -> 보완 질문 -> 답변 -> 승인."""
    upload = {'channel': CHANNEL_ID, 'user': 'U1', 'ts': 'upload',
              'files': [{'id': 'F1', 'name': 'meeting.md', 'size': 100}]}
    controller.collect_chat(WORKSPACE_ID, upload,
                            lambda _: MEETING_FILE.read_text())
    _chat(controller, 'request', '<@BOT> 분석해줘', thread_ts='upload')
    question = store.find_candidates()[0]
    _chat(controller, 'answer', MONTHLY_REPORT_WHY + '입니다.',
          thread_ts=question.thread)
    story = _first_open(store)
    print(controller.on_approved(_decision(story, 'U1')))


def _play_removal(controller, store):
    """시나리오 2: 다크 모드 제외 -> Story 승인 -> Spec 별도 승인."""
    _chat(controller, 'discussion', DARK_MODE_DECISION)
    _chat(controller, 'ending', '수고하셨습니다')
    for kind in ('story', 'spec'):
        record = _first_open(store, kind)
        print(controller.on_approved(_decision(record, 'U2')))


def _play_conflict(controller, store):
    """시나리오 3: 기존 US-003과 충돌하는 새 요구 -> 새 요구 선택."""
    _chat(controller, 'block-export', EXPORT_BLOCK_REQUEST)
    conflicted = _first_open(store, status=CandidateStatus.CONFLICTED)
    print(controller.on_selected(_decision(conflicted, 'U1'), KEEP_NEW))
    spec = _first_open(store, 'spec')
    print(controller.on_approved(_decision(spec, 'U2')))
    _chat(controller, 'scan', '<@BOT> 충돌 확인')


def replay():
    """임시 폴더에서 모의 데모를 실행하고 결과 문서를 검증한다."""
    print('OFFLINE MOCK: Slack/무료 모델 실제 작동 검증이 아닙니다.')
    with tempfile.TemporaryDirectory(prefix='fastreqs-replay-') as temp:
        root = Path(temp)
        folder = root / 'documents'
        shutil.copytree(FIXTURE_FOLDER, folder)
        store = StateStore(root / 'state')
        store.bind(WORKSPACE_ID, CHANNEL_ID, folder)
        settings = ControllerSettings(endings=('수고하셨습니다',),
                                      bot_id='BOT')
        controller = RequirementController(
            store, ScriptedAnalyzer(), RequirementDocumentRepository(store),
            SlackBot(_print_and_send([])), settings)
        _play_meeting_file(controller, store)
        _play_removal(controller, store)
        _play_conflict(controller, store)
        result = read_documents(folder)
        assert '월간 보고서' in result[USER_STORIES]
        assert EXPORT_BLOCK_TITLE in result[USER_STORIES]
        for removed in ('US-002', 'US-003'):
            assert removed not in result[USER_STORIES]
            assert removed not in result[SPEC]
        assert 'ADR-001' in result[ADR]
        print('\n모의 데모 완료: 보완→공동 승인→제외→Spec 별도 승인→'
              '충돌 선택→전체 충돌 확인. 임시 문서는 종료 시 삭제됩니다.')
        store.close()
