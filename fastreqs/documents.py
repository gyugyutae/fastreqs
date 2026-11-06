"""ID-scoped Markdown patches. Files, never database projections, are authoritative."""
import hashlib
import os
import re
import tempfile
from pathlib import Path

NAMES = ('prd.md', 'user-stories.md', 'spec.md', 'adr.md')

def digest(content): return hashlib.sha256(content.encode('utf-8')).hexdigest()

def atomic_write(path, content):
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as handle:
            handle.write(content); handle.flush(); os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)

def read(folder, validate_structure=True):
    result = {}
    for name in NAMES:
        path = Path(folder) / name
        if path.is_symlink(): raise ValueError('문서 심볼릭 링크는 지원하지 않습니다.')
        result[name] = path.read_bytes().decode('utf-8')
    if validate_structure: validate(result)
    return result

def sections(text):
    matches = list(re.finditer(r'^## ((?:US|ADR)-\d{3,})(?:[^\n]*)\n', text, re.M))
    result = {}
    for m in matches:
        if m[1] in result: raise ValueError('중복 문서 ID: ' + m[1])
        end = re.search(r'^## ', text[m.end():], re.M)
        stop = m.end() + end.start() if end else len(text)
        result[m[1]] = text[m.start():stop]
    return result

def validate(docs):
    for name in NAMES:
        if not docs[name].startswith('# '): raise ValueError(name + ': 제목이 필요합니다.')
        sections(docs[name])
    if '## 현재 제품 범위\n' not in docs['prd.md']: raise ValueError('PRD에 ## 현재 제품 범위 섹션이 필요합니다.')
    if not re.search(r'^\| Story ID \| 기능 \| 우선순위 \|', docs['prd.md'], re.M):
        raise ValueError('PRD 범위 표 형식: | Story ID | 기능 | 우선순위 |')
    stories = sections(docs['user-stories.md'])
    for sid, body in stories.items():
        if not all('- ' + key + ':' in body for key in ('Who', 'What', 'Why', '인수조건')):
            raise ValueError(sid + ': Story 필수 필드가 없습니다.')
        if not re.search(r'^\| ' + sid + r' \|', docs['prd.md'], re.M): raise ValueError(sid + ': PRD 참조가 없습니다.')

def replace_section(text, sid, replacement):
    body = sections(text).get(sid)
    if body: return text.replace(body, replacement, 1)
    # Insert before trailing policy section, preserving it.
    position = text.find('\n## 변경 원칙')
    position = position if position >= 0 else len(text)
    return text[:position] + ('' if text[:position].endswith('\n') else '\n') + replacement + text[position:]

def story_body(sid, story):
    return (f"## {sid} {story['title']}\n- Who: {story['who']}\n- What: {story['what']}\n"
            f"- Why: {story['why']}\n- 인수조건:\n" + ''.join('  - ' + x + '\n' for x in story['acceptance']) + '\n')

def plan(docs, candidate, target, kind='story'):
    output = {}
    if kind == 'story':
        value = candidate
        replacement = '' if value['action'] == 'delete' else story_body(target, value['story'])
        output['user-stories.md'] = replace_section(docs['user-stories.md'], target, replacement)
        text = docs['prd.md']; pattern = r'^\| ' + re.escape(target) + r' \|[^\n]*\n?'
        old = re.search(pattern, text, re.M)
        row = '' if value['action'] == 'delete' else f"| {target} | {value['story']['title'].replace('|', '/')} — {value['story']['what'].replace('|', '/')} | 보통 |\n"
        if old:
            if row:
                priority = old[0].strip().split('|')[-2].strip()
                row = row.replace('| 보통 |', '| ' + priority + ' |')
            text = text[:old.start()] + row + text[old.end():]
        elif row:
            header = re.search(r'^\|---[^\n]*\n', text, re.M)
            if not header: raise ValueError('PRD 표 구분선이 없습니다.')
            text = text[:header.end()] + row + text[header.end():]
        output['prd.md'] = text
    elif kind == 'spec':
        replacement = '' if candidate['delete'] else f"## {target} 구현 계약\n{candidate['content']}\n\n"
        output['spec.md'] = replace_section(docs['spec.md'], target, replacement)
    else:
        c = candidate['change']; aid = candidate['adr_id']; previous = c['supersedes']
        text = docs['adr.md']
        if previous:
            body = sections(text).get(previous)
            if not body or '- 상태: Accepted' not in body: raise ValueError('대체할 활성 ADR이 없습니다.')
            text = text.replace(body, body.replace('- 상태: Accepted', '- 상태: Superseded') + f'- 새 결정: {aid}\n\n', 1)
        body = (f"## {aid} — {c['title']}\n- 상태: Accepted\n- 관련 스토리: {target}\n"
                + ''.join(f'- {label}: {c[key]}\n' for label,key in [('배경','context'),('결정','decision'),('대안','alternatives'),('결과','consequences')])
                + (f'- 대체한 결정: {previous}\n' if previous else '') + '\n')
        output['adr.md'] = replace_section(text, aid, body)
    validate({**docs, **output})
    return output

def preview(docs, output):
    import difflib
    return '\n'.join(''.join(difflib.unified_diff(docs[name].splitlines(True), new.splitlines(True), fromfile=name+' (이전)', tofile=name+' (이후)', n=2)) for name,new in output.items())
