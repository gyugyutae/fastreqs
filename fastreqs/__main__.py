"""FastReqs 명령줄 진입점.

사용 예:
    python -m fastreqs configure
    python -m fastreqs run
"""

import argparse
import re
import shutil
import sys
from getpass import getpass
from pathlib import Path

from dotenv import set_key

from .approval_processor import IMPACT_ALIGNED
from .config import ROOT, Config
from .documents import read_documents
from .records import CandidateStatus
from .store import StateStore

MIN_PYTHON = (3, 10)
DEMO_FIXTURE = ROOT / 'demo-fixtures' / 'team-search'
CHANNEL_ID_PATTERN = re.compile(r'(?:^|/)([CG][A-Z0-9]+)(?:/|$|\?)')
SECRET_NAMES = ('SLACK_BOT_TOKEN', 'SLACK_APP_TOKEN', 'OPENROUTER_API_KEY')
FINISHED_STATUSES = (CandidateStatus.APPLIED, CandidateStatus.REPLACED)


def _build_parser():
    """명령줄 인자 파서를 만든다."""
    parser = argparse.ArgumentParser(
        description='FastReqs 승인 기반 Slack 요구사항 MVP')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('run', 'configure', 'doctor', 'replay', 'status'):
        commands.add_parser(name)
    init_demo = commands.add_parser('init-demo')
    init_demo.add_argument('--folder', default='demo-documents')
    return parser


def init_demo(args, config):
    """빈 폴더에 데모용 초기 문서 네 개를 복사한다."""
    folder = Path(args.folder).resolve()
    if folder.exists() and any(folder.iterdir()):
        raise ValueError('빈 새 폴더만 사용할 수 있습니다. 덮어쓰지 않습니다.')
    shutil.copytree(DEMO_FIXTURE, folder, dirs_exist_ok=True)
    print('데모 문서 준비:', folder)


def _ask_missing_secrets(config):
    """비어 있는 키를 숨김 입력으로 받아 .env에 저장한다."""
    settings = ROOT / '.env'
    settings.touch(exist_ok=True)
    current = {'SLACK_BOT_TOKEN': config.bot_token,
               'SLACK_APP_TOKEN': config.app_token,
               'OPENROUTER_API_KEY': config.api_key}
    for name in SECRET_NAMES:
        if current[name]:
            continue
        secret = getpass(name + ' (입력 숨김): ').strip()
        if not secret:
            raise ValueError(name + '이 필요합니다.')
        set_key(str(settings), name, secret)


def _ask_channel_id(client):
    """채널 링크나 ID를 입력받아 봇이 들어 있는 채널 ID를 돌려준다."""
    raw_value = input('Slack 채널 링크 또는 ID: ').strip()
    match = CHANNEL_ID_PATTERN.search(raw_value)
    if not match:
        raise ValueError('채널 링크 또는 C/G로 시작하는 채널 ID를 입력하세요.')
    channel_id = match[1]
    info = client.conversations_info(channel=channel_id)['channel']
    if not info.get('is_member'):
        raise ValueError('먼저 채널에 FastReqs 봇을 초대하세요.')
    return channel_id


def configure(args, config):
    """키를 입력받고 Slack 채널과 문서 폴더를 연결한다."""
    # Slack SDK는 이 명령에서만 필요하므로 늦게 불러온다.
    from slack_sdk import WebClient

    _ask_missing_secrets(config)
    config = Config.load()
    config.validate()
    client = WebClient(token=config.bot_token)
    workspace_id = client.auth_test()['team_id']
    channel_id = _ask_channel_id(client)
    raw_folder = input('네 Markdown 문서 폴더 경로: ').strip().strip('"')
    folder = Path(raw_folder).resolve()
    binding = StateStore(config.data_dir).bind(workspace_id, channel_id,
                                               folder)
    print('연결 저장 완료:', binding['channel'], binding['folder'],
          '(문서 변경 없음)')


def doctor(args, config):
    """설정과 연결된 문서 폴더를 점검한다(네트워크 호출 없음)."""
    config.validate()
    print('Python/환경설정 확인 완료. '
          '키 값과 네트워크 호출은 출력/실행하지 않습니다.')
    bindings = StateStore(config.data_dir).find_all('binding')
    for binding in bindings:
        read_documents(binding['folder'])
        print('문서 연결 확인:', binding['channel'], binding['folder'])
    if not bindings:
        print('채널 연결 필요: python -m fastreqs configure')


def status(args, config):
    """연결, 미결 후보, 검토 필요 문서, 복구 필요 작업을 보여준다."""
    store = StateStore(config.data_dir)
    for binding in store.find_all('binding'):
        print('연결:', binding['channel'], binding['folder'])
    for record in store.find_candidates():
        if record.status not in FINISHED_STATUSES:
            print(record.target, record.kind, record.status.value)
    for impact in store.find_all('impact'):
        if impact['status'] != IMPACT_ALIGNED:
            print('갱신 검토 필요:', impact['target'], impact['kind'])
    for operation in store.find_all('operation', state='recovery_required'):
        print('복구 필요:', operation['id'], list(operation['after']))


def replay_demo(args, config):
    """오프라인 모의 데모를 실행한다."""
    from .replay import replay

    replay()


def run_bot(args, config):
    """Slack 봇을 실행한다."""
    from .runtime import single_instance
    from .slack_bot import run

    with single_instance(config.data_dir):
        run(config)


COMMANDS = {
    'init-demo': init_demo,
    'configure': configure,
    'doctor': doctor,
    'status': status,
    'replay': replay_demo,
    'run': run_bot,
}


def main():
    """명령을 실행하고 종료 코드를 돌려준다."""
    args = _build_parser().parse_args()
    config = Config.load()
    try:
        if sys.version_info < MIN_PYTHON:
            raise ValueError('Python 3.10 이상이 필요합니다.')
        COMMANDS[args.command](args, config)
    except (ValueError, RuntimeError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('종료했습니다.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
