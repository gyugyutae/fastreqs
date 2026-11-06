"""Explicit offline rehearsal. No Slack connection or model invocation."""
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from .config import ROOT
from .store import Store
from .service import Service
from .models import Analysis,Candidate

class ScriptedAnalyzer:
    def __init__(self): self.step=0
    def analyze(self,messages,state,clarification=None):
        self.step+=1
        if self.step==3:
            value=Candidate(action='delete',target_id='US-002',story=None,evidence='다크 모드는 삭제하기로 정했습니다',question='',spec_change='',adr_change=None)
        else:
            value=Candidate(action='add',target_id='',story={'title':'월간 보고서','who':'팀 관리자','what':'월을 선택하고 업무 건수와 완료 건수를 내려받는다',
                'why':'' if self.step==1 else '월간 실적 공유 시간을 줄이기 위해서','acceptance':['선택한 월의 업무 건수와 완료 건수가 포함된다']},
                evidence='관리자가 월간 보고서를 내려받을 수 있어야 합니다',question='월간 보고서가 필요한 목적은 무엇인가요?',spec_change='',adr_change=None)
        return Analysis(candidates=[value])

def replay():
    print('OFFLINE MOCK: Slack/무료 모델 실제 작동 검증이 아닙니다.')
    with tempfile.TemporaryDirectory(prefix='fastreqs-replay-') as tmp:
        root=Path(tmp); folder=root/'documents'; shutil.copytree(ROOT/'demo-fixtures/team-search',folder)
        store=Store(root/'state'); store.bind('DEMO','CDEMO',folder)
        sent=[]
        def send(channel,text,**kwargs):
            sent.append(text); print('\n'+text); return {'ts':str(len(sent))}
        svc=Service(store,ScriptedAnalyzer(),send,SimpleNamespace(endings=('수고하셨습니다',)),'BOT')
        base={'channel':'CDEMO','user':'U1'}
        svc.receive('DEMO',{**base,'ts':'upload','files':[{'id':'F1','name':'meeting.md','size':100}]},
                    lambda f:(ROOT/'demo-fixtures/meeting-inputs/01-monthly-report.md').read_text())
        svc.receive('DEMO',{**base,'ts':'request','thread_ts':'upload','text':'<@BOT> 분석해줘'})
        p=store.all('candidate')[0]
        svc.receive('DEMO',{**base,'ts':'answer','thread_ts':p['thread'],'text':'월간 실적 공유 시간을 줄이기 위해서입니다.'})
        p=[p for p in store.all('candidate') if p['status']=='pending'][0]
        print(svc.decide('DEMO/CDEMO',p['id'],p['version'],True,'U1'))
        svc.receive('DEMO',{**base,'ts':'discussion','text':'다크 모드는 삭제하는 것으로 정하겠습니다.'})
        svc.receive('DEMO',{**base,'ts':'ending','text':'수고하셨습니다'})
        p=[p for p in store.all('candidate') if p['status']=='pending' and p['kind']=='story'][0]
        print(svc.decide('DEMO/CDEMO',p['id'],1,True,'U2'))
        p=[p for p in store.all('candidate') if p['status']=='pending' and p['kind']=='spec'][0]
        print(svc.decide('DEMO/CDEMO',p['id'],1,True,'U2'))
        from .documents import read
        result=read(folder)
        assert '월간 보고서' in result['user-stories.md'] and 'US-002' not in result['user-stories.md']
        assert 'US-002' not in result['spec.md'] and 'ADR-001' in result['adr.md']
        print('\n모의 데모 완료: 보완→공동 승인→삭제→Spec 별도 승인. 임시 문서는 종료 시 삭제됩니다.')
        store.db.close()
