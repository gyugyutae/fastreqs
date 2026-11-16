# MVP 구현 상태

구현 상태는 이 문서 한 곳에만 적는다. 다른 문서는 이 문서를 링크한다.

기준일: 2026-11-17 (브랜치 `main`)

## 구현됨
- 설정·실행: 터미널 숨김 자격 입력, 채널/폴더 연결, Bolt Socket Mode, 단일 프로세스 보호, 재시작 복구.
- 입력: 일반 채널과 Markdown 회의록 스레드 분리, 분석 요청·종료 키워드, 후속 요청 병합.
- 후보: Who/What/Why 보완 질문, 상충 답변 선택 질문, 후보 정정(새 버전), 이월, 대상 없음 안내.
- 요구사항 충돌(UC-01·UC-03): 새 후보와 기존 요구사항 충돌 시 선택 질문, `@FastReqs 충돌 확인`으로 전체 확인, 고른 하나만 남기고 나머지 제외.
- 반영: Story/PRD 공동 승인, Spec/ADR 별도 승인, 수동 편집 감지 후 재승인, 작업 저널·롤백·재시작 판별.
- 모델: OpenRouter 무료 모델 JSON 출력, 일시 오류 재시도 1회, Retry-After 존중.

## 저장 방식
SQLite `records(kind, id, data)` 테이블 하나에 논리 객체를 JSON으로 저장한다. 상세는 [data-schema](final/data-schema.md).

## 검증한 것
- 자동 테스트 76개 통과: `python -m pytest -q` 또는 `python -m unittest discover -s tests`.
  - `tests/test_mvp.py` 23개: 전체 흐름과 충돌 선택.
  - `tests/test_analyzer.py` 12개: 모델 호출·재시도·충돌 검사.
  - `tests/test_units.py` 23개: 문서 함수, CRLF 문서, 저장소, 설정, SlackBot, 후보 레코드.
  - `tests/test_architecture.py` 18개: 설계-코드 이름 대응, 단일 위치 규칙, 코드 스멜 재발 방지, 의존 방향, 문서 일관성, ruff.
  - 이전 문서의 "25개(앱 20 + 하네스 5)" 중 하네스 테스트 5개는 이 저장소에 없다. 리팩토링 전 저장소의 테스트는 20개였다.
- 오프라인 모의 데모 `python -m fastreqs replay`: 보완 → 공동 승인 → 제외 → Spec 별도 승인 → 충돌 선택 → 전체 충돌 확인.
- 코딩 표준: `ruff check fastreqs scripts tests` 위반 0건(설정은 `pyproject.toml`).
- CI(GitHub Actions `.github/workflows/ci.yml`): main 푸시와 모든 PR에서 Ubuntu Python 3.10·3.13, Windows Python 3.13으로 ruff·테스트·모의 데모를 돌린다. 로컬에서는 macOS Python 3.13과 3.10으로 통과를 확인했다. 각 환경의 최신 CI 결과는 저장소 Actions 탭에서 본다.
- 실제 Slack 연결 데모: 2026-11-04 녹화([03-데모](03-데모/FastReqs_데모_2026-11-04.mp4)). 충돌 기능 추가 전 버전이다.

## 검증하지 않은 것
- 충돌 기능의 실제 Slack·무료 모델 동작(자동 테스트와 모의 데모만 통과).
- 무료 모델의 품질·가용성·지연. Windows 네이티브 실행은 CI(windows-latest) 자동 검사만 있고 실제 노트북 실행은 확인하지 않았다.
- 모의 데모는 실제 연결 검증을 대체하지 않는다.
