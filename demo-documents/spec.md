# 팀 업무 검색 서비스 — Spec

버전: 1 | 가상 시연 데이터 | 구현 계약 예시

## US-001 검색
- GET /tasks?q=<keyword>
- 제목 또는 본문에 키워드가 포함된 업무를 반환한다.
- 성공 응답: tasks 배열. 각 항목은 id, title, created_at을 포함한다.
- 결과 없음: tasks는 빈 배열이다.

## US-003 CSV 내보내기
- GET /tasks/export.csv?q=<keyword>
- 현재 검색 조건과 같은 결과를 CSV로 반환한다.
- 열: id,title,created_at.
- 권한: 팀 관리자만 허용한다. 일반 팀원은 403.
- 검증: 검색 결과 ID 집합과 CSV의 ID 집합이 동일하다.
## US-004 구현 계약
GET /reports/monthly.csv?month=YYYY-MM 를 추가하고, 팀 관리자만 허용하며 반환 CSV는 month,total_tasks,completed_tasks 열을 포함한다


## 변경 원칙
Story 변경으로 이 계약의 수정이 필요하면 별도 변경 후보를 승인해 반영한다.
승인 전에는 기존 구현 계약을 유지하며 갱신 필요 상태를 표시한다.
