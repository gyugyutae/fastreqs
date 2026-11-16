"""분석 서비스와 OpenRouter 클라이언트의 호출·검증 테스트."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from fastreqs import documents as doc
from fastreqs.analysis_service import RequirementAnalysisService, strict_schema
from fastreqs.llm_client import OpenRouterClient
from fastreqs.models import Candidate, ConflictReport
from tests.test_units import FIXTURE, FakeLlm, make_candidate

EMPTY_ANALYSIS = '{"candidates": []}'


def chat_response(content):
    """OpenRouter 채팅 응답 형태의 HTTP 응답을 만든다."""
    return httpx.Response(
        200, json={'choices': [{'message': {'content': content}}]})


class OpenRouterCallTest(unittest.TestCase):
    """HTTP 재시도와 오류 처리."""

    def setUp(self):
        config = SimpleNamespace(model='test:free', api_key='not-a-real-key')
        self.service = RequirementAnalysisService(OpenRouterClient(config))

    def test_rate_limit_retries_once(self):
        responses = [httpx.Response(429, headers={'Retry-After': '1'}),
                     chat_response(EMPTY_ANALYSIS)]
        with patch('httpx.Client.post', side_effect=responses) as post, \
                patch('fastreqs.llm_client.time.sleep') as sleep:
            analysis = self.service.extract_requirements([], {})
        self.assertEqual([], analysis.candidates)
        self.assertEqual(2, post.call_count)
        sleep.assert_called_once_with(1)

    def test_bad_key_not_retried(self):
        with patch('httpx.Client.post',
                   return_value=httpx.Response(401)) as post:
            with self.assertRaises(RuntimeError):
                self.service.extract_requirements([], {})
        self.assertEqual(1, post.call_count)

    def test_invalid_json_rejected(self):
        with patch('httpx.Client.post',
                   return_value=chat_response('not JSON')):
            with self.assertRaises(RuntimeError):
                self.service.extract_requirements([], {})

    def test_oversized_input_not_sent(self):
        with patch('httpx.Client.post') as post:
            with self.assertRaises(ValueError):
                self.service.extract_requirements([{'text': 'x' * 60001}], {})
        post.assert_not_called()

    def test_schema_fields_required(self):
        candidate = strict_schema()['$defs']['Candidate']
        self.assertEqual(set(candidate['properties']),
                         set(candidate['required']))


def conflict_json(*groups):
    """충돌 ID 묶음으로 ConflictReport JSON을 만든다."""
    conflicts = [{'requirement_ids': list(ids), 'reason': '동시에 불가'}
                 for ids in groups]
    return json.dumps({'conflicts': conflicts})


class ConflictCheckTest(unittest.TestCase):
    """check_conflicts: 충돌 검사의 유일한 위치."""

    def setUp(self):
        self.documents = doc.read_documents(FIXTURE)

    def check(self, raw_json, candidate=None):
        """가짜 LLM 응답으로 충돌 검사를 실행한다."""
        service = RequirementAnalysisService(FakeLlm(raw_json))
        return service.check_conflicts(self.documents, candidate)

    def test_candidate_conflict_with_existing_story(self):
        conflicts = self.check(conflict_json(['US-003']), make_candidate())
        self.assertEqual([['US-003']],
                         [item.requirement_ids for item in conflicts])

    def test_no_conflict(self):
        self.assertEqual([], self.check(conflict_json(), make_candidate()))

    def test_unknown_or_target_ids_are_dropped(self):
        candidate = make_candidate('update', 'US-001')
        raw = conflict_json(['US-999'], ['US-001'], ['US-002', 'US-003'])
        self.assertEqual([], self.check(raw, candidate))

    def test_full_scan_needs_pairs(self):
        raw = conflict_json(['US-003', 'US-001'], ['US-002'],
                            ['US-001', 'US-003'])
        conflicts = self.check(raw)
        self.assertEqual([['US-001', 'US-003']],
                         [item.requirement_ids for item in conflicts])

    def test_invalid_json_is_runtime_error(self):
        with self.assertRaises(RuntimeError):
            self.check('not JSON', make_candidate())

    def test_prompt_receives_candidate_and_stories(self):
        llm = FakeLlm(conflict_json())
        service = RequirementAnalysisService(llm)
        service.check_conflicts(self.documents, make_candidate())
        sent = json.loads(llm.calls[0][1])
        self.assertEqual({'US-001', 'US-002', 'US-003'}, set(sent['stories']))
        self.assertEqual('add', sent['candidate']['action'])
        self.assertEqual(strict_schema(ConflictReport), llm.calls[0][2])

    def test_contradicting_answers_need_answer(self):
        payload = {**make_candidate().model_dump(),
                   'answers_contradict': True}
        self.assertTrue(Candidate.model_validate(payload).needs_answer())


if __name__ == '__main__':
    unittest.main()
