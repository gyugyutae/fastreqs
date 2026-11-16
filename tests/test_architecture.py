"""설계·코드·문서 규칙을 강제하는 아키텍처 테스트.

CLAUDE.md의 규칙을 사람이 기억하지 않아도 지켜지도록, 어기면 실패한다.
- 설계 오퍼레이션(camelCase)마다 같은 이름의 snake_case 메서드가 있다.
- 시퀀스 다이어그램의 호출 메시지는 클래스 다이어그램의 오퍼레이션이다.
- 충돌 검사, 화면 표시, 문서 쓰기는 각각 한 곳에만 있다.
- 컨트롤러 계층은 Slack·HTTP 구체 모듈을 import하지 않는다(DIP).
- 모든 코드 모듈은 code-architecture.md에 적혀 있다.
- 옛 상태 문구·금지 용어·테스트 개수를 문서에 적지 않는다.
- ruff 코딩 표준 위반이 0건이다.
"""

import ast
import importlib
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'fastreqs'
DOCS = ROOT / 'docs'
DESIGN = DOCS / '02-설계' / 'design.md'
ARCHITECTURE = DOCS / 'final' / 'code-architecture.md'
STATUS = DOCS / 'mvp-status.md'

# 설계 클래스 -> (모듈, 클래스 이름 또는 None=모듈 함수)
DESIGN_TO_CODE = {
    'SlackBot': ('slack_bot', 'SlackBot'),
    'RequirementController': ('controller', 'RequirementController'),
    'ChatCollector': ('chat_collector', 'ChatCollector'),
    'AnalysisRunner': ('analysis_runner', 'AnalysisRunner'),
    'ApprovalProcessor': ('approval_processor', 'ApprovalProcessor'),
    'RequirementAnalysisService': ('analysis_service',
                                   'RequirementAnalysisService'),
    'LlmClient': ('llm_client', 'OpenRouterClient'),
    'RequirementDocumentRepository': ('document_repository',
                                      'RequirementDocumentRepository'),
    'RequirementDocument': ('documents', None),
}
CONTROLLER_LAYER = ('controller', 'controller_context', 'chat_collector',
                    'analysis_runner', 'approval_processor')
FORBIDDEN_IN_CONTROLLER = ('slack_bot', 'slack_bolt', 'llm_client', 'httpx')
STATUS_VALUES = {'pending', 'clarifying', 'conflicted', 'applying',
                 'applied', 'rejected', 'replaced', 'stale', 'apply_failed'}
MAX_MODULE_LINES = 450
STATUS_PHRASES = re.compile(
    r'테스트\s*\d+\s*개|테스트 결과는 없다|구현 재개 요청 전까지 보류'
    r'|미검증 보류|충돌 답변')

MERMAID = re.compile(r'```mermaid\n(.*?)```', re.S)
CLASS_HEADER = re.compile(r'^\s*class (\w+)', re.M)
OPERATION = re.compile(r'^\s*\+(\w+)\(', re.M)
CALL_MESSAGE = re.compile(r'->>[+-]?\w+: (\w+)\(')


def to_snake(name):
    """camelCase를 snake_case로 바꾼다."""
    return re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()


def mermaid_blocks():
    """design.md의 Mermaid 블록 목록(첫 번째가 클래스 다이어그램)."""
    return MERMAID.findall(DESIGN.read_text(encoding='utf-8'))


def design_operations():
    """클래스 다이어그램에서 {클래스: [오퍼레이션]}을 읽는다."""
    class_diagram = mermaid_blocks()[0]
    operations = {}
    current = None
    for line in class_diagram.splitlines():
        header = CLASS_HEADER.match(line)
        if header:
            current = header[1]
            operations.setdefault(current, [])
            continue
        operation = OPERATION.match(line)
        if operation and current:
            operations[current].append(operation[1])
    return {name: ops for name, ops in operations.items() if ops}


def source_files():
    """패키지의 파이썬 파일 목록."""
    return sorted(PACKAGE.glob('*.py'))


def files_defining(function_name):
    """함수(메서드)를 정의한 파일 이름 집합."""
    found = set()
    for path in source_files():
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if (isinstance(node, ast.FunctionDef)
                    and node.name == function_name):
                found.add(path.name)
    return found


def files_calling(attribute):
    """`x.attribute(...)` 또는 `attribute(...)`를 호출하는 파일 이름 집합."""
    found = set()
    for path in source_files():
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, 'attr', None) or getattr(func, 'id', None)
            if name == attribute:
                found.add(path.name)
    return found


class DesignCodeNamingTest(unittest.TestCase):
    """설계 오퍼레이션 이름 = 코드 메서드 이름(snake_case)."""

    def test_every_design_class_is_mapped(self):
        unmapped = set(design_operations()) - set(DESIGN_TO_CODE)
        self.assertFalse(unmapped, f'코드 대응이 없는 설계 클래스: {unmapped}')

    def test_every_operation_has_snake_case_method(self):
        missing = []
        for design_class, operations in design_operations().items():
            module_name, class_name = DESIGN_TO_CODE[design_class]
            target = importlib.import_module('fastreqs.' + module_name)
            if class_name:
                target = getattr(target, class_name)
            missing += [f'{design_class}.{op} -> {to_snake(op)}'
                        for op in operations
                        if not hasattr(target, to_snake(op))]
        self.assertFalse(missing, f'설계에만 있는 오퍼레이션: {missing}')

    def test_operations_are_english_camel_case(self):
        for operations in design_operations().values():
            for operation in operations:
                self.assertRegex(operation, r'^[a-z][A-Za-z]*$')

    def test_sequence_messages_are_class_operations(self):
        known = {op for ops in design_operations().values() for op in ops}
        unknown = set()
        for diagram in mermaid_blocks()[1:]:
            unknown |= set(CALL_MESSAGE.findall(diagram)) - known
        self.assertFalse(unknown, f'클래스 다이어그램에 없는 메시지: {unknown}')

    def test_operation_defined_in_one_view_only(self):
        operations = design_operations()
        view_ops = {op for op in operations['SlackBot']
                    if op.startswith(('show', 'ask', 'propose', 'notify'))}
        for design_class, ops in operations.items():
            if design_class != 'SlackBot':
                self.assertFalse(view_ops & set(ops),
                                 f'{design_class}가 화면 오퍼레이션을 가짐')


class SingleResponsibilityLocationTest(unittest.TestCase):
    """같은 일은 한 곳에서만 한다."""

    def test_conflict_check_defined_only_in_analysis_service(self):
        # ports.py는 인터페이스, replay.py는 서비스를 상속한 데모용 대체.
        allowed = {'analysis_service.py', 'ports.py', 'replay.py'}
        self.assertLessEqual(files_defining('check_conflicts'), allowed)

    def test_llm_called_only_by_analysis_service(self):
        self.assertEqual({'analysis_service.py'}, files_calling('complete'))

    def test_view_methods_only_in_slack_bot(self):
        allowed = {'slack_bot.py', 'ports.py'}
        for name in ('show_added', 'show_removed', 'show_not_found',
                     'show_no_conflict', 'show_error', 'ask_question',
                     'ask_conflict_choice', 'propose_change'):
            self.assertLessEqual(files_defining(name), allowed, name)

    def test_documents_written_only_through_repository(self):
        self.assertEqual({'document_repository.py'},
                         files_calling('atomic_write'))


class CodeSmellTest(unittest.TestCase):
    """리팩토링으로 없앤 코드 스멜이 다시 생기지 않게 한다."""

    def test_no_large_module(self):
        # ② 큰 클래스: 모듈이 커지면 책임을 나눈다.
        large = [path.name for path in source_files()
                 if len(path.read_text(encoding='utf-8').splitlines())
                 > MAX_MODULE_LINES]
        self.assertFalse(large, f'{MAX_MODULE_LINES}줄 초과 모듈: {large}')

    def test_status_compared_as_enum(self):
        # ⑤ 기본 타입 선호: 상태는 CandidateStatus로만 비교한다.
        offenders = []
        for path in source_files():
            if path.name == 'records.py':
                continue
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare):
                    continue
                values = [node.left, *node.comparators]
                if any(isinstance(value, ast.Constant)
                       and value.value in STATUS_VALUES for value in values):
                    offenders.append(f'{path.name}:{node.lineno}')
        self.assertFalse(offenders, f'문자열 상태 비교: {offenders}')

    def test_no_single_letter_names(self):
        # 이름 규칙: 한 글자 변수 금지(쓰지 않는 값의 _ 제외).
        offenders = []
        for path in [*source_files(), *(ROOT / 'tests').glob('*.py'),
                     *(ROOT / 'scripts').glob('*.py')]:
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Name)
                        and isinstance(node.ctx, ast.Store)
                        and len(node.id) == 1 and node.id != '_'):
                    offenders.append(f'{path.name}:{node.lineno} {node.id}')
                if isinstance(node, ast.arg) and len(node.arg) == 1 \
                        and node.arg != '_':
                    offenders.append(f'{path.name}:{node.lineno} {node.arg}')
        self.assertFalse(offenders, f'한 글자 이름: {offenders}')

    def test_view_does_not_touch_state(self):
        # ⑪ 다른 클래스 지나치게 애용: SlackBot은 저장소를 직접 쓰지 않는다.
        tree = ast.parse((PACKAGE / 'slack_bot.py').read_text(
            encoding='utf-8'))
        slack_bot = next(node for node in tree.body
                         if isinstance(node, ast.ClassDef)
                         and node.name == 'SlackBot')
        names = {node.attr for node in ast.walk(slack_bot)
                 if isinstance(node, ast.Attribute)}
        self.assertFalse(names & {'store', 'repository', 'analyzer'})


class DependencyDirectionTest(unittest.TestCase):
    """컨트롤러 계층은 구체 Slack·HTTP 모듈을 모른다(DIP)."""

    def test_controller_layer_imports(self):
        for module in CONTROLLER_LAYER:
            text = (PACKAGE / f'{module}.py').read_text(encoding='utf-8')
            tree = ast.parse(text)
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    imported.add((node.module or '').split('.')[0])
                elif isinstance(node, ast.Import):
                    imported |= {alias.name.split('.')[0]
                                 for alias in node.names}
            bad = imported & set(FORBIDDEN_IN_CONTROLLER)
            self.assertFalse(bad, f'{module} imports {bad}')


class DocumentConsistencyTest(unittest.TestCase):
    """문서끼리, 문서와 코드가 같은 이름·상태를 쓴다."""

    def test_every_module_listed_in_code_architecture(self):
        text = ARCHITECTURE.read_text(encoding='utf-8').replace('\\_', '_')
        missing = [path.name for path in source_files()
                   if path.name != '__init__.py' and path.name not in text]
        self.assertFalse(missing, f'code-architecture에 없는 모듈: {missing}')

    def test_banned_phrases_absent(self):
        # 옛 상태 문구(보류·테스트 결과 없음), 금지 용어(충돌 답변),
        # 테스트 개수 같은 변하는 숫자를 어느 문서에도 쓰지 않는다.
        documents = [*(DOCS / 'final').glob('*.md'), DOCS / 'README.md',
                     ROOT / 'README.md', DESIGN, STATUS]
        offenders = [path.name for path in documents
                     if STATUS_PHRASES.search(
                         path.read_text(encoding='utf-8'))]
        self.assertFalse(offenders, f'상태·용어 규칙 위반 문서: {offenders}')


class CodingStandardTest(unittest.TestCase):
    """Google Python Style(ruff 설정) 위반 0건."""

    def test_ruff_passes(self):
        ruff = shutil.which('ruff') or shutil.which(
            'ruff', path=str(ROOT / '.venv' / 'bin'))
        if not ruff and os.environ.get('CI'):
            self.fail('CI에는 ruff가 설치되어 있어야 합니다.')
        if not ruff:
            self.skipTest('ruff 미설치: pip install -r requirements-dev.txt')
        result = subprocess.run(
            [ruff, 'check', 'fastreqs', 'scripts', 'tests'], cwd=ROOT,
            capture_output=True, text=True, encoding='utf-8',
            check=False)
        self.assertEqual(0, result.returncode, result.stdout)


if __name__ == '__main__':
    unittest.main()
