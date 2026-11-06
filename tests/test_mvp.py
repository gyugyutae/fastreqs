import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from fastreqs import documents as md
from fastreqs.models import Candidate,Analysis
from fastreqs.store import Store
from fastreqs.service import Service

FIXTURE=Path(__file__).resolve().parents[1]/'demo-fixtures/team-search'

def candidate(action='add',target='',why='월간 실적 공유 시간을 줄이기 위해서'):
    return Candidate(action=action,target_id=target,story=None if action=='delete' else
        {'title':'월간 보고서','who':'팀 관리자','what':'월을 선택하고 보고서를 내려받는다','why':why,
         'acceptance':['선택한 월의 업무 건수와 완료 건수를 표시한다']},
        evidence='회의에서 보고서를 요청했다',question='왜 필요한가요?' if not why else '',
        spec_change='',adr_change=None)

class Fake:
    def __init__(self,values): self.values=list(values); self.calls=[]
    def analyze(self,messages,state,clarification=None):
        self.calls.append((messages,state,clarification)); value=self.values.pop(0)
        if isinstance(value,Exception): raise value
        return Analysis(candidates=value)

class MVPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.folder=self.root/'documents'; shutil.copytree(FIXTURE,self.folder)
        self.store=Store(self.root/'state'); self.binding=self.store.bind('T1','C1',self.folder)
        self.sent=[]
        def send(channel,text,**kwargs):
            self.sent.append((channel,text,kwargs)); return {'ts':str(len(self.sent))}
        self.send=send; self.config=SimpleNamespace(endings=('수고하셨습니다',))
    def tearDown(self): self.store.db.close(); self.tmp.cleanup()
    def service(self,values): return Service(self.store,Fake(values),self.send,self.config,'BOT')
    def source(self): return self.store.get('source','T1/C1/channel')
    def propose(self,service,value):
        with self.store.tx(): return service.make(self.source(),value,md.read(self.folder))
    def test_joint_patch_preserves_unrelated(self):
        svc=self.service([]); before=md.read(self.folder); p=self.propose(svc,candidate())
        self.assertIn('승인 반영 완료',svc.decide('T1/C1',p['id'],1,True,'U1'))
        after=md.read(self.folder)
        self.assertIn('US-004',after['user-stories.md']); self.assertIn('US-004',after['prd.md'])
        self.assertEqual(before['adr.md'],after['adr.md']); self.assertEqual(before['spec.md'],after['spec.md'])
        for sid,body in md.sections(before['user-stories.md']).items(): self.assertEqual(body,md.sections(after['user-stories.md'])[sid])
        self.assertIn('## 제외 범위\n음성 검색, 외부 서비스 연동.',after['prd.md'])
        self.assertIn('이미 처리',svc.decide('T1/C1',p['id'],1,True,'U2'))
    def test_reject_never_writes(self):
        svc=self.service([]); before=md.read(self.folder); p=self.propose(svc,candidate())
        svc.decide('T1/C1',p['id'],1,False,'U1'); self.assertEqual(before,md.read(self.folder))
        self.assertFalse(svc.pending(self.source()['id']))
    def test_manual_edit_requires_new_approval(self):
        svc=self.service([]); p=self.propose(svc,candidate())
        path=self.folder/'prd.md'; path.write_text(path.read_text()+'\n수동 메모\n')
        self.assertIn('다시 승인',svc.decide('T1/C1',p['id'],1,True,'U1'))
        self.assertNotIn('US-004',md.read(self.folder)['user-stories.md'])
        fresh=svc.pending(self.source()['id'])[0]; svc.decide('T1/C1',fresh['id'],1,True,'U1')
        self.assertIn('수동 메모',md.read(self.folder)['prd.md'])
    def test_joint_failure_rolls_back(self):
        svc=self.service([]); p=self.propose(svc,candidate()); before=md.read(self.folder); original=md.atomic_write
        def failing(path,content):
            if Path(path).name=='prd.md': raise OSError('disk')
            original(path,content)
        with patch('fastreqs.documents.atomic_write',side_effect=failing):
            self.assertIn('저장 실패',svc.decide('T1/C1',p['id'],1,True,'U1'))
        self.assertEqual(before,md.read(self.folder)); self.assertEqual('pending',self.store.get('candidate',p['id'])['status'])
    def test_delete_then_separate_spec(self):
        svc=self.service([]); p=self.propose(svc,candidate('delete','US-002')); before=md.read(self.folder)
        svc.decide('T1/C1',p['id'],1,True,'U1'); after=md.read(self.folder)
        self.assertNotIn('US-002',after['user-stories.md']); self.assertEqual(before['spec.md'],after['spec.md'])
        tech=self.store.all('candidate',kind='spec')[0]; svc.decide('T1/C1',tech['id'],1,True,'U2')
        self.assertNotIn('US-002',md.sections(md.read(self.folder)['spec.md']))
        self.assertEqual(before['adr.md'],md.read(self.folder)['adr.md'])
    def test_failure_preserves_cursor_candidates(self):
        svc=self.service([RuntimeError('offline')]); p=self.propose(svc,candidate())
        self.store.event(self.source()['id'],'1','U1','새 요구사항'); svc.analyze(self.source()['id'])
        self.assertEqual(0,self.source()['cursor']); self.assertEqual('pending',self.store.get('candidate',p['id'])['status'])
        self.assertFalse(self.source()['busy'])
    def test_file_isolation_duplicate_and_clarification(self):
        svc=self.service([[candidate(why='')],[candidate()]])
        svc.receive('T1',{'channel':'C1','user':'U1','ts':'1','text':'일반 채널 대화'})
        upload={'channel':'C1','user':'U1','ts':'2','files':[{'id':'F1','name':'meeting.md','size':20}],'subtype':'file_share'}
        svc.receive('T1',upload,lambda f:'월간 보고서 요청')
        svc.receive('T1',{**upload,'ts':'3'},lambda f:'월간 보고서 요청')
        self.assertEqual(2,len(self.store.all('source')))
        svc.receive('T1',{'channel':'C1','user':'U1','ts':'4','thread_ts':'2','text':'<@BOT> 분석해줘'})
        p=self.store.all('candidate')[0]; self.assertEqual('clarifying',p['status'])
        svc.receive('T1',{'channel':'C1','user':'U2','ts':'5','thread_ts':p['thread'],'text':'월간 공유 시간을 줄이려고요'})
        self.assertEqual('replaced',self.store.get('candidate',p['id'])['status'])
        self.assertEqual(0,self.source()['cursor'])
        self.assertNotIn('일반 채널 대화',str(svc.analyzer.calls))
    def test_busy_decision_and_followup(self):
        svc=self.service([]); p=self.propose(svc,candidate())
        with self.store.tx(): s=self.source(); s['busy']=True; self.store.put('source',s)
        self.assertIn('새 제안을 확인',svc.decide('T1/C1',p['id'],1,True,'U1'))
        svc.analyze(self.source()['id']); self.assertTrue(self.source()['followup'])
    def test_restart_preserves_candidates(self):
        svc=self.service([]); p=self.propose(svc,candidate()); self.store.db.close(); self.store=Store(self.root/'state')
        self.assertEqual(p,self.store.get('candidate',p['id']))
    def test_followup_uses_new_range_and_pending(self):
        svc=self.service([])
        service_source=self.source()['id']
        class Followup:
            count=0
            def analyze(inner,messages,state,clarification=None):
                inner.count+=1
                if inner.count==1:
                    self.store.event(service_source,'next','U2','새 추가 근거')
                    svc.analyze(service_source)
                else:
                    self.assertEqual(['새 추가 근거'],[m['text'] for m in messages])
                    self.assertEqual(1,len(state['pending']))
                return Analysis(candidates=[candidate()])
        svc.analyzer=Followup()
        self.store.event(service_source,'first','U1','월간 보고서 필요')
        svc.analyze(service_source)
        self.assertEqual(2,svc.analyzer.count)
        self.assertEqual(2,self.source()['cursor'])
        self.assertEqual(1,len(svc.pending(service_source)))

    def test_conflict_blocks_approval(self):
        svc=self.service([])
        c=Candidate.model_validate({**candidate().model_dump(),'conflicted':True,'question':'목적이 다릅니다. 어떤 답인가요?'})
        p=self.propose(svc,c)
        self.assertEqual('conflicted',p['status'])
        before=md.read(self.folder)
        svc.decide('T1/C1',p['id'],1,True,'U1')
        self.assertEqual(before,md.read(self.folder))

    def test_adr_append_preserves_previous_reason(self):
        svc=self.service([])
        c=candidate('update','US-003')
        c.adr_change=__import__('fastreqs.models',fromlist=['ADRChange']).ADRChange(
            title='새 정책',context='정책 변경 합의',decision='새 정책 적용',alternatives='기존 유지',consequences='권한 변경',supersedes='ADR-001')
        p=self.propose(svc,c); before=md.read(self.folder)
        svc.decide('T1/C1',p['id'],1,True,'U1')
        self.assertEqual(before['adr.md'],md.read(self.folder)['adr.md'])
        tech=self.store.all('candidate',kind='adr')[0]
        svc.decide('T1/C1',tech['id'],1,True,'U2')
        text=md.read(self.folder)['adr.md']
        self.assertIn('ADR-002',text); self.assertIn('- 상태: Superseded',text)
        self.assertIn('초기에는 관리자가 주간 공유 자료를 만든다.',text)

    def test_first_concurrent_decision_wins(self):
        svc=self.service([]); p=self.propose(svc,candidate()); results=[]
        workers=[threading.Thread(target=lambda user=user:results.append(svc.decide('T1/C1',p['id'],1,True,user))) for user in ('U1','U2')]
        for t in workers:t.start()
        for t in workers:t.join()
        self.assertEqual(1,sum(r.startswith('승인 반영 완료') for r in results))
        self.assertEqual(1,len(self.store.all('operation')))

    def test_restart_identifies_partial_files(self):
        svc=self.service([]); p=self.propose(svc,candidate()); docs=md.read(self.folder)
        op={'id':'partial','binding':'T1/C1','candidate':p['id'],'state':'prepared','before':docs,
            'after':p['plan'],'actor':'U1','time':'2026-10-11'}
        with self.store.tx():
            self.store.put('operation',op); p['status']='applying'; self.store.put('candidate',p)
        md.atomic_write(self.folder/'user-stories.md',p['plan']['user-stories.md'])
        svc.recover()
        self.assertEqual('recovery_required',self.store.get('operation','partial')['state'])
        self.assertEqual('apply_failed',self.store.get('candidate',p['id'])['status'])

    def test_path_and_schema_protection(self):
        with self.assertRaises(ValueError): self.store.bind('T1','C2',self.folder)
        with self.assertRaises(ValueError): Candidate.model_validate({**candidate().model_dump(),'story':{**candidate().story.model_dump(),'title':'x\n## US-999 injected'}})

if __name__=='__main__': unittest.main()
