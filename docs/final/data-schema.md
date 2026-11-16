# 데이터 스키마

저장 계약. 구현 상태는 [mvp-status](../mvp-status.md) 한 곳에만 적는다. Markdown이 기준 자료이며 아래 DB 테이블은 대화·작업·이력만 관리한다. DB에서 문서 전체를 생성하지 않는다. 동작은 [flow](flow.md), 이유는 [ADR](adr.md).

## 문서 계약
채널마다 사용자가 지정한 서로 다른 폴더에 prd.md/user-stories.md/spec.md/adr.md를 둔다. UTF-8 및 고정 기본 섹션을 검증한다.
- Story: US ID, 제목, Who, What, Why, 인수조건.
- PRD: 목표/배경 + Story ID를 참조하는 기능 범위.
- Spec: 고유 항목 ID + 관련 US ID + 동작/입출력/권한/예외/검증.
- ADR: ADR ID + 관련 US ID + 상태/배경/대안/결정/결과/대체 ID.
문서 버전은 원본 파일 바이트의 SHA-256이다. 항목 버전은 정규화한 해당 항목 내용의 해시다. 삭제된 ID도 내부 예약 목록에 남긴다. 무관 섹션은 그대로 보존한다.

## 공통 타입
내부 ID는 UUID hex, 시간은 UTC ISO-8601, Slack ts는 문자열(부동소수점 변환 금지). records.data는 검증된 JSON이다. workspace/channel 연결 ID가 모든 사용자 자료의 격리 경계다. 키/토큰은 DB 및 분석 로그에 저장하지 않는다.

## 실제 저장 방식
SQLite 테이블은 `records(kind, id, data)` 하나다. `data`는 JSON이고 `kind`가 논리 테이블 역할을 한다. 별도 SQL 테이블로 나누지 않은 이유는 MVP 규모에서 스키마 변경 비용을 줄이기 위해서다(코드: `store.py`).

| kind | 주요 필드 | 제약·용도 |
|---|---|---|
| binding | id(workspace/channel), workspace, channel, folder | 채널당 폴더 하나, 같은 폴더를 다른 채널에 연결 금지 |
| source | id, binding, thread, content, cursor, busy, followup, corrections | 채널 경로 하나(`…/channel`), 회의록은 내용 해시별 경로(`…/file/<sha256>`). cursor는 마지막 성공 분석 순번. busy/followup/corrections가 분석 실행 상태(별도 analysis_runs 없음) |
| event | id(source:ts), source, seq, user, text, ts, thread | 같은 ts 중복 저장 금지, source 안에서 seq 증가 |
| candidate | `records.CandidateRecord` 필드: id, binding, source, kind(story/spec/adr/conflict), target, status, payload, docs, plan, version, thread, message, story_hash, conflict, actor, decided_at | 버튼에 id/version 결합. 결정 결과(actor, decided_at)를 후보에 함께 저장(별도 decisions 없음) |
| impact | id(binding:kind:story), binding, target, kind, status | 기술 문서 영향 추적. 거절해도 needs_review 유지 |
| operation | id, binding, candidate, state, before, after, actor, time | 저장 작업 저널. before/after에 파일 전체 내용을 보관해 재시작 때 비교 |
| reserved | id, binding, prefix(US/ADR), value | 삭제 후에도 ID 재사용 금지 |

payload: Story 후보는 `models.Candidate` 직렬화(action, target_id, story, evidence, question, spec_change, adr_change, why_evidence, answers_contradict). Spec 후보는 {content, delete}, ADR 후보는 {change, adr_id}. 전체 충돌 확인 후보(kind=conflict)는 payload가 비어 있고 conflict에 {requirement_ids, reason}을 둔다. AI가 임의 경로나 실행 코드를 지정할 수 없다.

## 상태와 불변식
- 후보(CandidateStatus): pending(승인 대기) / clarifying(보완·상충 답변 질문) / conflicted(요구사항 충돌 선택 대기) / applying / applied / rejected / replaced / stale / apply_failed. 활성 상태는 pending, clarifying, conflicted.
- 승인·거절 버튼은 pending에서만, 충돌 선택 버튼은 conflicted에서만 유효하다. 버전이 다르면 아무것도 바꾸지 않는다.
- 분석: source.busy가 실행 중 표시다. 실행 중 새 트리거는 followup=true로, 후보 정정은 corrections 큐로 합친다.
- 영향: needs_review / aligned.
- 저장 작업: prepared / committed / rolled_back / recovery_required.
- applied는 파일 저장 성공이다. 재시도는 같은 작업의 복구로 수행하고 새 승인처럼 중복 반영하지 않는다.
- Story/PRD 작업 성공 후에만 applied. Spec/ADR은 각각 별도 결정·작업이다.
- 분석 실패 시 cursor 불변. 성공 시 고정한 end_seq까지만 이동. 이후 이벤트는 남긴다.
- 관련 Story 변경 승인 시 기술 후보의 story_hash를 재검증하고 오래된 후보를 차단한다.
- 충돌 선택 시 충돌한 Story가 문서에 없으면 stale로 끝내고 저장하지 않는다.

## 복구 저장
사용자 네 문서 밖 내부 상태 폴더(`data/`)에 SQLite를 둔다. 회의록 내용은 source 레코드에, 변경 전후 파일 내용은 operation 저널에 보관한다(별도 백업 폴더 없음). 승인 직전과 저장 직전 파일 내용 비교, 같은 폴더 임시 파일 준비 후 파일별 교체를 수행한다. 여러 파일 동시 원자성은 보장하지 않는다.
일부 실패는 저널의 이전 내용으로 복구를 시도한다. 복구 전에도 외부 수정 여부를 확인해 새 수동 편집을 덮어쓰지 않는다. 확인이 불가능하면 recovery_required로 남기고 대상 파일을 안내한다. 재시작 시 미완료 작업은 실제 파일 내용과 저널로 판별하며 자동 승인/무조건 재반영하지 않는다.
