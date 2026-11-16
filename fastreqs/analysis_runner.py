"""분석 실행 부품(RequirementController.startAnalysis·checkAllConflicts의 구현).

입력 경로마다 분석을 한 번에 하나만 돌리고, 결과를 후보로 저장해 제안한다.
충돌 검사는 분석 서비스의 check_conflicts() 한 곳에 맡긴다.
"""

from dataclasses import dataclass

from . import documents as doc
from .records import (
    KIND_CONFLICT,
    CandidateOptions,
    CandidateRecord,
    CandidateStatus,
)
from .store import new_id, utc_now

ANALYZING_NOTICE = '요구사항 변경 후보를 분석하고 있습니다…'
BUSY_NOTICE = '현재 분석 중입니다. 새 요청은 완료 후 이어서 처리하겠습니다.'
NO_CANDIDATE_NOTICE = '요구사항 변경 후보가 없습니다.'


@dataclass
class AnalysisRound:
    """분석 한 번에 필요한 입력을 묶은 값.

    Attributes:
        source: 입력 경로 레코드.
        documents: 분석에 쓴 문서 내용(고정 스냅샷).
        prior: 분석 전 미결 Story 후보 목록.
        correction: 보완·정정할 후보 정보. 일반 분석이면 None.
        end_seq: 이번 분석에 쓴 마지막 대화 순번.
    """

    source: dict
    documents: dict
    prior: list
    correction: dict | None
    end_seq: int


def merge_conflicts(conflicts):
    """Conflict 목록을 후보에 저장할 충돌 정보 하나로 합친다."""
    ids = sorted({story_id for conflict in conflicts
                  for story_id in conflict.requirement_ids})
    reason = ' / '.join(conflict.reason for conflict in conflicts)
    return {'requirement_ids': ids, 'reason': reason}


class AnalysisRunner:
    """입력 경로의 분석을 실행하고 후보를 만든다.

    Attributes:
        context: 공유 협력 객체(ControllerContext).
    """

    def __init__(self, context):
        """공유 협력 객체를 주입받는다."""
        self.context = context

    @property
    def store(self):
        """상태 저장소."""
        return self.context.store

    # ----- 후보 만들기 -----

    def create_candidate(self, source, candidate, documents, options=None):
        """후보 레코드를 만들고 저장한다(트랜잭션 안에서 호출).

        Args:
            source: 후보가 나온 입력 경로 레코드.
            candidate: 분석 서비스가 만든 Candidate.
            documents: 현재 문서 내용.
            options: 스레드·예약 ID·충돌 정보(CandidateOptions).

        Returns:
            저장된 CandidateRecord.

        Raises:
            ValueError: 대체할 ADR이 활성 결정이 아닌 경우.
        """
        options = options or CandidateOptions()
        payload = candidate.model_dump()
        doc.check_references(documents, payload)
        target = (candidate.target_id or options.target
                  or self.store.reserve_id(source['binding'], 'US', documents))
        conflict = None
        if candidate.needs_answer():
            status = CandidateStatus.CLARIFYING
        elif options.conflicts:
            status = CandidateStatus.CONFLICTED
            conflict = merge_conflicts(options.conflicts)
        else:
            status = CandidateStatus.PENDING
        plan = {}
        if status == CandidateStatus.PENDING:
            plan = doc.build_patch(documents, payload, target)
        record = CandidateRecord(
            id=new_id(), binding=source['binding'], source=source['id'],
            kind=doc.KIND_STORY, target=target, status=status,
            payload=payload, docs=documents, plan=plan,
            thread=options.thread, created=utc_now(), conflict=conflict)
        self.store.put_candidate(record)
        return record

    # ----- 분석 시작 -----

    def retry(self, binding_id, source_id):
        """[다시 분석] 버튼 요청을 검증하고 분석을 다시 시작한다.

        Raises:
            ValueError: 다른 채널의 입력 경로인 경우.
        """
        source = self.store.get('source', source_id)
        if source['binding'] != binding_id:
            raise ValueError('다른 채널 요청입니다.')
        self.start(source_id)

    def start(self, source_id, correction=None):
        """입력 경로의 새 대화를 분석해 후보를 만든다.

        이미 분석 중이면 요청을 예약하고 바로 돌아간다. 실패하면 입력과
        미결 후보를 그대로 두고 [다시 분석]을 안내한다.

        Args:
            source_id: 입력 경로 ID.
            correction: 보완·정정할 후보 정보. 일반 분석이면 None.
        """
        if not self._try_mark_busy(source_id, correction):
            return
        released = False
        try:
            has_next = True
            while has_next:
                self._run_round(source_id, correction)
                has_next, correction = self._take_next_request(source_id)
            released = True
        except Exception as error:  # noqa: BLE001 - 실패를 안내하고 보존한다.
            self._report_failure(source_id, error)
        finally:
            if not released:
                self._set_busy(source_id, False)

    def _try_mark_busy(self, source_id, correction):
        """분석 중 표시를 얻는다. 이미 분석 중이면 요청을 예약한다."""
        with self.store.transaction():
            source = self.store.get('source', source_id)
            if not source['busy']:
                source['busy'] = True
                self.store.put('source', source)
                return True
            if correction:
                queue = [item for item in source.get('corrections', [])
                         if item['id'] != correction['id']]
                source['corrections'] = queue + [correction]
            else:
                source['followup'] = True
            self.store.put('source', source)
        self.context.notify_source(source, BUSY_NOTICE)
        return False

    def _take_next_request(self, source_id):
        """예약된 다음 요청을 꺼낸다. 없으면 분석 중 표시를 푼다.

        Returns:
            (다음 요청이 있는지, 다음 정정 정보 또는 None).
        """
        with self.store.transaction():
            source = self.store.get('source', source_id)
            if source.get('corrections'):
                correction = source['corrections'].pop(0)
                self.store.put('source', source)
                return True, correction
            if source['followup']:
                source['followup'] = False
                self.store.put('source', source)
                return True, None
            source['busy'] = False
            self.store.put('source', source)
            return False, None

    def _set_busy(self, source_id, busy):
        """분석 중 표시를 바꾼다."""
        with self.store.transaction():
            source = self.store.get('source', source_id)
            source['busy'] = busy
            self.store.put('source', source)

    def _report_failure(self, source_id, error):
        """분석 실패를 사용자에게 알린다."""
        if isinstance(error, (ValueError, RuntimeError)):
            detail = str(error)
        else:
            detail = '처리 중 오류가 발생했습니다.'
        source = self.store.get('source', source_id)
        self.context.view.show_error(
            self.context.channel_of(source['binding']), source_id, detail,
            thread=source['thread'])

    # ----- 분석 한 번 -----

    def _resolve_correction(self, correction, prior):
        """정정 대상이 이미 교체됐으면 같은 스레드의 최신 후보로 바꾼다."""
        previous = self.store.get_candidate(correction['id'])
        if previous.status != CandidateStatus.REPLACED:
            return correction
        latest = [record for record in prior
                  if record.thread == previous.thread]
        if not latest:
            return correction
        return {**latest[-1].payload, 'id': latest[-1].id,
                'answer': correction.get('answer', '')}

    def _collect_new_chat(self, source, correction):
        """분석할 대화를 고른다(정정이면 해당 후보 스레드만)."""
        events = self.store.find_all('event', source=source['id'])
        if not correction:
            return [event for event in events
                    if event['seq'] > source['cursor']
                    and not event.get('thread')]
        thread = self.store.get_candidate(correction['id']).thread
        return [event for event in events if event.get('thread') == thread]

    def _run_round(self, source_id, correction):
        """분석 한 번: 대화 -> 문서 조회 -> 추출 -> 충돌 검사 -> 저장."""
        source = self.store.get('source', source_id)
        prior = self.context.pending_candidates(source_id)
        if correction:
            correction = self._resolve_correction(correction, prior)
        chat = self._collect_new_chat(source, correction)
        documents = self.context.repository.find_requirements(
            source['binding'])
        round_ = AnalysisRound(
            source=source, documents=documents, prior=prior,
            correction=correction,
            end_seq=max([event['seq'] for event in chat]
                        or [source['cursor']]))
        context = {'documents': documents,
                   'pending': [record.payload for record in prior],
                   'file': source['content']}
        self.context.notify_source(source, ANALYZING_NOTICE)
        analysis = self.context.analyzer.extract_requirements(
            chat, context, clarification=correction)
        if correction and len(analysis.candidates) != 1:
            raise ValueError('보완/정정 결과는 한 후보여야 합니다.')
        candidates = self._drop_missing_targets(round_, analysis.candidates)
        conflicts = [self._check_conflicts(documents, candidate)
                     for candidate in candidates]
        made = self._save_round(round_, list(zip(candidates, conflicts)))
        for record in made:
            self.context.present_candidate(record)
        if not made:
            self.context.notify_source(source, NO_CANDIDATE_NOTICE)

    def _drop_missing_targets(self, round_, candidates):
        """대상 Story가 문서에 없는 후보를 빼고 '요구사항 없음'을 알린다.

        Raises:
            ValueError: 보완·정정 후보의 대상이 없어진 경우.
        """
        source = round_.source
        repository = self.context.repository
        kept = []
        for candidate in candidates:
            target = candidate.target_id
            if not target or repository.exists(source['binding'], target):
                kept.append(candidate)
                continue
            if round_.correction:
                raise ValueError('변경 대상 Story가 없습니다.')
            self.context.view.show_not_found(
                self.context.channel_of(source['binding']), target,
                thread=source['thread'])
        return kept

    def _check_conflicts(self, documents, candidate):
        """승인 가능한 추가·수정 후보만 기존 요구사항과의 충돌을 검사한다."""
        if candidate.action == 'delete' or candidate.needs_answer():
            return []
        return self.context.analyzer.check_conflicts(documents, candidate)

    def _save_round(self, round_, results):
        """분석 결과를 후보로 저장하고 이전 후보를 교체한다.

        Args:
            round_: 이번 분석의 입력(AnalysisRound).
            results: (Candidate, 충돌 목록) 쌍의 목록.

        Returns:
            새로 만든 후보 레코드 목록.

        Raises:
            ValueError: 분석 중 문서가 바뀌었거나 정정이 대상을 바꾼 경우.
        """
        source = round_.source
        binding_id = source['binding']
        lock = self.context.binding_lock(binding_id)
        with lock, self.store.transaction():
            current = self.context.repository.find_requirements(binding_id)
            if round_.documents != current:
                raise ValueError('분석 중 문서가 바뀌었습니다. '
                                 '다시 분석해주세요.')
            options = CandidateOptions()
            replacements = round_.prior
            if round_.correction:
                old = self._check_correction_target(round_.correction,
                                                    results[0][0])
                replacements = [old]
                options = CandidateOptions(thread=old.thread,
                                           target=old.target)
            made = [self.create_candidate(
                        source, candidate, round_.documents,
                        CandidateOptions(options.thread, options.target,
                                         tuple(conflicts)))
                    for candidate, conflicts in results]
            for record in replacements:
                record.status = CandidateStatus.REPLACED
                self.store.put_candidate(record)
            if not round_.correction:
                # 후보별 답변은 관련 없는 채널 대화를 소비하지 않는다.
                latest = self.store.get('source', source['id'])
                latest['cursor'] = round_.end_seq
                self.store.put('source', latest)
        return made

    def _check_correction_target(self, correction, candidate):
        """정정 결과가 같은 후보·같은 대상인지 검사하고 이전 후보를 돌려준다."""
        old = self.store.get_candidate(correction['id'])
        if not old.is_active:
            raise ValueError('이미 처리된 후보입니다.')
        if (candidate.action != old.payload['action']
                or candidate.target_id != old.payload['target_id']):
            raise ValueError('정정에서 대상을 바꾸지 말고 '
                             '새 분석을 요청해주세요.')
        return old

    # ----- 전체 충돌 확인(UC-03) -----

    def check_all_conflicts(self, binding_id):
        """채널 문서 전체의 요구사항 충돌을 찾아 선택 질문으로 보인다.

        Args:
            binding_id: 채널 연결 ID.
        """
        view = self.context.view
        channel_id = self.context.channel_of(binding_id)
        try:
            documents = self.context.repository.find_requirements(binding_id)
            conflicts = self.context.analyzer.check_conflicts(documents)
        except (ValueError, RuntimeError) as error:
            view.notify(channel_id, '충돌 확인 실패: ' + str(error))
            return
        open_pairs = {tuple(record.conflict_ids) for record in
                      self.store.find_candidates(binding=binding_id,
                                                 kind=KIND_CONFLICT)
                      if record.is_active}
        new_conflicts = [conflict for conflict in conflicts
                         if tuple(conflict.requirement_ids) not in open_pairs]
        if not new_conflicts:
            view.show_no_conflict(channel_id)
            return
        with self.store.transaction():
            source, _ = self.store.get_or_create_source(binding_id)
            records = [self._create_conflict_record(source, documents,
                                                    conflict)
                       for conflict in new_conflicts]
        for record in records:
            self.context.present_candidate(record)

    def _create_conflict_record(self, source, documents, conflict):
        """기존 요구사항끼리의 충돌 하나를 선택 대기 레코드로 저장한다."""
        record = CandidateRecord(
            id=new_id(), binding=source['binding'], source=source['id'],
            kind=KIND_CONFLICT, target=' / '.join(conflict.requirement_ids),
            status=CandidateStatus.CONFLICTED, payload={}, docs=documents,
            created=utc_now(), conflict=conflict.model_dump())
        self.store.put_candidate(record)
        return record

