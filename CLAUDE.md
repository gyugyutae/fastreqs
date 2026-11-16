# FastReqs 저장소 지침

우선순위: 사용자 지시 > 이 파일 > `docs/02-설계/design.md` > `docs/final/*` > 다른 문서. 내용이 서로 다르면 높은 쪽을 따르고, 다른 점을 결과 보고에 적는다.
아래 규칙 대부분은 `tests/test_architecture.py`가 강제한다. 테스트를 끄거나 예외 목록을 넓혀서 통과시키지 않는다. 규칙을 바꿔야 하면 사용자에게 먼저 묻고, 이 파일·설계·테스트를 함께 고친다.

## 1. 설계와 코드 이름
- 기준 설계는 `docs/02-설계/design.md` 하나다. pptx/hwp는 이력 자료이며 고치지 않는다.
- 설계 클래스는 영문 PascalCase, 오퍼레이션은 영문 camelCase. 코드는 같은 클래스 이름과, 오퍼레이션을 snake_case로 옮긴 메서드 이름을 쓴다(collectChat → `collect_chat`). 사용자에게 보이는 문구만 한국어.
- 오퍼레이션을 추가·변경하면 design.md의 클래스 다이어그램, 해당 시퀀스, 코드, 리팩토링 보고서 대응표를 함께 바꾼다. 새 설계 클래스는 테스트의 `DESIGN_TO_CODE`에도 넣는다.
- 시퀀스 다이어그램은 UC-01 가이드(`FastReqs-유스케이스-설계/UC-01-sequence-guide.md`)를 따른다: `objectName:ClassName` 헤더, 호출 실선·반환 점선, 분기는 alt(승인/거절은 안쪽 alt), 활성 막대는 실행 구간만, 사용자 대기 구간은 막대 없음.
- 다이어그램을 바꾸면 PNG를 다시 만든다: design.md의 Mermaid 블록을 mermaid-cli로 렌더링해 `docs/02-설계/FastReqs_클래스다이어그램.png`, `FastReqs_시퀀스_UC-0N.png`를 덮어쓴다.

## 2. 한 곳에서만 하는 일
- 요구사항 충돌 검사: `RequirementAnalysisService.check_conflicts`만. 다른 클래스에 충돌 판단 로직을 만들지 않는다.
- LLM 호출(`complete`): 분석 서비스만.
- 사용자 화면(show_*/ask_*/propose_*): `SlackBot`만. View 클래스를 새로 만들지 않는다.
- 문서 쓰기: `RequirementDocumentRepository.save`만(추가·수정·삭제·충돌 해소 공통).
- 대화 입력: `collect_chat` 하나. 유스케이스마다 입력 경로나 컨트롤러를 새로 만들지 않는다.

## 3. 용어
- 충돌(conflict): 두 요구사항을 동시에 만족할 수 없음. 선택 질문으로 사용자가 고른 하나만 남기고 나머지를 제외한다.
- 상충 답변(answers_contradict): 보완 질문 답변끼리 다름. 선택형 보완 질문으로 다시 묻는다. 문서에 "충돌 답변"이라고 쓰지 않는다.

## 4. 문서 일관성
- 구현·검증 상태(테스트 수, 검증 범위)는 `docs/mvp-status.md`에만 적는다. 다른 문서는 링크한다. 테스트를 추가·삭제하면 mvp-status의 수를 고친다.
- 모듈을 추가·이름 변경하면 `docs/final/code-architecture.md` 책임 표를 고친다.
- 기능 범위를 바꾸면 prd → user-stories/spec(같은 FR-US ID) → flow → adr 순서로 함께 고친다.

## 5. 코딩 표준 (Google Python Style, `pyproject.toml`의 ruff가 강제)
- 모든 공개 모듈·클래스·함수에 docstring. 공개 함수는 Args/Returns/Raises를 적는다.
- 한 줄 80자, 한 줄에 한 문장(`a; b`, `if x: return` 금지). import는 파일 맨 위, 표준·외부·내부 순.
- 이름: 함수·변수 snake_case, 클래스 PascalCase, 상수 UPPER_CASE. 함수는 동사+명사(`read_documents`). 한 글자 변수 금지(반복 변수·`with ... as` 포함). 쓰지 않는 값만 `_`.
- 매직 넘버·반복 문자열은 이름 있는 상수로.
- 함수 복잡도 10 이하, 인자 5개 이하(넘으면 데이터 클래스로 묶는다), 함수당 문장 50개 이하. 규칙에 걸리면 기준을 올리지 말고 함수를 나눈다.
- 테스트 코드도 같은 표준을 따른다(docstring·매직 넘버만 예외).

## 6. 코드 스멜·SOLID (리팩토링 때 없앤 것을 다시 만들지 않는다)
| 규칙 | 지키는 방법 | 강제 |
|---|---|---|
| ① 긴 메서드 | 복잡도 10·문장 50개를 넘으면 도우미 함수로 나눈다 | ruff C901, PLR0915 |
| ② 큰 클래스 | 모듈 450줄 이하. 넘으면 책임별 부품으로 나눈다(컨트롤러 → ChatCollector/AnalysisRunner/ApprovalProcessor처럼) | test_no_large_module |
| ③ 긴 파라미터 리스트 | 인자 5개 이하. 함께 다니는 값은 `Decision`, `AnalysisRound`, `CandidateOptions`, `ControllerSettings` 같은 데이터 클래스로. bool 플래그 인자 대신 메서드를 나눈다 | ruff PLR0913 |
| ④ 유사 데이터 그룹 | 같이 다니는 값 묶음은 한 함수·한 데이터 클래스로(`put_impact`) | 리뷰 |
| ⑤ 기본 타입 선호 | 후보는 `CandidateRecord`, 상태는 `CandidateStatus`. 새 dict 레코드·문자열 상태 비교 금지 | test_status_compared_as_enum |
| ⑥ 여러 이유로 바뀌는 클래스 | 화면·흐름 조정·분석·저장을 한 클래스에 섞지 않는다 | 단일 위치 테스트 |
| ⑦ 여러 클래스 동시 수정 | 2절의 "한 곳에서만 하는 일"을 지킨다 | 단일 위치 테스트 |
| ⑨ Switch/If 문장 | 종류별 분기는 딕셔너리 디스패치(`_PLANNERS`)로. 새 종류는 함수만 추가 | 복잡도 |
| ⑩ 중복 코드 | 같은 판별식·리터럴·함수를 두 번 쓰면 함수·상수로 뽑는다. 일회성 스크립트를 루트에 두지 않는다(`scripts/`) | 리뷰 |
| ⑪ 다른 클래스 지나치게 애용 | SlackBot은 store·repository·analyzer를 직접 쓰지 않고 컨트롤러 메서드만 부른다 | test_view_does_not_touch_state |
| S 단일 책임 | 1·2절, ②⑥ | 위 테스트 |
| O 개방 폐쇄 | 새 문서 종류·화면은 기존 함수를 고치지 않고 추가로 확장(`_PLANNERS`, `RequirementView` 구현) | 리뷰 |
| L 리스코프 치환 | 데모·테스트용 대체 객체는 실제 클래스를 상속하고 같은 시그니처를 지킨다 | 기능 테스트 |
| I 인터페이스 분리 | `ports.py`의 Protocol은 쓰는 쪽에 필요한 메서드만 | 리뷰 |
| D 의존관계 역전 | 컨트롤러 계층(controller, controller_context, chat_collector, analysis_runner, approval_processor)은 slack_bot·slack_bolt·llm_client·httpx를 import하지 않고 `ports.py`에만 의존. 구체 클래스 조립은 `slack_bot.build_controller()`에서만 | test_controller_layer_imports |

"리뷰"로 표시한 규칙은 테스트로 잡을 수 없으므로 변경을 마치기 전에 직접 점검하고 결과 보고에 적는다.

## 7. 동작 원칙
- 네트워크 호출(LLM) 중에는 DB 트랜잭션이나 채널 잠금을 잡지 않는다.
- 승인·선택 전에는 문서를 바꾸지 않는다.
- 새 기능·버그 수정에는 실패를 잡는 테스트를 함께 넣는다. 테스트를 추가·삭제하면 `docs/mvp-status.md`의 테스트 수를 고친다(테스트가 검사한다).

## 8. 검사 (변경 후 모두 통과해야 완료)
- CI(`.github/workflows/ci.yml`)가 main 푸시(그리고 PR)마다 Ubuntu Python 3.10·3.13과 Windows Python 3.13으로 아래 세 검사를 돌린다. CI가 빨간색이면 완료가 아니다. 검사를 끄거나 매트릭스를 줄여서 통과시키지 않는다.
- Windows에서도 돌아가야 한다. 파일을 읽고 쓸 때는 항상 `encoding='utf-8'`을 지정한다(Windows 기본 인코딩은 UTF-8이 아니다).
- 구조·이름·설계 문서가 바뀌는 변경을 마치면 커밋 전에 `design-reviewer` 서브에이전트(`.claude/agents/design-reviewer.md`)로 검토하고, 지적을 고치거나 고치지 않는 이유를 결과 보고에 적는다. 6절의 "리뷰" 규칙(④ ⑩ O I)은 이 검토로 확인한다.
```sh
uv venv && uv pip install -r requirements-dev.txt   # 최초 1회
.venv/bin/python -m pytest -q                       # 아키텍처 규칙 + 기능 테스트
.venv/bin/ruff check fastreqs scripts tests
.venv/bin/python -m fastreqs replay                 # 오프라인 모의 데모
```
Windows에서는 `.venv/bin/`을 `.venv\Scripts\`로 바꿔 실행한다.

## 9. 커밋·푸시
- 커밋은 사용자 git 신원으로만 한다. Claude/AI 표시(`Co-Authored-By`, "Generated with") 금지.
- 사용자가 요청할 때만 커밋·푸시한다.
- 작업 브랜치는 main 하나를 쓰고 main에 바로 푸시한다(브랜치 보호 없음, 2026-11-17 사용자 결정). 그래서 CI는 푸시를 막지 않고 푸시 뒤에 결과를 낸다. 푸시 전에 8절 검사를 로컬에서 모두 통과시키고, 푸시 후 `gh run list -R gyugyutae/fastreqs -L 1`로 CI 결과를 확인한다. 실패하면 바로 고쳐 다시 푸시하고 사용자에게 알린다.
- 저장소 소유 계정은 `gyugyutae`다. 이 컴퓨터의 gh 기본 활성 계정은 `gyutaetae`라서 쓰기 권한이 없다(push 403, unarchive 권한 오류). 푸시 전에 `gh api repos/gyugyutae/fastreqs --jq '{archived, push: .permissions.push}'`로 확인하고, push가 false면 `gh auth switch -u gyugyutae`로 바꿔 푸시한 뒤 `gh auth switch -u gyutaetae`로 되돌린다.
- 저장소는 보관(archive, 읽기 전용)하지 않고 일반 상태로 운영한다(2026-11-17 사용자 결정). 보관하지 않는다. 혹시 보관 상태로 바뀌어 있으면 사용자에게 알리고 해제 여부를 묻는다.

## 10. 사용자와 소통
- 사용자에게는 한국어로 답한다.
- 이 저장소의 과제 산출물(보고서)은 Markdown(`docs/04-리팩토링/`)이 원본이다. HWP 양식이 필요하면 macOS에서는 HWP 바이너리를 쓸 수 없으므로 HWPX로 만든다.
