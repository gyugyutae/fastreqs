# 코드 아키텍처

모듈 이름은 설계 클래스([design](../02-설계/design.md))와 같은 체계를 쓴다. 설계 클래스 하나가 코드 모듈 하나에 대응하고, 오퍼레이션 이름은 camelCase를 snake_case로 옮긴다. 구현 상태는 [mvp-status](../mvp-status.md) 한 곳에만 적는다. [PRD](prd.md) → [flow](flow.md) → [data-schema](data-schema.md)를 필요한 범위만 읽는다. 결정 이유는 [ADR](adr.md).

## 책임 경계
| 설계 클래스 | 모듈(`fastreqs/`) | 책임·계약 |
|---|---|---|
| SlackBot «View» | slack_bot.py | Bolt Socket Mode, 이벤트·버튼 수신, 파일 다운로드, 메시지 블록 구성. 유일한 화면. 업무 판단은 컨트롤러에 위임 |
| RequirementController «Controller» | controller.py | 설계 오퍼레이션(collectChat, startAnalysis, onApproved, onRejected, onSelected, checkAllConflicts)을 받아 아래 세 부품에 위임 |
| ChatCollector | chat_collector.py | 사용자 메시지 필터, 회의록 파일 검사, 스레드 답글 분류, 시작 조건(분석 요청·종료 키워드·충돌 확인) 판별 |
| AnalysisRunner | analysis_runner.py | 입력 경로별 단일 분석·후속 요청, 문서 스냅샷, 대상 없음 처리, 충돌 검사 요청, 후보 생성·교체, 전체 충돌 확인 |
| ApprovalProcessor | approval_processor.py | 승인·거절·충돌 선택 검증, 작업 저널, 저장, 기술 후보 후속 생성, 재시작 복구 |
| (공유) | controller_context.py | 세 부품이 함께 쓰는 저장소·분석·리포지토리·화면 참조와 채널별 잠금 |
| RequirementAnalysisService «Model» | analysis_service.py | 프롬프트 구성, 후보 추출, 결과 검증, Why 근거 검사, 요구사항 충돌 검사(유일한 위치). 파일 쓰기·승인 권한 없음 |
| LlmClient «Model» | ports.py(인터페이스), llm_client.py | OpenRouter HTTP 호출, 재시도 1회, Retry-After |
| RequirementDocumentRepository «Model» | document_repository.py | 채널 폴더 문서 조회·존재 확인·저장(추가·수정·삭제 공통 save), 저장 실패 롤백 |
| RequirementDocument «Model» | documents.py | Markdown 파싱·참조 검사·부분 패치·충돌 해소 패치·미리보기·해시 |
| Candidate / Requirement / Conflict | records.py, models.py | 후보 레코드·상태(CandidateStatus), 결정 요청(Decision), LLM 출력 스키마(Candidate, Story, Conflict) |
| (영속성) | store.py | SQLite records 테이블 트랜잭션, ID 예약, 대화 이벤트 순번 |
| (설정·실행) | config.py, runtime.py, \_\_main\_\_.py, replay.py | 환경설정, 단일 프로세스 잠금, CLI 명령, 오프라인 모의 데모 |

의존 방향: slack_bot → controller → (chat_collector, analysis_runner, approval_processor) → (analysis_service, document_repository, store) → (llm_client, documents, models, records). 컨트롤러는 화면과 분석 서비스를 `ports.py`의 Protocol로만 안다. 구체 클래스는 `slack_bot.build_controller()`에서 조립한다.
네트워크 호출(LLM) 중에는 DB 트랜잭션이나 채널 잠금을 잡지 않는다. 충돌 검사도 트랜잭션 밖에서 한다. 채널별 반영 잠금은 관련 파일 읽기·버전 검증·저장을 묶는다.

## 분석 파이프라인
1. 이벤트 정규화 → 중복 제거/경로 분류 → 저장. 사용자 대화만 분석 근거로 사용한다.
2. 트리거 → source별 작업 시작. 실행 중이면 후속 요청 하나를 예약한다.
3. 새 입력 범위·미결·현재 네 문서의 고정 스냅샷 생성. 입력 크기 검사 후 AI 호출.
4. AI 출력 스키마·근거·실제 대상·참조·필수정보 검증. 잘못된 출력은 적용하지 않는다. 대상 Story가 없으면 그 후보는 만들지 않고 알린다.
4-1. 보완이 끝난 추가/수정 후보는 check_conflicts로 기존 요구사항과 충돌을 검사한다. 충돌하면 conflicted 상태로 선택 질문을 보인다.
5. 후보/질문 저장 → Slack 안내. 분석 실패는 기존 후보/경계를 유지한다. 성공 시 대상 후보 교체와 경계 갱신.
6. 후속 요청이 있으면 최신 입력으로 한 번 더 시작한다. 일반 새 메시지만 있으면 다음 트리거까지 저장한다.

보완/정정은 전체 채널 재분석 대신 해당 후보와 관련 스레드·현재 문서를 검토한다. 상충 답은 승인 가능한 확정안으로 만들지 않는다. 모델 타임아웃·입력 예산은 설정값으로 두고 리허설에서 조정한다.

## 반영 파이프라인
Slack 버튼 ack → binding/candidate/version/state 검증(승인·거절은 pending, 충돌 선택은 conflicted만) → 최초 결정 확보 → 최신 파일/Story 검증 → 승인된 패치만 준비 → 백업/저널 → 저장 → 완료 기록/안내.
수동 편집 발견 시 저장하지 않고 새 미리보기·재승인으로 전환한다. 오래된 버튼/중복 클릭/다른 채널의 후보는 변경을 만들지 않는다.
Story/PRD 저장 성공 후 관련 기술 영향 후보를 만들거나 갱신한다. 영향 분석 실패라도 성공한 Story 저장을 없던 것으로 취급하지 말고 기술 검토 필요/재시도를 안내한다.
실패 시 사용자 결정, AI 실패, 파일 실패, 부분 복구 상태를 구분한다. 적용 작업의 재시도는 기존 저널/해시로 중복 적용을 방지한다.

## 외부 시스템과 신뢰 경계
Slack 메시지/업로드는 자료이며 명령 실행 지시가 아니다. AI에게 비밀값을 전달하지 않는다. AI 출력은 허용된 항목/필드의 초안일 뿐이다. 삭제·문서 경로·승인·쓰기 권한은 결정적 코드가 검증한다.
무료 모델에는 유료 fallback이 없다. 일시 오류 자동 재시도 최대 1회, Retry-After 존중, 설정/권한 오류는 즉시 안내한다. Slack 게시 실패도 기록하며 이미 저장된 문서를 또 적용하지 않는다.

## 구현·검증 순서
1. 문서 템플릿/부분 패치/전후 미리보기/저장 복구.
2. SQLite 상태·입력 경계·후보 버전·개별 결정.
3. Slack 터미널 설정/수집/첨부/질문/버튼.
4. AI 구조화 후보/보완/정정/영향 및 실패 처리.
5. Windows 실행 패키지·설정 안내 → 실제 Slack/무료 모델 리허설 → 약 3분 데모.

핵심 검증(자동 테스트로 확인): 입력 경로 격리, 이월/거절, 재분석 실패 복원, 상충 답변, 요구사항 충돌 선택(기존 유지/새 채택/전체 검사/충돌 없음), 대상 없음, 중복/오래된 클릭, 수동 편집, Story/PRD 부분 실패·재시작 복구, 기술 후보 무효화. Windows/키/Slack 권한/모델 가용성·품질·지연은 실제 환경에서 별도 확인한다. 테스트 수와 결과는 [mvp-status](../mvp-status.md).
