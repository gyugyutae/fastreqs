"""대화 수집 부품(RequirementController.collectChat의 구현).

Slack 메시지를 입력 경로(채널 대화 또는 회의록 스레드)에 저장하고, 시작
조건(분석 요청, 종료 키워드, 충돌 확인 요청)을 만나면 컨트롤러에 알린다.
"""

from . import documents as doc
from .records import CandidateStatus
from .store import binding_key

MEETING_FILE_SUFFIX = '.md'
MAX_MEETING_FILE_BYTES = 1_000_000
ANALYZE_KEYWORD = '분석'
CONFLICT_KEYWORD = '충돌'
ALLOWED_SUBTYPES = (None, 'file_share')


def _is_user_message(event):
    """봇·시스템 메시지가 아닌 사용자 메시지인지 돌려준다."""
    return (not event.get('bot_id') and bool(event.get('user'))
            and event.get('subtype') in ALLOWED_SUBTYPES)


def read_meeting_file(files, download):
    """첨부 파일 한 개를 검사하고 내용을 돌려준다.

    Raises:
        ValueError: 파일 개수, 확장자, 크기 조건을 어긴 경우.
    """
    if len(files) != 1:
        raise ValueError('메시지당 .md 파일 하나만 올려주세요.')
    file_info = files[0]
    name = file_info.get('name', '').lower()
    if (not name.endswith(MEETING_FILE_SUFFIX)
            or file_info.get('size', 0) > MAX_MEETING_FILE_BYTES):
        raise ValueError('UTF-8 .md, 최대 1 MB만 지원합니다.')
    content = download(file_info)
    too_large = len(content.encode('utf-8')) > MAX_MEETING_FILE_BYTES
    if too_large or not content.strip():
        raise ValueError('빈 파일 또는 1 MB 초과 파일입니다.')
    return content


class ChatCollector:
    """Slack 메시지를 저장하고 시작 조건을 판별한다.

    Attributes:
        context: 공유 협력 객체(ControllerContext).
        start_analysis: 분석을 시작하는 함수(source_id, correction).
        check_all_conflicts: 전체 충돌 확인을 시작하는 함수(binding_id).
    """

    def __init__(self, context, start_analysis, check_all_conflicts):
        """협력 객체와 시작 함수를 주입받는다."""
        self.context = context
        self.start_analysis = start_analysis
        self.check_all_conflicts = check_all_conflicts

    @property
    def store(self):
        """상태 저장소."""
        return self.context.store

    def _mentions_bot_with(self, text, keyword):
        """봇 멘션과 키워드가 함께 있는 명시 요청인지 돌려준다."""
        return f'<@{self.context.settings.bot_id}>' in text and keyword in text

    def collect(self, workspace_id, event, download=None):
        """Slack 메시지 하나를 처리한다.

        Args:
            workspace_id: Slack 워크스페이스 ID.
            event: Slack message 이벤트 딕셔너리.
            download: 첨부 파일을 문자열로 내려받는 함수.
        """
        channel_id = event.get('channel')
        binding_id = binding_key(workspace_id, str(channel_id))
        if not self.store.find_all('binding', id=binding_id):
            return
        if not _is_user_message(event) or not event.get('ts'):
            return
        if event.get('files'):
            self._save_meeting_file(binding_id, channel_id, event, download)
            return
        text = event.get('text', '')
        if (not event.get('thread_ts')
                and self._mentions_bot_with(text, CONFLICT_KEYWORD)):
            self.check_all_conflicts(binding_id)
            return
        related, thread, file_source = self._find_thread_context(
            binding_id, event.get('thread_ts'), text)
        if related:
            self._handle_candidate_reply(related, event, thread)
            return
        self._record_message(binding_id, file_source, event)

    def _save_meeting_file(self, binding_id, channel_id, event, download):
        """업로드된 .md 회의록을 새 입력 경로로 저장한다."""
        ts = event['ts']
        view = self.context.view
        try:
            content = read_meeting_file(event['files'], download)
            with self.store.transaction():
                source, is_new = self.store.get_or_create_source(
                    binding_id, ts, content)
        except Exception as error:  # noqa: BLE001 - 사용자에게 안내한다.
            if isinstance(error, ValueError):
                detail = str(error)
            else:
                detail = '다운로드/권한을 확인해주세요.'
            view.notify(channel_id, '파일 확인 실패: ' + detail, thread=ts)
            return
        if is_new:
            self.context.notify_source(
                source, '회의록을 저장했습니다. 이 스레드에서 '
                '@FastReqs 분석해줘를 요청해주세요.')
        else:
            view.notify(channel_id, '같은 회의록이 이미 있습니다. 기존 '
                        '스레드에서 분석해주세요: ' + str(source['thread']),
                        thread=ts)

    def _find_thread_context(self, binding_id, thread, text):
        """스레드 답글이 어떤 후보·회의록에 속하는지 찾는다.

        Returns:
            (관련 후보 목록, 실제 스레드 ts, 회의록 입력 경로 또는 None).
        """
        if not thread:
            return [], thread, None
        related = self.store.find_candidates(binding=binding_id,
                                             thread=thread)
        files = self.store.find_all('source', binding=binding_id,
                                    thread=thread)
        file_source = files[0] if files else None
        if (related or not file_source
                or self._mentions_bot_with(text, ANALYZE_KEYWORD)):
            return related, thread, file_source
        waiting = [record for record in
                   self.context.pending_candidates(file_source['id'])
                   if record.status == CandidateStatus.CLARIFYING]
        if len(waiting) == 1:
            return waiting, waiting[0].thread, file_source
        if len(waiting) > 1:
            self.context.notify_source(
                file_source, '보완 후보가 여러 개입니다. 해당 보완 질문 '
                '메시지에 답글로 답해주세요.')
        return related, thread, file_source

    def _handle_candidate_reply(self, related, event, thread):
        """후보 스레드의 답글을 보완·정정 또는 새 변경 요청으로 처리한다."""
        active = [record for record in related if record.is_active]
        record = active[-1] if active else related[-1]
        source = self.store.get('source', record.source)
        text = event.get('text', '')
        is_new = self.store.add_event(source['id'], event['ts'],
                                      event['user'], text, thread=thread)
        if not is_new:
            return
        if record.kind != doc.KIND_STORY:
            self.context.notify_source(
                source, '기술 제안·충돌 선택은 버튼으로 처리하고, 관련 '
                '요구사항 정정은 새 분석으로 요청해주세요.')
            return
        if not record.is_active:
            self._reopen_as_new_request(source['id'], event['ts'],
                                        record.target, text)
            self.start_analysis(source['id'])
            return
        correction = {**record.payload, 'id': record.id, 'answer': text,
                      'previous_status': record.status.value}
        self.start_analysis(source['id'], correction)

    def _reopen_as_new_request(self, source_id, ts, story_id, text):
        """처리가 끝난 후보 스레드의 답글을 일반 대화 요청으로 바꾼다."""
        with self.store.transaction():
            event = self.store.get('event', source_id + ':' + ts)
            event['thread'] = None
            event['text'] = f'관련 Story {story_id}의 새 변경 요청: {text}'
            self.store.put('event', event)

    def _record_message(self, binding_id, file_source, event):
        """일반 대화를 저장하고 분석 요청·종료 키워드면 분석을 시작한다."""
        source = file_source
        if source is None:
            with self.store.transaction():
                source, _ = self.store.get_or_create_source(binding_id)
        text = event.get('text', '')
        if not self.store.add_event(source['id'], event['ts'],
                                    event['user'], text):
            return
        is_ending = (not source['content'] and any(
            word in text for word in self.context.settings.endings))
        if self._mentions_bot_with(text, ANALYZE_KEYWORD) or is_ending:
            self.start_analysis(source['id'])
