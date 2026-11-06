from fastreqs.config import Config
from fastreqs.store import Store
from slack_sdk import WebClient
c=Config.load(); s=Store(c.data_dir); client=WebClient(token=c.bot_token)
fixed=[]
with s.tx():
    for p in s.all('candidate'):
        if p['status'] in ('clarifying','conflicted') and '?' in p['payload'].get('question',''):
            p['payload']['question']='이 월간 보고서 기능이 필요한 목적(Why)은 무엇인가요?'
            s.put('candidate',p); fixed.append(p)
for p in fixed:
    b=s.get('binding',p['binding'])
    text='유저스토리 보완 질문\n'+p['payload']['question']+'\n이 스레드에 누구나 답할 수 있습니다.'
    if p.get('message'):
        client.chat_update(channel=b['channel'],ts=p['message'],text=text,blocks=[])
print('QUESTIONS_FIXED',len(fixed))
