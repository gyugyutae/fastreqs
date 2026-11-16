"""요구사항 변경 흐름(수집 -> 분석 -> 충돌 검사 -> 승인 -> 저장) 통합 테스트."""

import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastreqs import documents as doc
from fastreqs.analysis_service import RequirementAnalysisService
from fastreqs.controller import ControllerSettings, RequirementController
from fastreqs.document_repository import RequirementDocumentRepository
from fastreqs.models import ADRChange, Analysis, Candidate, Conflict
from fastreqs.records import KEEP_NEW, CandidateStatus, Decision
from fastreqs.slack_bot import SlackBot
from fastreqs.store import StateStore

FIXTURE = Path(__file__).resolve().parents[1] / 'demo-fixtures/team-search'
BINDING = 'T1/C1'
CHANNEL_SOURCE = 'T1/C1/channel'
REPORT_WHY = '월간 실적 공유 시간을 줄이기 위해서'


def make_candidate(action='add', target='', why=REPORT_WHY):
    """월간 보고서 Story 후보를 만든다."""
    story = None
    if action != 'delete':
        story = {'title': '월간 보고서', 'who': '팀 관리자',
                 'what': '월을 선택하고 보고서를 내려받는다', 'why': why,
                 'acceptance': ['선택한 월의 업무 건수와 완료 건수를 표시한다']}
    return Candidate(action=action, target_id=target, story=story,
                     evidence='회의에서 보고서를 요청했다',
                     question='' if why else '왜 필요한가요?',
                     spec_change='', adr_change=None)


class ScriptedAnalyzer(RequirementAnalysisService):
    """정해 둔 분석 결과와 충돌 결과를 순서대로 돌려준다."""

    def __init__(self, analyses, conflicts=()):
        """분석 결과 목록과 충돌 결과 목록을 받는다."""
        super().__init__(llm_client=None)
        self.analyses = list(analyses)
        self.conflicts = list(conflicts)
        self.calls = []

    def extract_requirements(self, conversation, context, clarification=None):
        """다음 분석 결과를 돌려주거나 예외를 던진다."""
        self.calls.append((conversation, context, clarification))
        value = self.analyses.pop(0)
        if isinstance(value, Exception):
            raise value
        return Analysis(candidates=value)

    def check_conflicts(self, documents, candidate=None):
        """다음 충돌 결과를 돌려준다. 없으면 충돌 없음."""
        return self.conflicts.pop(0) if self.conflicts else []


class FlowTestBase(unittest.TestCase):
    """임시 문서 폴더와 상태 저장소를 준비하는 공통 기반."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / 'documents'
        shutil.copytree(FIXTURE, self.folder)
        self.store = StateStore(self.root / 'state')
        self.store.bind('T1', 'C1', self.folder)
        self.sent = []
        self.settings = ControllerSettings(endings=('수고하셨습니다',),
                                           bot_id='BOT')

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def send(self, channel, text, **options):
        """보낸 메시지를 기록하는 가짜 Slack 전송 함수."""
        self.sent.append((channel, text, options))
        return {'ts': str(len(self.sent))}

    def make_controller(self, analyses=(), conflicts=()):
        """가짜 분석기를 끼운 컨트롤러를 만든다."""
        return RequirementController(
            self.store, ScriptedAnalyzer(analyses, conflicts),
            RequirementDocumentRepository(self.store), SlackBot(self.send),
            self.settings)

    def channel_source(self):
        """채널 입력 경로 레코드를 돌려준다."""
        return self.store.get('source', CHANNEL_SOURCE)

    def propose(self, controller, candidate):
        """현재 문서로 후보를 바로 만든다."""
        with self.store.transaction():
            return controller.create_candidate(
                self.channel_source(), candidate,
                doc.read_documents(self.folder))

    def read(self):
        """현재 문서 내용을 읽는다."""
        return doc.read_documents(self.folder)

    @staticmethod
    def decision(record, user_id='U1'):
        """후보의 현재 버전으로 결정 요청을 만든다."""
        return Decision(BINDING, record.id, record.version, user_id)

    def status_of(self, record):
        """저장된 후보의 현재 상태를 돌려준다."""
        return self.store.get_candidate(record.id).status



class RequirementFlowTest(FlowTestBase):
    """RequirementController가 조정하는 추가·수정·삭제 흐름."""

    def test_joint_patch_preserves_unrelated(self):
        controller = self.make_controller()
        before = self.read()
        record = self.propose(controller, make_candidate())
        result = controller.on_approved(self.decision(record))
        self.assertIn('승인 반영 완료', result)
        after = self.read()
        self.assertIn('US-004', after[doc.USER_STORIES])
        self.assertIn('US-004', after[doc.PRD])
        self.assertEqual(before[doc.ADR], after[doc.ADR])
        self.assertEqual(before[doc.SPEC], after[doc.SPEC])
        old_sections = doc.parse_sections(before[doc.USER_STORIES])
        new_sections = doc.parse_sections(after[doc.USER_STORIES])
        for story_id, body in old_sections.items():
            self.assertEqual(body, new_sections[story_id])
        self.assertIn('## 제외 범위\n음성 검색, 외부 서비스 연동.',
                      after[doc.PRD])
        again = controller.on_approved(self.decision(record, 'U2'))
        self.assertIn('이미 처리', again)

    def test_reject_never_writes(self):
        controller = self.make_controller()
        before = self.read()
        record = self.propose(controller, make_candidate())
        controller.on_rejected(self.decision(record))
        self.assertEqual(before, self.read())
        self.assertFalse(controller.pending_candidates(CHANNEL_SOURCE))

    def test_manual_edit_requires_new_approval(self):
        controller = self.make_controller()
        record = self.propose(controller, make_candidate())
        prd = self.folder / doc.PRD
        original = prd.read_text(encoding='utf-8')
        prd.write_text(original + '\n수동 메모\n', encoding='utf-8',
                       newline='')
        result = controller.on_approved(self.decision(record))
        self.assertIn('다시 승인', result)
        self.assertNotIn('US-004', self.read()[doc.USER_STORIES])
        fresh = controller.pending_candidates(CHANNEL_SOURCE)[0]
        controller.on_approved(self.decision(fresh))
        self.assertIn('수동 메모', self.read()[doc.PRD])

    def test_joint_failure_rolls_back(self):
        controller = self.make_controller()
        record = self.propose(controller, make_candidate())
        before = self.read()
        original = doc.atomic_write

        def failing(path, content):
            if Path(path).name == doc.PRD:
                raise OSError('disk')
            original(path, content)

        with patch('fastreqs.documents.atomic_write', side_effect=failing):
            result = controller.on_approved(self.decision(record))
        self.assertIn('저장 실패', result)
        self.assertEqual(before, self.read())
        self.assertEqual(CandidateStatus.PENDING, self.status_of(record))

    def test_delete_then_separate_spec(self):
        controller = self.make_controller()
        record = self.propose(controller, make_candidate('delete', 'US-002'))
        before = self.read()
        controller.on_approved(self.decision(record))
        after = self.read()
        self.assertNotIn('US-002', after[doc.USER_STORIES])
        self.assertEqual(before[doc.SPEC], after[doc.SPEC])
        tech = self.store.find_candidates(kind=doc.KIND_SPEC)[0]
        controller.on_approved(self.decision(tech, 'U2'))
        spec = self.read()[doc.SPEC]
        self.assertNotIn('US-002', doc.parse_sections(spec))
        self.assertEqual(before[doc.ADR], self.read()[doc.ADR])
        self.assertTrue(any('US-002 제외 완료' in text
                            for _, text, _ in self.sent))

    def test_failure_preserves_cursor_and_candidates(self):
        controller = self.make_controller([RuntimeError('offline')])
        record = self.propose(controller, make_candidate())
        self.store.add_event(CHANNEL_SOURCE, '1', 'U1', '새 요구사항')
        controller.start_analysis(CHANNEL_SOURCE)
        self.assertEqual(0, self.channel_source()['cursor'])
        self.assertEqual(CandidateStatus.PENDING, self.status_of(record))
        self.assertFalse(self.channel_source()['busy'])

    def test_file_isolation_duplicate_and_clarification(self):
        controller = self.make_controller(
            [[make_candidate(why='')], [make_candidate()]])
        controller.collect_chat('T1', {'channel': 'C1', 'user': 'U1',
                                       'ts': '1', 'text': '일반 채널 대화'})
        upload = {'channel': 'C1', 'user': 'U1', 'ts': '2',
                  'subtype': 'file_share',
                  'files': [{'id': 'F1', 'name': 'meeting.md', 'size': 20}]}
        controller.collect_chat('T1', upload, lambda _: '월간 보고서 요청')
        controller.collect_chat('T1', {**upload, 'ts': '3'},
                                lambda _: '월간 보고서 요청')
        self.assertEqual(2, len(self.store.find_all('source')))
        controller.collect_chat('T1', {'channel': 'C1', 'user': 'U1',
                                       'ts': '4', 'thread_ts': '2',
                                       'text': '<@BOT> 분석해줘'})
        question = self.store.find_candidates()[0]
        self.assertEqual(CandidateStatus.CLARIFYING, question.status)
        controller.collect_chat('T1', {'channel': 'C1', 'user': 'U2',
                                       'ts': '5', 'thread_ts': question.thread,
                                       'text': '월간 공유 시간을 줄이려고요'})
        self.assertEqual(CandidateStatus.REPLACED, self.status_of(question))
        self.assertEqual(0, self.channel_source()['cursor'])
        self.assertNotIn('일반 채널 대화', str(controller.analyzer.calls))

    def test_busy_decision_and_followup(self):
        controller = self.make_controller()
        record = self.propose(controller, make_candidate())
        with self.store.transaction():
            source = self.channel_source()
            source['busy'] = True
            self.store.put('source', source)
        result = controller.on_approved(self.decision(record))
        self.assertIn('새 제안을 확인', result)
        controller.start_analysis(CHANNEL_SOURCE)
        self.assertTrue(self.channel_source()['followup'])

    def test_restart_preserves_candidates(self):
        controller = self.make_controller()
        record = self.propose(controller, make_candidate())
        self.store.close()
        self.store = StateStore(self.root / 'state')
        self.assertEqual(record, self.store.get_candidate(record.id))

    def test_followup_uses_new_range_and_pending(self):
        controller = self.make_controller()
        test = self

        class Followup(RequirementAnalysisService):
            count = 0

            def __init__(self):
                super().__init__(llm_client=None)

            def extract_requirements(self, conversation, context,
                                     clarification=None):
                self.count += 1
                if self.count == 1:
                    test.store.add_event(CHANNEL_SOURCE, 'next', 'U2',
                                         '새 추가 근거')
                    controller.start_analysis(CHANNEL_SOURCE)
                else:
                    texts = [event['text'] for event in conversation]
                    test.assertEqual(['새 추가 근거'], texts)
                    test.assertEqual(1, len(context['pending']))
                return Analysis(candidates=[make_candidate()])

            def check_conflicts(self, documents, candidate=None):
                return []

        controller.analyzer = Followup()
        self.store.add_event(CHANNEL_SOURCE, 'first', 'U1', '월간 보고서 필요')
        controller.start_analysis(CHANNEL_SOURCE)
        self.assertEqual(2, controller.analyzer.count)
        self.assertEqual(2, self.channel_source()['cursor'])
        self.assertEqual(1, len(controller.pending_candidates(CHANNEL_SOURCE)))

    def test_contradicting_answers_block_approval(self):
        controller = self.make_controller()
        contradicted = Candidate.model_validate({
            **make_candidate().model_dump(), 'answers_contradict': True,
            'question': '목적이 다릅니다. 어떤 답인가요?'})
        record = self.propose(controller, contradicted)
        self.assertEqual(CandidateStatus.CLARIFYING, record.status)
        before = self.read()
        controller.on_approved(self.decision(record))
        self.assertEqual(before, self.read())

    def test_adr_append_preserves_previous_reason(self):
        controller = self.make_controller()
        candidate = make_candidate('update', 'US-003')
        candidate.adr_change = ADRChange(
            title='새 정책', context='정책 변경 합의', decision='새 정책 적용',
            alternatives='기존 유지', consequences='권한 변경',
            supersedes='ADR-001')
        record = self.propose(controller, candidate)
        before = self.read()
        controller.on_approved(self.decision(record))
        self.assertEqual(before[doc.ADR], self.read()[doc.ADR])
        tech = self.store.find_candidates(kind=doc.KIND_ADR)[0]
        controller.on_approved(self.decision(tech, 'U2'))
        text = self.read()[doc.ADR]
        self.assertIn('ADR-002', text)
        self.assertIn('- 상태: Superseded', text)
        self.assertIn('초기에는 관리자가 주간 공유 자료를 만든다.', text)

    def test_superseding_inactive_adr_is_rejected(self):
        controller = self.make_controller()
        candidate = make_candidate('update', 'US-001')
        candidate.adr_change = ADRChange(
            title='t', context='c', decision='d', alternatives='a',
            consequences='r', supersedes='ADR-099')
        with self.assertRaises(ValueError):
            self.propose(controller, candidate)

    def test_first_concurrent_decision_wins(self):
        controller = self.make_controller()
        record = self.propose(controller, make_candidate())
        results = []

        def approve(user_id):
            results.append(controller.on_approved(
                self.decision(record, user_id)))

        workers = [threading.Thread(target=approve, args=(user_id,))
                   for user_id in ('U1', 'U2')]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual(1, sum(result.startswith('승인 반영 완료')
                                for result in results))
        self.assertEqual(1, len(self.store.find_all('operation')))

    def test_restart_identifies_partial_files(self):
        controller = self.make_controller()
        record = self.propose(controller, make_candidate())
        operation = {'id': 'partial', 'binding': BINDING,
                     'candidate': record.id, 'state': 'prepared',
                     'before': self.read(), 'after': record.plan,
                     'actor': 'U1', 'time': '2026-10-11'}
        with self.store.transaction():
            self.store.put('operation', operation)
            record.status = CandidateStatus.APPLYING
            self.store.put_candidate(record)
        doc.atomic_write(self.folder / doc.USER_STORIES,
                         record.plan[doc.USER_STORIES])
        controller.recover_pending_operations()
        state = self.store.get('operation', 'partial')['state']
        self.assertEqual('recovery_required', state)
        self.assertEqual(CandidateStatus.APPLY_FAILED, self.status_of(record))

    def test_path_and_schema_protection(self):
        with self.assertRaises(ValueError):
            self.store.bind('T1', 'C2', self.folder)
        story = {**make_candidate().story.model_dump(),
                 'title': 'x\n## US-999 injected'}
        with self.assertRaises(ValueError):
            Candidate.model_validate({**make_candidate().model_dump(),
                                      'story': story})


class ConflictFlowTest(FlowTestBase):
    """요구사항 충돌: 선택 질문 후 고른 하나만 남긴다(UC-01, UC-03)."""

    CONFLICT = Conflict(requirement_ids=['US-003'],
                        reason='CSV 내보내기와 동시에 만족할 수 없다')

    def analyze_conflicting_candidate(self):
        """US-003과 충돌하는 추가 후보를 분석으로 만든다."""
        controller = self.make_controller([[make_candidate()]],
                                          [[self.CONFLICT]])
        controller.collect_chat('T1', {'channel': 'C1', 'user': 'U1',
                                       'ts': '1', 'text': '<@BOT> 분석해줘'})
        return controller, self.store.find_candidates()[0]

    def test_conflict_asks_choice_instead_of_approval(self):
        _, record = self.analyze_conflicting_candidate()
        self.assertEqual(CandidateStatus.CONFLICTED, record.status)
        self.assertEqual(['US-003'], record.conflict_ids)
        buttons = self.sent[-1][2]['blocks'][-1]['elements']
        values = [button['value'].rsplit(':', 1)[1] for button in buttons]
        self.assertEqual(['US-003', KEEP_NEW], values)

    def test_keep_existing_rejects_new(self):
        controller, record = self.analyze_conflicting_candidate()
        before = self.read()
        result = controller.on_selected(self.decision(record), 'US-003')
        self.assertIn('기존 요구사항을 유지', result)
        self.assertEqual(before, self.read())
        self.assertEqual(CandidateStatus.REJECTED, self.status_of(record))

    def test_keep_new_removes_existing(self):
        controller, record = self.analyze_conflicting_candidate()
        result = controller.on_selected(self.decision(record), KEEP_NEW)
        self.assertIn('승인 반영 완료', result)
        stories = doc.parse_sections(self.read()[doc.USER_STORIES])
        self.assertIn(record.target, stories)
        self.assertNotIn('US-003', stories)
        self.assertNotIn('| US-003 |', self.read()[doc.PRD])
        spec = self.store.find_candidates(kind=doc.KIND_SPEC)[0]
        self.assertEqual('US-003', spec.target)

    def test_approve_button_cannot_skip_choice(self):
        controller, record = self.analyze_conflicting_candidate()
        before = self.read()
        result = controller.on_approved(self.decision(record))
        self.assertIn('이미 처리되었거나', result)
        self.assertEqual(before, self.read())

    def test_full_scan_keeps_selected_story(self):
        pair = Conflict(requirement_ids=['US-001', 'US-003'],
                        reason='두 요구사항을 동시에 만족할 수 없다')
        controller = self.make_controller(conflicts=[[pair]])
        controller.collect_chat('T1', {'channel': 'C1', 'user': 'U1',
                                       'ts': '1', 'text': '<@BOT> 충돌 확인'})
        record = self.store.find_candidates(kind='conflict')[0]
        controller.on_selected(self.decision(record), 'US-001')
        stories = doc.parse_sections(self.read()[doc.USER_STORIES])
        self.assertIn('US-001', stories)
        self.assertNotIn('US-003', stories)

    def test_full_scan_without_conflict(self):
        controller = self.make_controller()
        controller.check_all_conflicts(BINDING)
        self.assertEqual('요구사항 충돌이 없습니다.', self.sent[-1][1])

    def test_missing_target_shows_not_found(self):
        controller = self.make_controller(
            [[make_candidate('update', 'US-999')]])
        before = self.read()
        controller.collect_chat('T1', {'channel': 'C1', 'user': 'U1',
                                       'ts': '1', 'text': '<@BOT> 분석해줘'})
        self.assertEqual(before, self.read())
        self.assertFalse(self.store.find_candidates())
        self.assertTrue(any('US-999 요구사항을 문서에서 찾지' in text
                            for _, text, _ in self.sent))


if __name__ == '__main__':
    unittest.main()
