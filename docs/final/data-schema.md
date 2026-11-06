# 데이터 스키마

구현용 설계안. Markdown이 기준 자료이며 아래 DB 테이블은 대화·작업·이력만 관리한다. DB에서 문서 전체를 생성하지 않는다. 동작은 [flow](flow.md), 이유는 [ADR](adr.md).

## 문서 계약
채널마다 사용자가 지정한 서로 다른 폴더에 prd.md/user-stories.md/spec.md/adr.md를 둔다. UTF-8 및 고정 기본 섹션을 검증한다.
- Story: US ID, 제목, Who, What, Why, 인수조건.
- PRD: 목표/배경 + Story ID를 참조하는 기능 범위.
- Spec: 고유 항목 ID + 관련 US ID + 동작/입출력/권한/예외/검증.
- ADR: ADR ID + 관련 US ID + 상태/배경/대안/결정/결과/대체 ID.
문서 버전은 원본 파일 바이트의 SHA-256이다. 항목 버전은 정규화한 해당 항목 내용의 해시다. 삭제된 ID도 내부 예약 목록에 남긴다. 무관 섹션은 그대로 보존한다.

## 공통 타입
내부 ID는 UUID, 시간은 UTC ISO-8601, Slack ts는 문자열(부동소수점 변환 금지). *_json은 검증된 구조화 JSON이다. workspace_id+channel_id가 모든 사용자 자료의 격리 경계다. 키/토큰은 DB 및 분석 로그에 저장하지 않는다.

## 논리 테이블
| 테이블 | 주요 필드 | 제약·용도 |
|---|---|---|
| channel_bindings | id, workspace_id, channel_id, folder_path, created_at | UNIQUE(workspace_id,channel_id), 정규화한 폴더 중복 연결 금지 |
| input_sources | id, binding_id, kind(channel/file), thread_ts?, file_id?, content_hash?, content_path?, analyzed_seq, followup_requested | 채널 경로 하나, 파일은 UNIQUE(binding_id,content_hash); 내용이 달라지면 새 경로 |
| events | id, source_id, event_key, seq, message_ts, thread_ts?, user_id, text, received_at | event_key 유일, source 내 seq 증가; bot/system 제외 |
| analysis_runs | id, source_id, start_seq, end_seq, state, snapshot_json, previous_candidate_states_json, error?, started_at, ended_at | 입력·미결·파일 버전을 고정; 성공 때만 분석 경계 이동 |
| candidates | id, source_id, run_id, version, kind(story/spec/adr), operation, target_id, story_refs_json, status, payload_json, evidence_json, base_hashes_json, depends_on?, slack_thread_ts, slack_message_ts | 버튼에 id/version 결합; 실제 존재 대상·참조 검증 |
| decisions | id, candidate_id, candidate_version, choice, actor_id, decided_at, result | UNIQUE(candidate_id, candidate_version); 결정 승자와 저장 결과는 별도 |
| document_impacts | id, binding_id, story_id, story_hash, document_kind, status, candidate_id? | 기술 영향 추적; 거절해도 needs_review 유지 |
| document_operations | id, binding_id, decision_id, state, file_plan_json, backup_dir, error?, updated_at | 파일별 이전/예정 해시·백업 위치·반영 결과; 재시작 복구 저널 |
| reserved_ids | binding_id, document_kind, item_id, first_seen_at, retired_at? | 복합 PK, 삭제 후 재사용 금지 |

payload_json: Story의 Who/What/Why/인수조건 및 PRD 범위 패치, 또는 Spec/ADR 패치. 패치는 문서 종류·대상 항목 ID·기대 원문·제안문을 가지며 허용된 폴더/섹션만 편집한다. evidence_json은 source/event/file 근거 위치다. AI가 임의 경로나 실행 코드를 지정할 수 없다.

## 상태와 불변식
- 후보: clarifying / conflicted / pending / applying / applied / rejected / replaced / stale / apply_failed. 재분석 일시 잠금은 analysis_runs와 연결해 원래 상태 복원이 가능해야 한다.
- 분석: queued / running / succeeded / failed. source별 active run 하나, 새 트리거는 followup_requested=true로 병합.
- 영향: needs_review / applying / aligned / failed / recovery_required.
- 저장 작업: prepared / writing / committed / rolled_back / recovery_required.
- decisions의 approve는 사용자 의사이며 applied는 파일 저장 성공이다. 재시도는 동일 작업의 복구로 수행하고 새로운 승인처럼 중복 반영하지 않는다.
- Story/PRD 작업 성공 후에만 applied. Spec/ADR은 각각 별도 결정·작업이다.
- 분석 실패 시 analyzed_seq 불변. 성공 시 고정한 end_seq까지만 이동. 이후 이벤트는 남긴다.
- 관련 Story 변경 승인 시 기술 후보의 기준 story_hash를 재검증하고 오래된 후보를 차단한다.

## 복구 저장
사용자 네 문서 밖 내부 상태 폴더에 SQLite/입력 파일/작업별 원본 백업을 보관한다. 승인 직전과 저장 직전 파일 해시 검사, 같은 폴더 임시 파일 준비 후 파일별 교체를 수행한다. 여러 파일 동시 원자성은 보장하지 않는다.
일부 실패는 백업 복구를 시도한다. 복구 전에도 외부 수정 여부를 확인해 새 수동 편집을 덮어쓰지 않는다. 확인이 불가능하면 recovery_required로 남기고 대상 파일을 안내한다. 재시작 시 미완료 작업은 실제 해시와 저널로 판별하며 자동 승인/무조건 재반영하지 않는다.
