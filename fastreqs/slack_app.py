import re
from urllib.parse import urlparse
import httpx
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from .analyzer import OpenRouter
from .service import Service
from .store import Store


def download_file(client, token, file):
    info=client.files_info(file=file['id'])['file']
    url=info.get('url_private_download') or info.get('url_private')
    parsed=urlparse(url or '')
    if parsed.scheme!='https' or not (parsed.hostname or '').endswith('.slack.com'):
        raise ValueError('Slack 파일 다운로드 주소를 확인할 수 없습니다.')
    # Never forward a bearer token to arbitrary redirects or attachment URLs.
    with httpx.Client(timeout=30,follow_redirects=False) as http:
        with http.stream('GET',url,headers={'Authorization':'Bearer '+token}) as response:
            if response.status_code!=200: raise ValueError('파일 다운로드 실패. files:read 권한을 확인해주세요.')
            data=bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data)>1_000_000: raise ValueError('파일은 최대 1 MB입니다.')
    try: return bytes(data).decode('utf-8-sig')
    except UnicodeDecodeError: raise ValueError('UTF-8 Markdown 파일만 지원합니다.') from None

def run(config):
    config.validate(); app=App(token=config.bot_token)
    identity=app.client.auth_test(); workspace,bot_id=identity['team_id'],identity['user_id']
    store=Store(config.data_dir)
    if not store.all('binding',workspace=workspace): raise ValueError('먼저 python -m fastreqs configure 를 실행하세요.')
    def send(channel,text,**kwargs): return app.client.chat_postMessage(channel=channel,text=text,**kwargs)
    service=Service(store,OpenRouter(config),send,config,bot_id)
    service.recover()
    @app.event('message')
    def message(event): service.receive(workspace,event,lambda f:download_file(app.client,config.bot_token,f))
    @app.event('app_mention')
    def mention(event): service.receive(workspace,event,lambda f:download_file(app.client,config.bot_token,f))
    @app.action(re.compile(r'^(approve|reject|retry)$'))
    def action(ack,body,client):
        ack(); channel=body['channel']['id']; clicked=body['actions'][0]
        try:
            if clicked['action_id']=='retry':
                source=store.get('source',clicked['value'])
                if source['binding']!=workspace+'/'+channel: raise ValueError('다른 채널 요청입니다.')
                service.analyze(source['id']); return
            pid,version=clicked['value'].split(':')
            result=service.decide(workspace+'/'+channel,pid,int(version),clicked['action_id']=='approve',body['user']['id'])
            client.chat_postEphemeral(channel=channel,user=body['user']['id'],text=result)
            if result.startswith(('승인 반영 완료','거절했습니다')):
                client.chat_update(channel=channel,ts=body['message']['ts'],text=result,blocks=[{'type':'section','text':{'type':'plain_text','text':result}}])
        except Exception:
            client.chat_postEphemeral(channel=channel,user=body['user']['id'],text='처리 실패. 문서와 후보 상태를 확인하고 다시 요청해주세요.')
    for b in store.all('binding',workspace=workspace):
        send(b['channel'],'FastReqs 수집을 재개했습니다. 중단 중 대화는 자동 수집하지 않습니다. Markdown 회의록으로 보충할 수 있습니다.')
    for p in store.all('candidate'):
        if p['status'] in ('pending','clarifying','conflicted'):
            service.show(p)
    print('Slack 연결 완료. Ctrl+C로 종료합니다.',flush=True)
    SocketModeHandler(app,config.app_token).start()
