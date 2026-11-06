from fastreqs.config import Config
from fastreqs.store import Store
from fastreqs.analyzer import OpenRouter
from fastreqs.service import Service
from slack_sdk import WebClient
c=Config.load();s=Store(c.data_dir);client=WebClient(token=c.bot_token)
identity=client.auth_test()
def send(channel,text,**kwargs):return client.chat_postMessage(channel=channel,text=text,**kwargs)
svc=Service(s,OpenRouter(c),send,c,identity['user_id'])
p=[p for p in s.all('candidate') if p['status']=='clarifying' and p['kind']=='story'][-1]
events=[e for e in s.all('event',source=p['source']) if '월간 실적 공유 시간을 줄이기' in e['text']]
e=events[-1]
with s.tx():
    e['thread']=p['thread'];s.put('event',e)
svc.analyze(p['source'],{**p['payload'],'id':p['id'],'answer':e['text'],'previous_status':p['status']})
print('ANSWER_PROCESSED')
