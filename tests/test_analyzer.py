import unittest
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from fastreqs.analyzer import OpenRouter, strict_schema

class AnalyzerTests(unittest.TestCase):
    def setUp(self): self.client=OpenRouter(SimpleNamespace(model='test:free',api_key='not-a-real-key'))
    def test_rate_limit_retries_once(self):
        responses=[httpx.Response(429,headers={'Retry-After':'1'}),httpx.Response(200,json={'choices':[{'message':{'content':'{"candidates":[]}'}}]})]
        with patch('httpx.Client.post',side_effect=responses) as post,patch('fastreqs.analyzer.time.sleep') as sleep:
            self.assertEqual([],self.client.analyze([],{}).candidates)
            self.assertEqual(2,post.call_count); sleep.assert_called_once_with(1)
    def test_bad_key_not_retried(self):
        with patch('httpx.Client.post',return_value=httpx.Response(401)) as post:
            with self.assertRaises(RuntimeError):self.client.analyze([],{})
            self.assertEqual(1,post.call_count)
    def test_invalid_json_rejected(self):
        with patch('httpx.Client.post',return_value=httpx.Response(200,json={'choices':[{'message':{'content':'not JSON'}}]})):
            with self.assertRaises(RuntimeError):self.client.analyze([],{})
    def test_oversized_input_not_sent(self):
        with patch('httpx.Client.post') as post:
            with self.assertRaises(ValueError):self.client.analyze([{'text':'x'*60001}],{})
            post.assert_not_called()
    def test_schema_fields_required(self):
        schema=strict_schema()
        candidate=schema['$defs']['Candidate']
        self.assertEqual(set(candidate['properties']),set(candidate['required']))

if __name__=='__main__':unittest.main()
