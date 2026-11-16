# UC-01 요구사항 추가 — 클래스 목록

> 2026-11-16 갱신. UC-01·02·03을 합친 전체 클래스 목록과 다이어그램은 [docs/02-설계/design.md](../docs/02-설계/design.md)에 있다. 오퍼레이션 이름은 영문 camelCase로 통일했고, 코드 메서드는 같은 이름의 snake_case다.

## 작성 근거와 범위
사용자가 작성한 UC-01-sequence-starter.drawio의 최종 Page-2와 UC-01-sequence-starter-Page-2.drawio.png를 기준으로 작성했다. 앱 구현을 그대로 역설계한 목록이 아니라, 유스케이스 1의 시퀀스에서 도출한 설계 클래스 목록이다. 코드와 원본 다이어그램은 변경하지 않는다.

## 도출 방법
1. 시스템 내부 라이프라인에서 클래스 후보를 찾는다. 외부 액터인 사용자는 제외한다.
2. 각 객체가 받는 호출 메시지에서 해당 클래스의 오퍼레이션을 찾는다. 보내는 메시지는 다른 클래스에 대한 의존성을 뜻한다.
3. 반환 메시지는 결과 데이터로 구분한다. ‘저장 성공’, ‘충돌 결과’를 메서드로 추가하지 않는다.
4. 작업 사이에 기억해야 하는 정보를 속성 후보로 둔다. 매개변수가 모두 속성이 되는 것은 아니다.
5. 클래스별 책임을 한 문장으로 설명하고, 메시지와 책임이 일치하는지 확인한다.

## 시퀀스에서 직접 도출한 클래스 4개
| 클래스 | 책임 | 주요 오퍼레이션 | 코드 |
| --- | --- | --- | --- |
| 슬랙봇 (SlackBot) | Slack 이벤트를 전달하고 제안·충돌 선택·완료를 사용자에게 표시 | sendChat(channelId, content), approve(candidateId), reject(candidateId), select(conflictId, keepId), proposeChange(candidate), askConflictChoice(candidate), showAdded(candidate), showRemoved(requirementId) | slack_bot.py::SlackBot |
| 요구사항 컨트롤러 (RequirementController) | 대화 수집부터 분석·충돌 검사·제안·결정·저장까지 유스케이스의 진행을 조정 | collectChat(channelId, content), startAnalysis(channelId, trigger), onApproved(candidateId, userId), onRejected(candidateId, userId), onSelected(conflictId, keepId, userId) | controller.py::RequirementController |
| 요구사항 분석서비스 (RequirementAnalysisService) | 새 대화에서 요구사항 후보를 추출하고 기존 요구사항과 의미 충돌을 검사(충돌 검사의 유일한 위치) | extractRequirements(newChat), checkConflicts(existing, candidate) | analysis_service.py::RequirementAnalysisService |
| 요구사항 문서 리포지토리 (RequirementDocumentRepository) | 채널에 연결된 로컬 문서의 기존 요구사항 조회와 승인된 변경 저장 | findRequirements(channelId), exists(channelId, requirementId), save(channelId, change) | document_repository.py::RequirementDocumentRepository |

오퍼레이션은 그림의 수신 메시지에 맞췄다. 이전 한국어 이름과의 대응: 대화전송→sendChat, 대화수집→collectChat, 분석시작→startAnalysis, 요구사항추출→extractRequirements, 기존요구사항조회→findRequirements, 충돌검사→checkConflicts, 추가제안→proposeChange, 충돌알림→askConflictChoice(알림 후 종료 대신 선택 질문), 추가승인→approve, 승인처리→onApproved, 요구사항추가→save, 추가완료알림→showAdded(candidate). 속성은 그림만으로 확정할 수 없으므로 후보로 표시한다.

## 주요 반환값
- extractRequirements → 요구사항 후보(Candidate 목록)
- findRequirements → 기존 요구사항 문서
- checkConflicts → Conflict 목록(비어 있으면 충돌 없음)
- save → 저장 결과(실패 시 SaveFailedError)

## 클래스 간 협력
- 슬랙봇 → 컨트롤러: 대화 수집, 분석 시작, 승인 전달
- 컨트롤러 → 분석서비스: 후보 추출, 충돌 검사
- 컨트롤러 → 리포지토리: 문서 조회, 요구사항 추가
- 컨트롤러 → 슬랙봇: 제안, 충돌 선택 질문, 완료 알림
이 관계는 호출 의존성이다. 상속·합성 관계나 다중성은 이 시퀀스만으로 확정하지 않는다.

## 필요할 때 확장할 데이터 클래스
| 후보 클래스 | 속성 후보 | 도출 근거 |
|---|---|---|
| 요구사항 후보 (RequirementCandidate) | 후보ID, 내용, 대상문서, 처리상태 | 추출 결과를 제안한 뒤 승인 시점에 다시 찾아야 함 |
| 요구사항 문서 (RequirementDocument) | 문서경로, 요구사항목록 | 조회·저장하는 데이터의 구조를 별도 객체로 표현할 때 필요 |

두 데이터 클래스는 현재 그림의 독립 라이프라인이 아니다. 상세 클래스 설계가 요구될 때 추가하며, 이번 기본 목록은 4개로 유지한다. 후보ID와 확정된 요구사항ID의 동일 여부는 이번 범위에서 정하지 않는다.

## 과제 설명 예시
“시퀀스 다이어그램의 시스템 내부 참여 객체에서 네 개의 클래스를 도출했다. 각 객체가 수신하는 호출 메시지를 오퍼레이션으로 배정했고, 사용자 액터와 반환값은 클래스나 메서드에서 제외했다. 속성은 대화 수집과 승인 대기 등 처리 사이에 유지해야 하는 정보를 중심으로 제안했다.”
