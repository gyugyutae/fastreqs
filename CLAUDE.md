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

## 5. 코드 원칙
- SOLID를 지킨다. 컨트롤러 계층(controller, controller_context, chat_collector, analysis_runner, approval_processor)은 slack_bot·slack_bolt·llm_client·httpx를 import하지 않고 `ports.py` 인터페이스에만 의존한다. 구체 클래스 조립은 `slack_bot.build_controller()`에서만.
- 코딩 표준: Google Python Style. 모든 공개 모듈·클래스·함수에 docstring(Args/Returns/Raises), 80자, 한 줄 한 문장, 매직 넘버는 이름 있는 상수, 복잡도 10 이하.
- 후보는 `records.CandidateRecord`, 상태는 `CandidateStatus`로 다룬다. dict·문자열 상태를 새로 쓰지 않는다.
- 네트워크 호출(LLM) 중에는 DB 트랜잭션이나 채널 잠금을 잡지 않는다.
- 승인·선택 전에는 문서를 바꾸지 않는다.

## 6. 검사 (변경 후 모두 통과해야 완료)
```sh
uv venv && uv pip install -r requirements-dev.txt   # 최초 1회
.venv/bin/python -m pytest -q                       # 아키텍처 규칙 + 기능 테스트
.venv/bin/ruff check fastreqs scripts tests
.venv/bin/python -m fastreqs replay                 # 오프라인 모의 데모
```

## 7. 커밋
- 커밋은 사용자 git 신원으로만 한다. Claude/AI 표시(`Co-Authored-By`, "Generated with") 금지.
- 사용자가 요청할 때만 커밋·푸시한다.
