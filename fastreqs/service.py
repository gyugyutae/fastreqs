import threading
from pathlib import Path
from . import documents as md
from .models import Candidate
from .store import now

ACTIVE = ('pending','clarifying','conflicted')

class Service:
    def __init__(self,store,analyzer,send,config,bot_id):
        self.store,self.analyzer,self.send,self.config,self.bot_id=store,analyzer,send,config,bot_id
        self.guard=threading.RLock(); self.locks={}
    def lock(self,binding):
        with self.guard: return self.locks.setdefault(binding,threading.RLock())
    def notify(self,source,text,**kwargs):
        binding=self.store.get('binding',source['binding'])
        if source['thread']: kwargs.setdefault('thread_ts',source['thread'])
        return self.send(binding['channel'],text,**kwargs)
    def snapshot(self,binding): return md.read(self.store.get('binding',binding)['folder'])
    def pending(self,source):
        return [p for p in self.store.all('candidate',source=source) if p['status'] in ACTIVE and p['kind']=='story']
    def show(self,p):
        source=self.store.get('source',p['source'])
        if p['status'] in ('clarifying','conflicted'):
            text='유저스토리 보완 질문\n'+(p['payload'].get('question') or 'Who/What/Why와 인수조건을 보완해주세요.')+'\n이 스레드에 누구나 답할 수 있습니다.'
            blocks=None
        else:
            text=f"{p['kind']} {p['payload'].get('action','변경')} · {p['target']}\n"
            text+='Story/PRD 공동 승인\n' if p['kind']=='story' else '기술 문서 별도 승인\n'
            text+='근거: '+p['payload'].get('evidence','승인된 Story의 변경 영향')+'\n'+md.preview(p['docs'],p['plan'])
            # Full preview is retained in all section blocks, never silently truncated.
            blocks=[{'type':'section','text':{'type':'plain_text','text':text[i:i+2800]}} for i in range(0,len(text),2800)]
            blocks.append({'type':'actions','elements':[{'type':'button','action_id':action,'value':p['id']+':'+str(p['version']),
              'text':{'type':'plain_text','text':label}} for action,label in [('approve','승인'),('reject','거절')]]})
            if len(blocks)>48: raise ValueError('미리보기가 너무 깁니다. 후보 내용을 줄여주세요.')
        kwargs={'blocks':blocks} if blocks else {}
        if p.get('thread'):
            kwargs['thread_ts']=p['thread']
            if p['status']=='pending': kwargs['reply_broadcast']=True
        binding=self.store.get('binding',source['binding'])
        response=self.send(binding['channel'],text[:3500],**kwargs)
        with self.store.tx():
            current=self.store.get('candidate',p['id'])
            current['thread']=p.get('thread') or response['ts']; current['message']=response['ts']; self.store.put('candidate',current)
    def make(self,source,candidate,docs,thread=None,reserved_target=None):
        value=candidate.model_dump(); stories=md.sections(docs['user-stories.md'])
        if candidate.target_id and candidate.target_id not in stories: raise ValueError('변경 대상 Story가 없습니다.')
        if candidate.adr_change and candidate.adr_change.supersedes:
            old=md.sections(docs['adr.md']).get(candidate.adr_change.supersedes,'')
            if '- 상태: Accepted' not in old: raise ValueError('대체할 활성 ADR이 없습니다.')
        target=candidate.target_id or reserved_target or self.store.reserve(source['binding'],'US',docs)
        status='conflicted' if candidate.conflicted else ('clarifying' if candidate.needs_answer() else 'pending')
        plan=md.plan(docs,value,target) if status=='pending' else {}
        p={'id':self.store.ident(),'binding':source['binding'],'source':source['id'],'kind':'story','target':target,
           'status':status,'payload':value,'docs':docs,'plan':plan,'version':1,'thread':thread,'created':now()}
        self.store.put('candidate',p); return p
    def analyze(self,sid,correction=None):
        with self.store.tx():
            source=self.store.get('source',sid)
            if source['busy']:
                if correction:
                    queue=[c for c in source.get('corrections',[]) if c['id']!=correction['id']]
                    source['corrections']=queue+[correction]
                else: source['followup']=True
                self.store.put('source',source)
                self.notify(source,'현재 분석 중입니다. 새 요청은 완료 후 이어서 처리하겠습니다.'); return
            source['busy']=True; self.store.put('source',source)
        released=False
        try:
            while True:
                source=self.store.get('source',sid)
                prior=self.pending(sid)
                batch=[e for e in self.store.all('event',source=sid) if e['seq']>source['cursor'] and not e.get('thread')]
                if correction:
                    previous=self.store.get('candidate',correction['id'])
                    if previous['status']=='replaced':
                        latest=[p for p in prior if p.get('thread')==previous.get('thread')]
                        if latest:
                            correction={**latest[-1]['payload'],'id':latest[-1]['id'],'answer':correction.get('answer','')}
                    candidate_thread=self.store.get('candidate',correction['id']).get('thread')
                    batch=[e for e in self.store.all('event',source=sid) if e.get('thread')==candidate_thread]
                end=max([e['seq'] for e in batch] or [source['cursor']])
                docs=self.snapshot(source['binding'])
                candidates_before=[p['payload'] for p in prior]
                context={'documents':docs,'pending':candidates_before,'file':source['content']}
                self.notify(source,'요구사항 변경 후보를 분석하고 있습니다…')
                result=self.analyzer.analyze(batch,context,clarification=correction)
                if correction and len(result.candidates)!=1: raise ValueError('보완/정정 결과는 한 후보여야 합니다.')
                with self.lock(source['binding']),self.store.tx():
                    if docs!=self.snapshot(source['binding']): raise ValueError('분석 중 문서가 바뀌었습니다. 다시 분석해주세요.')
                    replacements=prior
                    if correction:
                        old=self.store.get('candidate',correction['id'])
                        if old['status'] not in ACTIVE: raise ValueError('이미 처리된 후보입니다.')
                        c=result.candidates[0]
                        if c.action!=old['payload']['action'] or c.target_id!=old['payload']['target_id']:
                            raise ValueError('정정에서 대상을 바꾸지 말고 새 분석을 요청해주세요.')
                        replacements=[old]
                    made=[self.make(source,c,docs,thread=(replacements[0].get('thread') if correction else None), reserved_target=(replacements[0]['target'] if correction else None)) for c in result.candidates]
                    for p in replacements: p['status']='replaced'; self.store.put('candidate',p)
                    source=self.store.get('source',sid)
                    # Candidate-specific answers must not consume unrelated conversation.
                    if not correction: source['cursor']=end
                    self.store.put('source',source)
                for p in made: self.show(p)
                if not made: self.notify(source,'요구사항 변경 후보가 없습니다.')
                correction=None
                with self.store.tx():
                    source=self.store.get('source',sid)
                    if source.get('corrections'):
                        correction=source['corrections'].pop(0); self.store.put('source',source); continue
                    if source['followup']:
                        source['followup']=False; self.store.put('source',source); continue
                    source['busy']=False; self.store.put('source',source)
                    released=True
                    break
        except Exception as exc:
            detail=str(exc) if isinstance(exc,(ValueError,RuntimeError)) else '처리 중 오류가 발생했습니다.'
            self.notify(source,'분석 실패: '+detail+'\n입력과 미결 제안은 보존했습니다.',blocks=[
                {'type':'section','text':{'type':'plain_text','text':('분석 실패: '+detail+'\n입력과 미결 제안은 보존했습니다. 다시 분석할 수 있습니다.')[:2800]}},
                {'type':'actions','elements':[{'type':'button','action_id':'retry','value':sid,'text':{'type':'plain_text','text':'다시 분석'}}]}])
        finally:
            if not released:
                with self.store.tx():
                    source=self.store.get('source',sid); source['busy']=False; self.store.put('source',source)
    def receive(self,workspace,event,download=None):
        channel=event.get('channel'); binding=workspace+'/'+str(channel)
        if not self.store.all('binding',id=binding): return
        if event.get('bot_id') or not event.get('user') or event.get('subtype') not in (None,'file_share'): return
        ts=event.get('ts'); text=event.get('text',''); thread=event.get('thread_ts')
        if not ts: return
        if event.get('files'):
            files=event['files']
            try:
                if len(files)!=1: raise ValueError('메시지당 .md 파일 하나만 올려주세요.')
                f=files[0]
                if not f.get('name','').lower().endswith('.md') or f.get('size',0)>1_000_000: raise ValueError('UTF-8 .md, 최대 1 MB만 지원합니다.')
                content=download(f)
                if len(content.encode('utf-8'))>1_000_000 or not content.strip(): raise ValueError('빈 파일 또는 1 MB 초과 파일입니다.')
                with self.store.tx(): source,fresh=self.store.source(binding,ts,content)
                if not fresh:
                    self.notify({'binding':binding,'thread':ts},'같은 회의록이 이미 있습니다. 기존 스레드에서 분석해주세요: '+str(source['thread']))
                else: self.notify(source,'회의록을 저장했습니다. 이 스레드에서 @FastReqs 분석해줘를 요청해주세요.')
            except Exception as exc:
                self.send(channel,'파일 확인 실패: '+(str(exc) if isinstance(exc,ValueError) else '다운로드/권한을 확인해주세요.'),thread_ts=ts)
            return
        related=[p for p in self.store.all('candidate',binding=binding) if p.get('thread')==thread and thread]
        files=[s for s in self.store.all('source',binding=binding) if s['thread']==thread and thread]
        if not related and files and not (f'<@{self.bot_id}>' in text and '분석' in text):
            waiting=[p for p in self.pending(files[0]['id']) if p['status'] in ('clarifying','conflicted')]
            if len(waiting)==1:
                related=waiting
                thread=waiting[0]['thread']
            elif len(waiting)>1:
                self.notify(files[0],'보완 후보가 여러 개입니다. 해당 보완 질문 메시지에 답글로 답해주세요.')
        if related:
            active=[p for p in related if p['status'] in ACTIVE]
            # Latest live candidate in a reused thread wins routing.
            p=active[-1] if active else related[-1]
            source=self.store.get('source',p['source'])
            if not self.store.event(source['id'],ts,event['user'],text,thread=thread): return
            if p['kind']!='story':
                self.notify(source,'기술 제안 정정은 관련 요구사항을 새 분석으로 요청해주세요.'); return
            correction={**p['payload'],'id':p['id'],'answer':text,'previous_status':p['status']}
            if p['status'] not in ACTIVE:
                with self.store.tx():
                    saved=self.store.get('event',source['id']+':'+ts)
                    saved['thread']=None; saved['text']='관련 Story '+p['target']+'의 새 변경 요청: '+text
                    self.store.put('event',saved)
                self.analyze(source['id']); return
            self.analyze(source['id'],correction); return
        if files: source=files[0]
        else:
            with self.store.tx(): source,_=self.store.source(binding)
        if not self.store.event(source['id'],ts,event['user'],text): return
        mention=f'<@{self.bot_id}>' in text and '분석' in text
        ending=not source['content'] and any(word in text for word in self.config.endings)
        if mention or ending: self.analyze(source['id'])
    def dependencies(self,p,docs):
        value=p['payload']; target=p['target']; created=[]
        for old in self.store.all('candidate',binding=p['binding']):
            if old['kind']!='story' and old['target']==target and old['status'] in ACTIVE:
                old['status']='stale'; self.store.put('candidate',old)
                self.store.put('impact',{'id':p['binding']+':'+old['kind']+':'+target,'binding':p['binding'],'target':target,'kind':old['kind'],'status':'needs_review'})
        if value['spec_change'] or (value['action']=='delete' and target in md.sections(docs['spec.md'])):
            created.append(('spec',{'content':value['spec_change'],'delete':value['action']=='delete'}))
        if value['adr_change']:
            change=value['adr_change']; aid=self.store.reserve(p['binding'],'ADR',docs)
            created.append(('adr',{'change':change,'adr_id':aid}))
        for kind,payload in created:
            child={'id':self.store.ident(),'binding':p['binding'],'source':p['source'],'kind':kind,'target':target,
                'status':'pending','payload':payload,'docs':docs,'plan':md.plan(docs,payload,target,kind),
                'version':1,'thread':None,'created':now(),'story_hash':md.digest(md.sections(docs['user-stories.md']).get(target,''))}
            self.store.put('candidate',child)
            self.store.put('impact',{'id':p['binding']+':'+kind+':'+target,'binding':p['binding'],'target':target,'kind':kind,'status':'needs_review'})
            yield child
    def decide(self,binding,pid,version,approve,user):
        with self.lock(binding):
            with self.store.tx():
                p=self.store.get('candidate',pid); source=self.store.get('source',p['source'])
                if p['binding']!=binding: raise ValueError('다른 채널의 제안입니다.')
                if source['busy'] and p['kind']=='story': return '재분석이 끝나면 새 제안을 확인해주세요.'
                if p['version']!=version or p['status']!='pending': return '이미 처리되었거나 오래된 제안입니다: '+p['status']
                if not approve:
                    p.update(status='rejected',actor=user,decided_at=now()); self.store.put('candidate',p); return '거절했습니다. 문서는 변경하지 않았습니다.'
                docs=self.snapshot(binding)
                if docs!=p['docs']:
                    if p['kind']=='story':
                        p['status']='stale'; self.store.put('candidate',p)
                        new=self.make(source,Candidate.model_validate(p['payload']),docs,thread=p.get('thread'),reserved_target=p['target'])
                    else:
                        current=md.digest(md.sections(docs['user-stories.md']).get(p['target'],''))
                        if current!=p['story_hash']:
                            p['status']='stale'; self.store.put('candidate',p); return '관련 Story가 바뀌었습니다. 기술 변경안을 다시 검토해주세요.'
                        p['docs']=docs; p['plan']=md.plan(docs,p['payload'],p['target'],p['kind']); p['version']+=1
                        self.store.put('candidate',p); new=p
                    refresh=True
                else: refresh=False
            if refresh:
                self.show(new); return '문서가 변경되어 새 미리보기를 만들었습니다. 다시 승인해주세요.'
            folder=Path(self.store.get('binding',binding)['folder'])
            operation={'id':self.store.ident(),'binding':binding,'candidate':pid,'state':'prepared','before':docs,'after':p['plan'],'actor':user,'time':now()}
            with self.store.tx():
                self.store.put('operation',operation); p['status']='applying'; self.store.put('candidate',p)
            written=[]
            try:
                if self.snapshot(binding)!=docs: raise ValueError('저장 직전 문서가 바뀌었습니다.')
                for name,content in p['plan'].items():
                    if (folder/name).read_bytes().decode('utf-8')!=docs[name]: raise ValueError('저장 중 문서가 바뀌었습니다.')
                    md.atomic_write(folder/name,content); written.append(name)
            except Exception:
                recovery=False
                for name in written:
                    try:
                        if (folder/name).read_bytes().decode('utf-8')!=p['plan'][name]: raise OSError('외부 편집 감지')
                        md.atomic_write(folder/name,docs[name])
                    except Exception: recovery=True
                with self.store.tx():
                    operation['state']='recovery_required' if recovery else 'rolled_back'; self.store.put('operation',operation)
                    p['status']='apply_failed' if recovery else 'pending'; self.store.put('candidate',p)
                return '부분 반영: 복구 필요 파일을 확인해주세요: '+', '.join(written) if recovery else '저장 실패. 이전 상태를 유지/복구했습니다. 다시 승인할 수 있습니다.'
            with self.store.tx():
                operation['state']='committed'; self.store.put('operation',operation)
                p.update(status='applied',actor=user,decided_at=now()); self.store.put('candidate',p)
            try:
                with self.store.tx():
                    if p['kind']=='story': children=list(self.dependencies(p,self.snapshot(binding)))
                    else:
                        children=[]; self.store.put('impact',{'id':binding+':'+p['kind']+':'+p['target'],'binding':binding,'target':p['target'],'kind':p['kind'],'status':'aligned'})
                for child in children: self.show(child)
            except Exception:
                self.notify(source,'문서 반영은 완료했습니다. 기술 영향 제안 생성/게시 실패: 갱신 검토 필요.')
            return '승인 반영 완료: '+', '.join(p['plan'])
    def recover(self):
        for source in self.store.all('source'):
            with self.store.tx(): source['busy']=False; self.store.put('source',source)
        for op in self.store.all('operation'):
            if op['state'] not in ('prepared','recovery_required'): continue
            with self.lock(op['binding']):
                docs=md.read(self.store.get('binding',op['binding'])['folder'],validate_structure=False); p=self.store.get('candidate',op['candidate'])
                if all(docs[n]==v for n,v in op['after'].items()):
                    op['state']='committed'; p.update(status='applied',actor=op['actor'],decided_at=op['time'])
                elif all(docs[n]==op['before'][n] for n in op['after']):
                    op['state']='rolled_back'; p['status']='pending'
                else: op['state']='recovery_required'; p['status']='apply_failed'
                with self.store.tx(): self.store.put('operation',op); self.store.put('candidate',p)
                self.send(self.store.get('binding',op['binding'])['channel'],'미완료 저장 작업 확인: '+op['state']+' · '+', '.join(op['after']))
