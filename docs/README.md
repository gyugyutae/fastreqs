# FastReqs 프로젝트 문서 지도

소프트웨어공학개론 3조 FastReqs: Slack 대화에서 결정된 요구사항을 감지해 User Story·PRD·Spec 문서에 승인/거절 클릭만으로 반영하고, 서로 충돌하는 요구사항은 하나만 고르게 하는 봇.

문서마다 역할이 하나다. 역할이 겹치는 새 문서를 만들지 말고 아래 문서를 고친다(CLAUDE.md 4절).
"참조" 열의 하네스는 이 저장소에서 Claude가 작업할 때 쓰는 장치(CLAUDE.md, design-reviewer 서브에이전트, 테스트, CI)를 뜻한다.

## 작업 규칙과 검사 (저장소 루트)

| 파일 | 역할 | 참조: 누가, 언제 |
|---|---|---|
| [CLAUDE.md](../CLAUDE.md) | 규칙의 유일한 원본(설계 이름, 단일 위치, 용어, 문서 일관성, 코딩 표준, 코드 스멜·SOLID, 검사, 커밋) | Claude: 이 저장소에서 세션을 시작할 때마다 자동으로 읽음. 팀원: 규칙 확인 |
| [.claude/agents/design-reviewer.md](../.claude/agents/design-reviewer.md) | 테스트로 판정할 수 없는 규칙과 설계·문서 일관성을 검토하는 방법 | Claude: 구조·이름·설계 문서가 바뀌는 변경을 마치고 커밋하기 전 |
| [tests/test_architecture.py](../tests/test_architecture.py) | 기계적으로 판정되는 규칙 검사 | `pytest` 실행 때(로컬, CI) |
| [pyproject.toml](../pyproject.toml) | ruff 코딩 표준 설정(줄 길이, docstring, 복잡도, 인자 수 등) | ruff 실행 때(로컬, CI) |
| [.github/workflows/ci.yml](../.github/workflows/ci.yml) | 3개 환경(Ubuntu Python 3.10·3.13, Windows Python 3.13)에서 ruff·테스트·모의 데모 실행 | GitHub: main 푸시·PR마다 자동, 수동 실행 가능 |
| [README.md](../README.md) | 설치·실행·데모 방법 | 사람: 처음 실행할 때, 시연 준비할 때 |
| [demo-fixtures/](../demo-fixtures) | 시연용 가상 제품 문서 4개와 회의록 입력 | 테스트·`replay`가 매번 읽음, `init-demo`가 복사 |

## 설계 (02-설계)

| 파일 | 역할 | 참조: 누가, 언제 |
|---|---|---|
| [design.md](02-설계/design.md) | 기준 설계: 이름 규칙, 용어, 클래스 목록, 클래스·시퀀스 다이어그램(Mermaid 원본), 시퀀스 작성 규칙 | 테스트: 매 실행마다 Mermaid 블록을 읽어 코드 메서드와 대조. Claude: 클래스·오퍼레이션을 바꿀 때(CLAUDE.md 1절). 검토자: 관련 절 |
| [FastReqs_클래스다이어그램.png](02-설계/FastReqs_클래스다이어그램.png), [시퀀스 UC-01](02-설계/FastReqs_시퀀스_UC-01.png)·[02](02-설계/FastReqs_시퀀스_UC-02.png)·[03](02-설계/FastReqs_시퀀스_UC-03.png) | design.md를 렌더링한 그림 | 사람: 발표·보고서. Claude: 다이어그램을 바꾸면 다시 생성 |
| [FastReqs_UI설계(이전).pdf](<02-설계/FastReqs_UI설계(이전).pdf>) | (이전) 실습 UI 설계 화면 스케치. 화면 흐름만 유효. 다른 점: 한국어 오퍼레이션 이름(대응은 design.md 3절), 승인 후 충돌 검사(지금은 충돌 검사 후 제안), 충돌 화면이 "알리고 종료"(지금은 선택 질문), /conflict 명령(지금은 @FastReqs 충돌 확인) | 사람: 화면 참고. 하네스는 참조하지 않음 |

## 요구·동작·저장 (final)

| 파일 | 역할 | 참조: 누가, 언제 |
|---|---|---|
| [prd.md](final/prd.md) | 제품 목적·범위(왜, 무엇을, 무엇을 안 하나) | Claude: 기능 범위를 바꿀 때 첫 번째로 고침. 테스트: 상태 문구 검사 |
| [user-stories.md](final/user-stories.md) | FastReqs 기능 FR-US-001~011의 Who/What/Why·인수조건 | Claude: 범위 변경 때 같은 FR-US ID로 |
| [spec.md](final/spec.md) | 같은 FR-US ID의 구현 계약(입출력·예외·검증) | Claude: 범위 변경 때. 검토자: 동작이 계약과 맞는지 |
| [flow.md](final/flow.md) | 사용자 입장의 동작 순서(입력 경로, 보완, 충돌, 결정, 실패) | Claude: 범위 변경 때. 시퀀스 그림에서 생략한 흐름의 기준 |
| [adr.md](final/adr.md) | 기술 결정과 이유 FR-ADR-001~006 | Claude: 결정이 바뀔 때 새 ID로 추가 |
| [code-architecture.md](final/code-architecture.md) | 설계 클래스 ↔ 코드 모듈 책임 표, 분석·반영 파이프라인 | 테스트: 모든 모듈이 표에 있는지 매번 검사. Claude: 모듈 추가·이름 변경 때 |
| [data-schema.md](final/data-schema.md) | 실제 저장 방식(records 테이블), 상태값과 불변식 | Claude: 저장 구조·상태를 바꿀 때 |
| [mvp-status.md](mvp-status.md) | 구현·검증 상태의 유일한 기록(된 것, 확인 안 된 것) | 상태를 말하는 문서(prd, spec, adr, code-architecture, data-schema, README)가 이곳을 링크. 테스트: 금지 문구·테스트 개수를 적지 않았는지 검사 |

## 과제 산출물

| 파일 | 역할 | 참조: 누가, 언제 |
|---|---|---|
| [04-리팩토링/리팩토링보고서.md](04-리팩토링/리팩토링보고서.md) | 실습 12 리팩토링 보고서 원본, 설계 ↔ 코드 대응표(제출물 2) | Claude: 오퍼레이션이 바뀌면 대응표를 고침. 사람: 제출 |
| [04-리팩토링/PBL_리팩토링보고서.hwpx](04-리팩토링/PBL_리팩토링보고서.hwpx) | 위 보고서를 PBL 양식에 맞춘 한글 파일 | 사람: 제출. 하네스는 참조하지 않음 |
| [01-요구분석/FastReqs_중간발표.pptx](01-요구분석/FastReqs_중간발표.pptx) | 중간 발표 자료(관리계획·기술조사·유스케이스 다이어그램 포함) | 사람: 발표 기록. 하네스는 참조하지 않음 |
| [01-요구분석/품질시나리오보고서.pptx](01-요구분석/품질시나리오보고서.pptx) | 품질 시나리오 Q1~Q5(중간발표에 없는 세부 포함) | 사람: 품질 목표 확인. 하네스는 참조하지 않음 |
| [03-데모/FastReqs_데모_2026-11-04.mp4](03-데모/FastReqs_데모_2026-11-04.mp4) | 실제 Slack 시연 녹화(충돌 기능 추가 전) | mvp-status의 검증 근거 |

지운 문서(내용이 다른 문서와 겹치거나 더 이상 쓰지 않음)는 git 기록에서 꺼낼 수 있다: 이전 설계 pptx·hwp, UC-01 시퀀스 가이드·클래스 목록(design.md로 병합), 중간발표를 나눈 pptx 3개(관리계획서·기술조사·유스케이스다이어그램. 관리계획서의 "GitHub으로 버전 관리" 한 줄 말고는 중간발표에 모두 있음), UI 설계 hwpx(같은 내용의 pdf 유지), 3분 데모 대본(흐름은 README·PRD에 있고, 사전 준비 목록은 README 데모 절로 옮김).

![클래스 다이어그램](02-설계/FastReqs_클래스다이어그램.png)
