import argparse
import re
import shutil
import sys
from pathlib import Path
from .config import Config,ROOT
from .store import Store
from .documents import read


def main():
    parser=argparse.ArgumentParser(description='FastReqs 승인 기반 Slack 요구사항 MVP')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('run'); sub.add_parser('configure'); sub.add_parser('doctor'); sub.add_parser('replay')
    sample=sub.add_parser('init-demo'); sample.add_argument('--folder',default='demo-documents')
    sub.add_parser('status')
    args=parser.parse_args(); config=Config.load()
    try:
        if sys.version_info<(3,10): raise ValueError('Python 3.10 이상이 필요합니다.')
        if args.command=='init-demo':
            folder=Path(args.folder).resolve()
            if folder.exists() and any(folder.iterdir()): raise ValueError('빈 새 폴더만 사용할 수 있습니다. 덮어쓰지 않습니다.')
            shutil.copytree(ROOT/'demo-fixtures/team-search',folder,dirs_exist_ok=True)
            print('데모 문서 준비:',folder)
        elif args.command=='configure':
            from getpass import getpass
            from dotenv import set_key
            settings=ROOT/'.env'
            settings.touch(exist_ok=True)
            for name,value in [('SLACK_BOT_TOKEN',config.bot_token),('SLACK_APP_TOKEN',config.app_token),('OPENROUTER_API_KEY',config.api_key)]:
                if not value:
                    secret=getpass(name+' (입력 숨김): ').strip()
                    if not secret: raise ValueError(name+'이 필요합니다.')
                    set_key(str(settings),name,secret)
            config=Config.load()
            config.validate()
            from slack_sdk import WebClient
            client=WebClient(token=config.bot_token); workspace=client.auth_test()['team_id']
            raw=input('Slack 채널 링크 또는 ID: ').strip()
            match=re.search(r'(?:^|/)([CG][A-Z0-9]+)(?:/|$|\?)',raw)
            if not match: raise ValueError('채널 링크 또는 C/G로 시작하는 채널 ID를 입력하세요.')
            channel=match[1]; info=client.conversations_info(channel=channel)['channel']
            if not info.get('is_member'): raise ValueError('먼저 채널에 FastReqs 봇을 초대하세요.')
            folder=Path(input('네 Markdown 문서 폴더 경로: ').strip().strip('"')).resolve()
            binding=Store(config.data_dir).bind(workspace,channel,folder)
            print('연결 저장 완료:',binding['channel'],binding['folder'],'(문서 변경 없음)')
        elif args.command=='doctor':
            config.validate(); print('Python/환경설정 확인 완료. 키 값과 네트워크 호출은 출력/실행하지 않습니다.')
            store=Store(config.data_dir)
            for b in store.all('binding'): read(b['folder']); print('문서 연결 확인:',b['channel'],b['folder'])
            if not store.all('binding'): print('채널 연결 필요: python -m fastreqs configure')
        elif args.command=='status':
            store=Store(config.data_dir)
            for b in store.all('binding'): print('연결:',b['channel'],b['folder'])
            for p in store.all('candidate'):
                if p['status'] not in ('applied','replaced'): print(p['target'],p['kind'],p['status'])
            for i in store.all('impact'):
                if i['status']!='aligned': print('갱신 검토 필요:',i['target'],i['kind'])
            for op in store.all('operation'):
                if op['state']=='recovery_required': print('복구 필요:',op['id'],list(op['after']))
        elif args.command=='replay':
            from .replay import replay
            replay()
        else:
            from .runtime import single_instance
            from .slack_app import run
            with single_instance(config.data_dir): run(config)
    except (ValueError,RuntimeError,OSError) as exc:
        print(str(exc),file=sys.stderr); return 1
    except KeyboardInterrupt: print('종료했습니다.')
    return 0

if __name__=='__main__': raise SystemExit(main())
