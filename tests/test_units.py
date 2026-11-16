"""리팩토링으로 분리한 단위(함수·클래스)의 단위 테스트."""

import shutil
import tempfile
import unittest
from pathlib import Path

from fastreqs import documents as doc
from fastreqs.analysis_service import RequirementAnalysisService
from fastreqs.config import Config
from fastreqs.models import Candidate
from fastreqs.records import CandidateRecord, CandidateStatus
from fastreqs.slack_bot import MAX_BLOCKS, SlackBot
from fastreqs.store import StateStore

FIXTURE = Path(__file__).resolve().parents[1] / 'demo-fixtures/team-search'
STORY = {'title': '월간 보고서', 'who': '팀 관리자', 'what': '보고서를 받는다',
         'why': '공유 시간을 줄이기 위해',
         'acceptance': ['월별 건수를 표시한다']}


def make_candidate(action='add', target_id=''):
    """테스트용 후보를 만든다."""
    story = None if action == 'delete' else STORY
    return Candidate(action=action, target_id=target_id, story=story,
                     evidence='근거', question='', spec_change='',
                     adr_change=None)


class DocumentsTest(unittest.TestCase):
    """documents 모듈(RequirementDocument)의 순수 함수."""

    def setUp(self):
        self.documents = doc.read_documents(FIXTURE)

    def test_parse_sections_finds_story_ids(self):
        sections = doc.parse_sections(self.documents[doc.USER_STORIES])
        self.assertEqual(['US-001', 'US-002', 'US-003'], list(sections))

    def test_parse_sections_rejects_duplicate_id(self):
        text = '# t\n## US-001 a\n본문\n## US-001 b\n본문\n'
        with self.assertRaises(ValueError):
            doc.parse_sections(text)

    def test_add_story_patch_updates_story_and_prd(self):
        payload = make_candidate().model_dump()
        patch = doc.build_patch(self.documents, payload, 'US-004')
        self.assertEqual({doc.USER_STORIES, doc.PRD}, set(patch))
        self.assertIn('## US-004 월간 보고서', patch[doc.USER_STORIES])
        self.assertIn('| US-004 | 월간 보고서 — 보고서를 받는다 | 보통 |',
                      patch[doc.PRD])

    def test_update_keeps_existing_priority(self):
        prd = self.documents[doc.PRD]
        old_row = [line for line in prd.splitlines()
                   if line.startswith('| US-001 |')][0]
        priority = old_row.split('|')[-2].strip()
        payload = make_candidate('update', 'US-001').model_dump()
        patch = doc.build_patch(self.documents, payload, 'US-001')
        self.assertIn(f'| {priority} |', patch[doc.PRD])

    def test_pipe_in_title_does_not_break_table(self):
        payload = make_candidate().model_dump()
        payload['story']['title'] = 'A|B'
        patch = doc.build_patch(self.documents, payload, 'US-004')
        self.assertIn('| US-004 | A/B — ', patch[doc.PRD])

    def test_delete_patch_removes_story_and_row(self):
        payload = make_candidate('delete', 'US-002').model_dump()
        patch = doc.build_patch(self.documents, payload, 'US-002')
        self.assertNotIn('US-002', patch[doc.USER_STORIES])
        self.assertNotIn('| US-002 |', patch[doc.PRD])

    def test_render_diff_marks_before_and_after(self):
        payload = make_candidate().model_dump()
        patch = doc.build_patch(self.documents, payload, 'US-004')
        diff = doc.render_diff(self.documents, patch)
        self.assertIn('user-stories.md (이전)', diff)
        self.assertIn('+## US-004 월간 보고서', diff)

    def test_validate_requires_title(self):
        broken = {**self.documents, doc.SPEC: '제목 없음\n'}
        with self.assertRaises(ValueError):
            doc.validate_documents(broken)


class StateStoreTest(unittest.TestCase):
    """StateStore의 ID 예약과 이벤트 저장."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        shutil.copytree(FIXTURE, root / 'docs')
        self.store = StateStore(root / 'state')
        self.store.bind('T1', 'C1', root / 'docs')
        self.documents = doc.read_documents(root / 'docs')

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_reserve_id_never_reuses(self):
        with self.store.transaction():
            first = self.store.reserve_id('T1/C1', 'US', self.documents)
            second = self.store.reserve_id('T1/C1', 'US', self.documents)
        self.assertEqual(('US-004', 'US-005'), (first, second))

    def test_add_event_ignores_duplicate_ts(self):
        source = 'T1/C1/channel'
        self.assertTrue(self.store.add_event(source, '1', 'U1', '안녕'))
        self.assertFalse(self.store.add_event(source, '1', 'U1', '안녕'))
        self.assertTrue(self.store.add_event(source, '2', 'U1', '다음'))
        sequences = [event['seq'] for event in
                     self.store.find_all('event', source=source)]
        self.assertEqual([1, 2], sequences)

    def test_find_all_accepts_kind_filter(self):
        with self.store.transaction():
            self.store.put('candidate', {'id': 'x', 'kind': 'spec'})
        self.assertEqual(1, len(self.store.find_all('candidate',
                                                    kind='spec')))


class ConfigTest(unittest.TestCase):
    """Config.validate의 필수 값 검사."""

    def make_config(self, **overrides):
        values = {'data_dir': Path('.'), 'bot_token': 'b', 'app_token': 'a',
                  'api_key': 'k', 'model': 'm:free', 'endings': (),
                  'channels': frozenset()}
        values.update(overrides)
        return Config(**values)

    def test_paid_model_rejected(self):
        with self.assertRaises(ValueError):
            self.make_config(model='paid-model').validate()

    def test_missing_token_named(self):
        with self.assertRaisesRegex(ValueError, 'SLACK_APP_TOKEN'):
            self.make_config(app_token='').validate()


class FakeLlm:
    """정해진 JSON을 돌려주는 가짜 LLM."""

    def __init__(self, raw_json):
        self.raw_json = raw_json
        self.calls = []

    def complete(self, system_prompt, user_content, schema):
        self.calls.append((system_prompt, user_content, schema))
        return self.raw_json


class WhyGroundingTest(unittest.TestCase):
    """원문 근거가 없는 Why를 지우는 규칙."""

    def analyze(self, why, evidence, conversation_text):
        candidate = make_candidate().model_copy(update={
            'why_evidence': evidence})
        candidate.story.why = why
        service = RequirementAnalysisService(FakeLlm(
            '{"candidates": [' + candidate.model_dump_json() + ']}'))
        conversation = [{'text': conversation_text}]
        return service.extract_requirements(conversation, {}).candidates[0]

    def test_quoted_purpose_is_kept(self):
        result = self.analyze('시간을 줄이기 위해', '시간을 줄이기 위해',
                              '보고서는 시간을 줄이기 위해 필요해요')
        self.assertEqual('시간을 줄이기 위해', result.story.why)

    def test_invented_purpose_is_removed(self):
        result = self.analyze('시간을 줄이기 위해', '시간을 줄이기 위해',
                              '보고서가 필요해요')
        self.assertEqual('', result.story.why)
        self.assertIn('Why', result.question)


class SlackBotTest(unittest.TestCase):
    """SlackBot(View)의 메시지 구성."""

    def setUp(self):
        self.sent = []

        def send(channel, text, **options):
            self.sent.append((channel, text, options))
            return {'ts': str(len(self.sent))}

        self.bot = SlackBot(send)
        documents = doc.read_documents(FIXTURE)
        payload = make_candidate().model_dump()
        self.record = CandidateRecord(
            id='c1', binding='T1/C1', source='T1/C1/channel', kind='story',
            target='US-004', status=CandidateStatus.PENDING, payload=payload,
            docs=documents, version=2,
            plan=doc.build_patch(documents, payload, 'US-004'))

    def test_proposal_has_versioned_buttons(self):
        ts = self.bot.propose_change('C1', self.record, thread='9')
        _, text, options = self.sent[0]
        buttons = options['blocks'][-1]['elements']
        self.assertEqual('1', ts)
        self.assertEqual(['c1:2', 'c1:2'], [b['value'] for b in buttons])
        self.assertTrue(options['reply_broadcast'])
        self.assertIn('Story/PRD 공동 승인', text)

    def test_too_long_preview_rejected(self):
        self.record.payload['evidence'] = 'x' * 2800 * MAX_BLOCKS
        with self.assertRaises(ValueError):
            self.bot.propose_change('C1', self.record)
        self.assertEqual([], self.sent)

    def test_failure_notice_has_retry_button(self):
        self.bot.show_error('C1', 'src', '오류', thread='5')
        _, _, options = self.sent[0]
        self.assertEqual('5', options['thread_ts'])
        button = options['blocks'][-1]['elements'][0]
        self.assertEqual(('retry', 'src'), (button['action_id'],
                                            button['value']))

    def test_conflict_choice_offers_both_sides(self):
        self.record.status = CandidateStatus.CONFLICTED
        self.record.conflict = {'requirement_ids': ['US-003'],
                                'reason': '동시에 불가'}
        self.bot.ask_conflict_choice('C1', self.record)
        _, text, options = self.sent[0]
        labels = [button['text']['text']
                  for button in options['blocks'][-1]['elements']]
        self.assertEqual(['US-003 유지', '새 요구사항 채택'], labels)
        self.assertIn('## US-003 CSV 내보내기', text)
        self.assertIn('## US-004 월간 보고서', text)


class CandidateRecordTest(unittest.TestCase):
    """CandidateRecord 저장 형식."""

    def test_round_trip_keeps_status_enum(self):
        record = CandidateRecord(
            id='x', binding='b', source='s', kind='story', target='US-001',
            status=CandidateStatus.CONFLICTED, payload={}, docs={},
            conflict={'requirement_ids': ['US-002'], 'reason': 'r'})
        data = record.to_dict()
        self.assertEqual('conflicted', data['status'])
        restored = CandidateRecord.from_dict({**data, 'unknown': 1})
        self.assertEqual(record, restored)
        self.assertTrue(restored.is_active)
        self.assertEqual(['US-002'], restored.conflict_ids)


if __name__ == '__main__':
    unittest.main()
