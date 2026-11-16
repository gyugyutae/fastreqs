"""Slack 경계 객체(설계의 SlackBot, «View»). 화면은 이 클래스 하나뿐이다.

사용자 -> SlackBot 메시지(설계 camelCase -> 코드 snake_case):
    sendChat(channelId, content)     -> send_chat()  (분석·충돌 확인 요청 포함)
    approve(candidateId)             -> approve()    (승인 버튼)
    reject(candidateId)              -> reject()     (거절 버튼)
    select(conflictId, keepId)       -> select()     (충돌 선택 버튼)

컨트롤러 -> SlackBot 메시지:
    proposeChange(candidate)         -> propose_change()
    askQuestion(candidate)           -> ask_question()
    askConflictChoice(candidate)     -> ask_conflict_choice()
    showAdded(candidate)             -> show_added()
    showRemoved(requirementId)       -> show_removed()
    showNotFound(requirementId)      -> show_not_found()
    showNoConflict()                 -> show_no_conflict()
    showError(message)               -> show_error()

Slack 메시지 형식(blocks)은 이 모듈에만 둔다. 업무 판단은 컨트롤러에
위임한다.
"""

import re
from urllib.parse import urlparse

import httpx
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from . import documents as doc
from .analysis_service import RequirementAnalysisService
from .approval_processor import is_final_decision
from .controller import ControllerSettings, RequirementController
from .document_repository import RequirementDocumentRepository
from .llm_client import OpenRouterClient
from .records import KEEP_NEW, KIND_CONFLICT, CandidateStatus, Decision
from .store import StateStore, binding_key

SECTION_TEXT_LIMIT = 2800
MESSAGE_TEXT_LIMIT = 3500
MAX_BLOCKS = 48
DOWNLOAD_TIMEOUT_SECONDS = 30
MAX_DOWNLOAD_BYTES = 1_000_000
HTTP_OK = 200
SLACK_HOST_SUFFIX = '.slack.com'
SELECT_ACTIONS = re.compile(r'^select_')
FAILURE_NOTICE = '처리 실패. 문서와 후보 상태를 확인하고 다시 요청해주세요.'
DEFAULT_QUESTION = 'Who/What/Why와 인수조건을 보완해주세요.'
DEFAULT_EVIDENCE = '승인된 Story의 변경 영향'
RESUME_NOTICE = ('FastReqs 수집을 재개했습니다. 중단 중 대화는 자동 수집하지 '
                 '않습니다. Markdown 회의록으로 보충할 수 있습니다.')


def _plain_section(text):
    """plain_text section 블록 하나를 만든다."""
    return {'type': 'section', 'text': {'type': 'plain_text', 'text': text}}


def _button(action_id, value, label):
    """버튼 요소 하나를 만든다."""
    return {'type': 'button', 'action_id': action_id, 'value': value,
            'text': {'type': 'plain_text', 'text': label}}


def download_file(client, token, file_info):
    """Slack 첨부 파일을 UTF-8 문자열로 내려받는다.

    토큰이 다른 호스트로 새지 않도록 slack.com HTTPS 주소만 허용하고
    리다이렉트를 따라가지 않는다.

    Raises:
        ValueError: 주소, 권한, 크기, 인코딩 조건을 어긴 경우.
    """
    info = client.files_info(file=file_info['id'])['file']
    url = info.get('url_private_download') or info.get('url_private')
    parsed = urlparse(url or '')
    if (parsed.scheme != 'https'
            or not (parsed.hostname or '').endswith(SLACK_HOST_SUFFIX)):
        raise ValueError('Slack 파일 다운로드 주소를 확인할 수 없습니다.')
    headers = {'Authorization': 'Bearer ' + token}
    data = bytearray()
    with httpx.Client(timeout=DOWNLOAD_TIMEOUT_SECONDS,
                      follow_redirects=False) as http:
        with http.stream('GET', url, headers=headers) as response:
            if response.status_code != HTTP_OK:
                raise ValueError('파일 다운로드 실패. '
                                 'files:read 권한을 확인해주세요.')
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > MAX_DOWNLOAD_BYTES:
                    raise ValueError('파일은 최대 1 MB입니다.')
    try:
        return bytes(data).decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('UTF-8 Markdown 파일만 지원합니다.') from None


class SlackBot:
    """Slack 메시지를 보내고 받는 화면 계층.

    Attributes:
        send: chat.postMessage와 같은 형태의 전송 함수.
        controller: 사용자 입력을 넘길 RequirementController.
        workspace_id: 연결된 Slack 워크스페이스 ID.
        download: 첨부 파일을 문자열로 내려받는 함수.
    """

    def __init__(self, send):
        """메시지 전송 함수를 주입받는다(테스트에서는 가짜 함수)."""
        self.send = send
        self.controller = None
        self.workspace_id = None
        self.download = None

    def _post(self, channel_id, text, thread=None, **options):
        """메시지를 보내고 ts를 돌려준다."""
        if thread:
            options['thread_ts'] = thread
        return self.send(channel_id, text, **options)['ts']

    def _post_with_buttons(self, channel_id, text, buttons, thread=None,
                           **options):
        """본문 블록과 버튼 줄이 있는 메시지를 보낸다.

        Raises:
            ValueError: 본문이 Slack 블록 한도를 넘는 경우.
        """
        blocks = [_plain_section(text[start:start + SECTION_TEXT_LIMIT])
                  for start in range(0, len(text), SECTION_TEXT_LIMIT)]
        blocks.append({'type': 'actions', 'elements': buttons})
        if len(blocks) > MAX_BLOCKS:
            raise ValueError('미리보기가 너무 깁니다. 후보 내용을 줄여주세요.')
        return self._post(channel_id, text[:MESSAGE_TEXT_LIMIT], thread,
                          blocks=blocks, **options)

    # ----- 컨트롤러 -> 사용자 -----

    def notify(self, channel_id, text, thread=None):
        """일반 안내 메시지를 보낸다."""
        self._post(channel_id, text, thread)

    def ask_question(self, channel_id, candidate, thread=None):
        """askQuestion: 보완 질문(또는 상충 답변 선택 질문)을 보인다.

        Returns:
            게시한 메시지 ts.
        """
        question = candidate.payload.get('question') or DEFAULT_QUESTION
        text = (f'유저스토리 보완 질문\n{question}\n'
                '이 스레드에 누구나 답할 수 있습니다.')
        return self._post(channel_id, text, thread)

    def ask_conflict_choice(self, channel_id, candidate, thread=None):
        """askConflictChoice: 충돌한 요구사항 중 살릴 하나를 고르게 한다.

        Returns:
            게시한 메시지 ts.
        """
        conflict = candidate.conflict
        stories = doc.parse_sections(candidate.docs[doc.USER_STORIES])
        lines = ['요구사항 충돌: 둘 중 하나만 남깁니다. 고르면 바로 문서에 '
                 '반영하고 나머지는 제외합니다.', '이유: ' + conflict['reason']]
        lines += [stories.get(story_id, story_id).strip()
                  for story_id in candidate.conflict_ids]
        value = f'{candidate.id}:{candidate.version}:'
        buttons = [_button(f'select_{index}', value + story_id,
                           story_id + ' 유지')
                   for index, story_id in enumerate(candidate.conflict_ids)]
        if candidate.kind != KIND_CONFLICT:
            lines.append('새 요구사항:\n' + doc.render_story(
                candidate.target, candidate.payload['story']).strip())
            buttons.append(_button('select_new', value + KEEP_NEW,
                                   '새 요구사항 채택'))
        return self._post_with_buttons(channel_id, '\n\n'.join(lines),
                                       buttons, thread)

    def propose_change(self, channel_id, candidate, thread=None):
        """proposeChange: 변경 전후 미리보기와 승인·거절 버튼을 보인다.

        Returns:
            게시한 메시지 ts.

        Raises:
            ValueError: 미리보기가 Slack 블록 한도를 넘는 경우.
        """
        value = f'{candidate.id}:{candidate.version}'
        buttons = [_button('approve', value, '승인'),
                   _button('reject', value, '거절')]
        options = {}
        if thread and candidate.status == CandidateStatus.PENDING:
            options['reply_broadcast'] = True
        return self._post_with_buttons(channel_id,
                                       self._render_proposal(candidate),
                                       buttons, thread, **options)

    @staticmethod
    def _render_proposal(candidate):
        """제안 본문(종류·대상·근거·전후 비교)을 만든다."""
        payload = candidate.payload
        action = payload.get('action', '변경')
        if candidate.kind == doc.KIND_STORY:
            scope = 'Story/PRD 공동 승인'
        else:
            scope = '기술 문서 별도 승인'
        evidence = payload.get('evidence', DEFAULT_EVIDENCE)
        diff = doc.render_diff(candidate.docs, candidate.plan)
        return (f'{candidate.kind} {action} · {candidate.target}\n'
                f'{scope}\n근거: {evidence}\n{diff}')

    def show_added(self, channel_id, candidate, thread=None):
        """showAdded: 추가·수정 반영 완료를 알린다."""
        names = ', '.join(candidate.plan)
        self._post(channel_id, f'{candidate.target} 반영 완료: {names}',
                   thread)

    def show_removed(self, channel_id, requirement_id, thread=None):
        """showRemoved: 요구사항 제외 완료를 알린다."""
        self._post(channel_id, f'{requirement_id} 제외 완료. 이전 내용은 '
                   '작업 기록에 보존했습니다.', thread)

    def show_not_found(self, channel_id, requirement_id, thread=None):
        """showNotFound: 변경 대상 요구사항이 문서에 없음을 알린다."""
        self._post(channel_id, f'{requirement_id} 요구사항을 문서에서 찾지 '
                   '못했습니다. 문서는 변경하지 않았습니다.', thread)

    def show_no_conflict(self, channel_id):
        """showNoConflict: 전체 충돌 확인 결과 충돌이 없음을 알린다."""
        self._post(channel_id, '요구사항 충돌이 없습니다.')

    def show_error(self, channel_id, source_id, detail, thread=None):
        """showError: 분석 실패를 [다시 분석] 버튼과 함께 알린다."""
        text = f'분석 실패: {detail}\n입력과 미결 제안은 보존했습니다.'
        block_text = text + ' 다시 분석할 수 있습니다.'
        blocks = [
            _plain_section(block_text[:SECTION_TEXT_LIMIT]),
            {'type': 'actions',
             'elements': [_button('retry', source_id, '다시 분석')]},
        ]
        self._post(channel_id, text, thread, blocks=blocks)

    # ----- 사용자 -> 컨트롤러 -----

    def register_handlers(self, app, controller, workspace_id, bot_token):
        """Bolt 앱에 이벤트·버튼 핸들러를 등록한다."""
        self.controller = controller
        self.workspace_id = workspace_id

        def download(file_info):
            return download_file(app.client, bot_token, file_info)

        self.download = download
        app.event('message')(self.send_chat)
        app.event('app_mention')(self.send_chat)
        for action_id, handler in (('approve', self.approve),
                                   ('reject', self.reject),
                                   ('retry', self.retry)):
            app.action(action_id)(handler)
        app.action(SELECT_ACTIONS)(self.select)

    def send_chat(self, event):
        """sendChat: 채널 메시지를 컨트롤러의 대화 수집으로 넘긴다."""
        self.controller.collect_chat(self.workspace_id, event, self.download)

    def approve(self, ack, body, client):
        """approve: 승인 버튼을 처리한다."""
        ack()
        self._decide(body, client, self.controller.on_approved)

    def reject(self, ack, body, client):
        """reject: 거절 버튼을 처리한다."""
        ack()
        self._decide(body, client, self.controller.on_rejected)

    def select(self, ack, body, client):
        """select: 충돌 선택 버튼을 처리한다."""
        ack()
        keep = body['actions'][0]['value'].rsplit(':', 1)[1]
        self._decide(body, client,
                     lambda decision: self.controller.on_selected(decision,
                                                                  keep))

    def retry(self, ack, body, client):
        """[다시 분석] 버튼을 처리한다."""
        ack()
        channel_id = body['channel']['id']
        binding_id = binding_key(self.workspace_id, channel_id)
        try:
            self.controller.retry_analysis(binding_id,
                                           body['actions'][0]['value'])
        except Exception:  # noqa: BLE001 - 사용자에게 실패를 알린다.
            client.chat_postEphemeral(channel=channel_id,
                                      user=body['user']['id'],
                                      text=FAILURE_NOTICE)

    def _decide(self, body, client, handle):
        """버튼 값으로 Decision을 만들어 컨트롤러에 넘기고 결과를 보인다."""
        channel_id = body['channel']['id']
        user_id = body['user']['id']
        candidate_id, version = body['actions'][0]['value'].split(':')[:2]
        decision = Decision(binding_key(self.workspace_id, channel_id),
                            candidate_id, int(version), user_id)
        try:
            result = handle(decision)
            client.chat_postEphemeral(channel=channel_id, user=user_id,
                                      text=result)
            if is_final_decision(result):
                client.chat_update(channel=channel_id,
                                   ts=body['message']['ts'], text=result,
                                   blocks=[_plain_section(result)])
        except Exception:  # noqa: BLE001 - 사용자에게 실패를 알린다.
            client.chat_postEphemeral(channel=channel_id, user=user_id,
                                      text=FAILURE_NOTICE)


def build_controller(store, config, bot_id, send):
    """구체 클래스를 조립해 컨트롤러와 SlackBot을 만든다(조립 루트)."""
    bot = SlackBot(send)
    analyzer = RequirementAnalysisService(OpenRouterClient(config))
    repository = RequirementDocumentRepository(store)
    settings = ControllerSettings(endings=config.endings, bot_id=bot_id)
    controller = RequirementController(store, analyzer, repository, bot,
                                       settings)
    return controller, bot


def run(config):
    """Slack Socket Mode로 FastReqs를 실행한다.

    Raises:
        ValueError: 설정이나 채널 연결이 없는 경우.
    """
    config.validate()
    app = App(token=config.bot_token)
    identity = app.client.auth_test()
    workspace_id, bot_id = identity['team_id'], identity['user_id']
    store = StateStore(config.data_dir)
    bindings = store.find_all('binding', workspace=workspace_id)
    if not bindings:
        raise ValueError('먼저 python -m fastreqs configure 를 실행하세요.')

    def send(channel, text, **options):
        return app.client.chat_postMessage(channel=channel, text=text,
                                           **options)

    controller, bot = build_controller(store, config, bot_id, send)
    controller.recover_pending_operations()
    bot.register_handlers(app, controller, workspace_id, config.bot_token)
    for binding in bindings:
        bot.notify(binding['channel'], RESUME_NOTICE)
    controller.resume_open_candidates()
    print('Slack 연결 완료. Ctrl+C로 종료합니다.', flush=True)
    SocketModeHandler(app, config.app_token).start()
