from fastreqs.config import Config
from fastreqs.store import Store
from fastreqs.service import Service
from fastreqs.analyzer import OpenRouter
from slack_sdk import WebClient
c=Config.load();s=Store(c.data_dir);client=WebClient(token=c.bot_token)
def send(channel,text,**kwargs):return client.chat_postMessage(channel=channel,text=text,**kwargs)
svc=Service(s,OpenRouter(c),send,c,client.auth_test()['user_id'])
for p in s.all('candidate'):
    if p['status']=='pending':
        p['thread']=None
        with s.tx():s.put('candidate',p)
        svc.show(p)
        latest=s.get('candidate',p['id'])
        print('APPROVAL_LINK',client.chat_getPermalink(conversation_id=s.get('binding',p['binding'])['channel'],message_ts=latest['message'])['permalink'])
