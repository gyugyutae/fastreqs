# FastReqs MVP

Windows 노트북에서 실행하는 승인 기반 Slack 요구사항 관리 데모.
대화/.md 회의록 → Who/What/Why 보완 → 후보별 Story/PRD 공동 승인 → Spec/ADR 별도 승인.

## Windows 시작

1. Python 3.10 이상을 설치한 노트북에 이 프로젝트/배포 zip을 풀고 `setup.cmd` 실행. 패키지 설치에는 인터넷 필요.
2. Slack 앱을 `slack-manifest.json`으로 생성. Socket Mode 활성화, App-Level Token의 `connections:write` 권한으로 **xapp** 토큰 생성.
3. 워크스페이스에 설치하고 OAuth의 **xoxb** Bot Token 확보. 대상 채널에서 `/invite @FastReqs`.
4. `demo.cmd` 실행: 새 `demo-documents` 폴더에 네 초기 Markdown 문서 복사. 이미 내용 있는 폴더는 덮어쓰지 않음.
5. `configure.cmd` 실행: 없는 Slack/OpenRouter 키를 숨김 입력하고, 채널 링크/ID와 **노트북의 demo-documents 절대 경로** 입력. 설정은 `.env`, 연결/작업은 `data/mvp.db` 저장.
6. `start.cmd` 실행. 실행 중인 노트북과 인터넷 연결이 필요. Ctrl+C 종료.

같은 봇은 한 컴퓨터에서만 실행한다. 데스크톱 프로세스 종료 후 노트북에서 실행한다. `.env`/`data`는 공유하지 않는다. 이전 초안의 fastreqs.db는 사용하지 않고 새 mvp.db를 사용한다.

## 실제 데모

- 파일: `demo-fixtures/meeting-inputs/01-monthly-report.md`를 Slack 업로드 → **업로드 메시지 스레드**에서 `@FastReqs 분석해줘`.
- 봇의 보완 질문 메시지에 **답글**로 “월간 실적 공유 시간을 줄이기 위해서입니다.” 입력. 후보 카드마다 별도 스레드가 있으므로 해당 카드/질문에 답글을 단다.
- Story/PRD 전후를 확인하고 승인. 노트북의 `demo-documents` 파일 변경 확인.
- 두 사람 대화로 다크 모드 US-002 제외 결정 → `수고하셨습니다` → 삭제 후보 승인. 이어 Spec 삭제 별도 승인.
- 무관한 ADR/제품 배경은 유지된다. 일반 채널 재분석은 파일 미결을 섞지 않는다.
- 기술 변경이 미결/거절이면 기존 문서를 유지하고 봇 제안/`status`에 **갱신 검토 필요** 표시. 승인하지 않은 상태 표시만으로 문서를 수정하지 않는다.

전체 약 3분 대본: [demo-script-3min.md](docs/demo-script-3min.md).

## 점검/모의 데모

```powershell
.venv\Scripts\python.exe -m fastreqs doctor
.venv\Scripts\python.exe -m fastreqs status
.venv\Scripts\python.exe -m fastreqs replay
```

`doctor`는 키 존재/파일만 검사하며 모델을 호출하지 않는다. `replay.cmd`는 **미리 정한 모델 응답을 쓰는 오프라인 모의 데모**다. Slack/무료 모델 실증이 아니다. 임시 파일만 사용한다.

## 문서와 복구

Markdown 네 파일이 기준이다. 샘플 템플릿의 기본 섹션/US/ADR ID를 유지한다. 후보 승인 전 수동 파일 변경 시 새 미리보기 재승인. Story/PRD 둘 다 저장되어야 성공이다.
저장 저널에 원본/제안/처리자를 보관한다. 부분 실패는 복구 시도, 외부 편집 등으로 복구 불가하면 파일명/복구 필요를 알린다. `status`로 작업 상태를 확인한다. 운영 DB에서 문서 전체 재출력 기능은 제공하지 않는다.

## 현재 검증 범위

자동 테스트 및 오프라인 모의 흐름 검증. 실제 Slack 권한/첨부·무료 모델 품질/지연·Windows 네이티브 실행은 **리허설에서 검증 필요**. 무료 모델 자동 유료 전환 없음.
첨부 다운로드는 토큰 유출 방지를 위해 다른 호스트/리다이렉트를 따라가지 않는다. Slack 파일 전달이 리다이렉트를 요구하면 명시적으로 다운로드 실패가 표시되며 리허설에서 확인한다.

설계: [docs/final/prd.md](docs/final/prd.md). 개발 테스트: `python -m unittest discover -s tests -v`.
SDK 연결은 [Slack Bolt 이벤트](https://docs.slack.dev/tools/bolt-python/concepts/event-listening/)·[버튼 ack](https://docs.slack.dev/tools/bolt-python/concepts/actions/), 모델 출력은 [OpenRouter Structured Outputs](https://openrouter.ai/docs/guides/features/structured-outputs)를 따른다.
