"""요구사항 Markdown 문서(설계의 RequirementDocument)를 다루는 순수 함수.

DB가 아니라 네 Markdown 파일이 기준 자료다. 이 모듈은 파일을 읽고,
ID 단위 섹션을 찾아 바꾸고, 바뀐 결과를 미리보기로 만든다.

사용 예:
    docs = read_documents(folder)
    patch = build_patch(docs, candidate, 'US-004')
    print(render_diff(docs, patch))
"""

import difflib
import hashlib
import os
import re
import tempfile
from pathlib import Path

PRD = 'prd.md'
USER_STORIES = 'user-stories.md'
SPEC = 'spec.md'
ADR = 'adr.md'
DOCUMENT_NAMES = (PRD, USER_STORIES, SPEC, ADR)

KIND_STORY = 'story'
KIND_SPEC = 'spec'
KIND_ADR = 'adr'

ADR_ACCEPTED = '- 상태: Accepted'
ADR_SUPERSEDED = '- 상태: Superseded'
DEFAULT_PRIORITY = '보통'
POLICY_SECTION = '\n## 변경 원칙'
SCOPE_SECTION = '## 현재 제품 범위\n'
STORY_FIELDS = ('Who', 'What', 'Why', '인수조건')
ADR_FIELD_LABELS = (
    ('배경', 'context'),
    ('결정', 'decision'),
    ('대안', 'alternatives'),
    ('결과', 'consequences'),
)

SECTION_HEADER = re.compile(r'^## ((?:US|ADR)-\d{3,})(?:[^\n]*)\n', re.M)
NEXT_SECTION = re.compile(r'^## ', re.M)
PRD_TABLE_HEADER = re.compile(r'^\| Story ID \| 기능 \| 우선순위 \|', re.M)
TABLE_DIVIDER = re.compile(r'^\|---[^\n]*\n', re.M)


def compute_digest(content):
    """문자열의 SHA-256 해시를 돌려준다."""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def atomic_write(path, content):
    """같은 폴더의 임시 파일을 거쳐 파일을 원자적으로 교체한다.

    Args:
        path: 저장할 파일 경로.
        content: 저장할 UTF-8 문자열.
    """
    path = Path(path)
    descriptor, temp_name = tempfile.mkstemp(
        prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def read_text(path):
    """파일을 UTF-8 문자열로 읽는다(줄바꿈 변환 없음)."""
    return Path(path).read_bytes().decode('utf-8')


def read_documents(folder, validate_structure=True):
    """폴더의 네 요구사항 문서를 읽는다.

    Args:
        folder: 문서 폴더 경로.
        validate_structure: True면 문서 형식까지 검사한다.

    Returns:
        {파일명: 내용} 딕셔너리.

    Raises:
        ValueError: 심볼릭 링크이거나 형식이 잘못된 경우.
    """
    documents = {}
    for name in DOCUMENT_NAMES:
        path = Path(folder) / name
        if path.is_symlink():
            raise ValueError('문서 심볼릭 링크는 지원하지 않습니다.')
        documents[name] = read_text(path)
    if validate_structure:
        validate_documents(documents)
    return documents


def parse_sections(text):
    """'## US-001' 같은 ID 섹션을 {ID: 섹션 본문}으로 나눈다.

    Raises:
        ValueError: 같은 ID가 두 번 나오는 경우.
    """
    result = {}
    for match in SECTION_HEADER.finditer(text):
        section_id = match[1]
        if section_id in result:
            raise ValueError('중복 문서 ID: ' + section_id)
        following = NEXT_SECTION.search(text[match.end():])
        stop = match.end() + following.start() if following else len(text)
        result[section_id] = text[match.start():stop]
    return result


def _story_row_pattern(story_id):
    """PRD 범위 표에서 Story 행을 찾는 정규식을 돌려준다."""
    return re.compile(r'^\| ' + re.escape(story_id) + r' \|[^\n]*\n?', re.M)


def validate_documents(documents):
    """네 문서의 필수 구조와 Story-PRD 참조를 검사한다.

    Raises:
        ValueError: 제목, 섹션, 필수 필드, PRD 참조가 없는 경우.
    """
    for name in DOCUMENT_NAMES:
        if not documents[name].startswith('# '):
            raise ValueError(name + ': 제목이 필요합니다.')
        parse_sections(documents[name])
    prd = documents[PRD]
    if SCOPE_SECTION not in prd:
        raise ValueError('PRD에 ## 현재 제품 범위 섹션이 필요합니다.')
    if not PRD_TABLE_HEADER.search(prd):
        raise ValueError('PRD 범위 표 형식: | Story ID | 기능 | 우선순위 |')
    stories = parse_sections(documents[USER_STORIES])
    for story_id, body in stories.items():
        if not all('- ' + key + ':' in body for key in STORY_FIELDS):
            raise ValueError(story_id + ': Story 필수 필드가 없습니다.')
        if not _story_row_pattern(story_id).search(prd):
            raise ValueError(story_id + ': PRD 참조가 없습니다.')


def replace_section(text, section_id, replacement):
    """ID 섹션을 바꾸고, 없으면 '변경 원칙' 섹션 앞에 넣는다."""
    body = parse_sections(text).get(section_id)
    if body:
        return text.replace(body, replacement, 1)
    position = text.find(POLICY_SECTION)
    if position < 0:
        position = len(text)
    head = text[:position]
    separator = '' if head.endswith('\n') else '\n'
    return head + separator + replacement + text[position:]


def render_story(story_id, story):
    """Story 딕셔너리를 user-stories.md 섹션 문자열로 만든다."""
    criteria = ''.join('  - ' + item + '\n' for item in story['acceptance'])
    return (f"## {story_id} {story['title']}\n"
            f"- Who: {story['who']}\n"
            f"- What: {story['what']}\n"
            f"- Why: {story['why']}\n"
            f'- 인수조건:\n{criteria}\n')


def _render_prd_row(story_id, story, priority):
    """PRD 범위 표의 한 행을 만든다. 표를 깨는 '|'는 '/'로 바꾼다."""
    title = story['title'].replace('|', '/')
    what = story['what'].replace('|', '/')
    return f'| {story_id} | {title} — {what} | {priority} |\n'


def _update_prd_scope(prd, story_id, candidate):
    """PRD 범위 표에서 Story 행을 추가·수정·삭제한다."""
    old_row = _story_row_pattern(story_id).search(prd)
    if candidate['action'] == 'delete':
        new_row = ''
    else:
        priority = DEFAULT_PRIORITY
        if old_row:
            priority = old_row[0].strip().split('|')[-2].strip()
        new_row = _render_prd_row(story_id, candidate['story'], priority)
    if old_row:
        return prd[:old_row.start()] + new_row + prd[old_row.end():]
    if not new_row:
        return prd
    divider = TABLE_DIVIDER.search(prd)
    if not divider:
        raise ValueError('PRD 표 구분선이 없습니다.')
    return prd[:divider.end()] + new_row + prd[divider.end():]


def _plan_story(documents, candidate, story_id):
    """Story와 PRD 범위를 함께 바꾸는 패치를 만든다."""
    if candidate['action'] == 'delete':
        story_section = ''
    else:
        story_section = render_story(story_id, candidate['story'])
    return {
        USER_STORIES: replace_section(
            documents[USER_STORIES], story_id, story_section),
        PRD: _update_prd_scope(documents[PRD], story_id, candidate),
    }


def _plan_spec(documents, candidate, story_id):
    """Spec 문서의 Story 계약 섹션을 바꾸는 패치를 만든다."""
    if candidate['delete']:
        section = ''
    else:
        section = f"## {story_id} 구현 계약\n{candidate['content']}\n\n"
    return {SPEC: replace_section(documents[SPEC], story_id, section)}


def _supersede_adr(text, previous_id, new_id):
    """기존 ADR을 Superseded로 바꾸고 새 결정 ID를 남긴다."""
    body = parse_sections(text).get(previous_id)
    if not body or ADR_ACCEPTED not in body:
        raise ValueError('대체할 활성 ADR이 없습니다.')
    replaced = body.replace(ADR_ACCEPTED, ADR_SUPERSEDED)
    return text.replace(body, replaced + f'- 새 결정: {new_id}\n\n', 1)


def _plan_adr(documents, candidate, story_id):
    """새 ADR을 추가하고 필요하면 기존 ADR을 대체하는 패치를 만든다."""
    change = candidate['change']
    adr_id = candidate['adr_id']
    previous_id = change['supersedes']
    text = documents[ADR]
    if previous_id:
        text = _supersede_adr(text, previous_id, adr_id)
    fields = ''.join(f'- {label}: {change[key]}\n'
                     for label, key in ADR_FIELD_LABELS)
    superseded = f'- 대체한 결정: {previous_id}\n' if previous_id else ''
    body = (f"## {adr_id} — {change['title']}\n"
            f'{ADR_ACCEPTED}\n'
            f'- 관련 스토리: {story_id}\n'
            f'{fields}{superseded}\n')
    return {ADR: replace_section(text, adr_id, body)}


_PLANNERS = {
    KIND_STORY: _plan_story,
    KIND_SPEC: _plan_spec,
    KIND_ADR: _plan_adr,
}


def build_patch(documents, candidate, target_id, kind=KIND_STORY):
    """후보를 반영한 새 문서 내용(패치)을 만든다.

    Args:
        documents: 현재 {파일명: 내용}.
        candidate: 후보 payload 딕셔너리.
        target_id: 대상 Story ID.
        kind: 'story', 'spec', 'adr' 중 하나.

    Returns:
        바뀌는 파일만 담은 {파일명: 새 내용}.

    Raises:
        ValueError: 결과 문서가 형식 검사를 통과하지 못한 경우.
    """
    patch = _PLANNERS[kind](documents, candidate, target_id)
    validate_documents({**documents, **patch})
    return patch


DELETE_PAYLOAD = {'action': 'delete', 'story': None}


def check_references(documents, payload):
    """후보가 가리키는 ADR이 대체 가능한 활성 결정인지 검사한다.

    Raises:
        ValueError: 대체할 활성 ADR이 없는 경우.
    """
    adr_change = payload.get('adr_change')
    if not adr_change or not adr_change['supersedes']:
        return
    previous = parse_sections(documents[ADR]).get(adr_change['supersedes'], '')
    if ADR_ACCEPTED not in previous:
        raise ValueError('대체할 활성 ADR이 없습니다.')


def build_resolution_patch(documents, payload, target_id, removed_ids):
    """충돌 선택 결과(살릴 것 반영 + 나머지 삭제)를 한 패치로 만든다.

    Args:
        documents: 현재 {파일명: 내용}.
        payload: 살릴 새 후보 payload. 기존 요구사항을 살리면 None.
        target_id: 새 후보의 Story ID.
        removed_ids: 삭제할 기존 Story ID 목록.

    Returns:
        바뀌는 파일만 담은 {파일명: 새 내용}.
    """
    current = dict(documents)
    patch = {}
    changes = [(payload, target_id)] if payload else []
    changes += [(DELETE_PAYLOAD, story_id) for story_id in removed_ids]
    for change, story_id in changes:
        step = build_patch(current, change, story_id)
        current.update(step)
        patch.update(step)
    return patch


def render_diff(documents, patch):
    """패치 전후를 unified diff 문자열로 만든다."""
    diffs = []
    for name, new_text in patch.items():
        lines = difflib.unified_diff(
            documents[name].splitlines(True), new_text.splitlines(True),
            fromfile=name + ' (이전)', tofile=name + ' (이후)', n=2)
        diffs.append(''.join(lines))
    return '\n'.join(diffs)
