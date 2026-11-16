"""결정 처리 부품(RequirementController.onApproved·onRejected·onSelected).

사용자 결정(승인·거절·충돌 선택)을 검증하고, 저장은 문서 리포지토리의
save() 한 경로로 한다. 저장 전에 작업 저널을 남겨 재시작 때 복구한다.
"""

from . import documents as doc
from .document_repository import SaveFailedError
from .models import Candidate
from .records import (
    KEEP_NEW,
    KIND_CONFLICT,
    CandidateOptions,
    CandidateRecord,
    CandidateStatus,
)
from .store import new_id, utc_now

OPERATION_PREPARED = 'prepared'
OPERATION_COMMITTED = 'committed'
OPERATION_ROLLED_BACK = 'rolled_back'
OPERATION_RECOVERY_REQUIRED = 'recovery_required'
UNFINISHED_OPERATIONS = (OPERATION_PREPARED, OPERATION_RECOVERY_REQUIRED)

IMPACT_NEEDS_REVIEW = 'needs_review'
IMPACT_ALIGNED = 'aligned'

APPLIED_PREFIX = '승인 반영 완료'
REJECTED_MESSAGE = '거절했습니다. 문서는 변경하지 않았습니다.'
KEPT_EXISTING_PREFIX = '기존 요구사항을 유지했습니다'
BUSY_REFUSAL = '재분석이 끝나면 새 제안을 확인해주세요.'
STALE_STORY_REFUSAL = ('관련 Story가 바뀌었습니다. '
                       '기술 변경안을 다시 검토해주세요.')
REFRESHED_NOTICE = ('문서가 변경되어 새 미리보기를 만들었습니다. '
                    '다시 승인해주세요.')
STALE_CONFLICT_REFUSAL = ('문서가 바뀌어 충돌 정보가 오래되었습니다. '
                          '다시 확인해주세요.')
TECH_DELETE_PAYLOAD = {'action': 'delete', 'spec_change': '',
                       'adr_change': None}


def is_final_decision(message):
    """결정 결과 메시지가 최종 결정(카드 닫기 대상)인지 돌려준다."""
    return message.startswith((APPLIED_PREFIX, REJECTED_MESSAGE,
                               KEPT_EXISTING_PREFIX))


class ApprovalProcessor:
    """승인·거절·충돌 선택을 처리하고 문서에 저장한다.

    Attributes:
        context: 공유 협력 객체(ControllerContext).
        create_candidate: 최신 문서로 Story 후보를 다시 만드는 함수.
    """

    def __init__(self, context, create_candidate):
        """공유 협력 객체와 후보 생성 함수를 주입받는다."""
        self.context = context
        self.create_candidate = create_candidate

    @property
    def store(self):
        """상태 저장소."""
        return self.context.store

    def _load(self, decision):
        """결정 대상 후보와 입력 경로를 읽는다."""
        record = self.store.get_candidate(decision.candidate_id)
        source = self.store.get('source', record.source)
        return record, source

    @staticmethod
    def _check_decidable(record, source, decision, expected_status):
        """지금 결정할 수 없는 후보면 안내 메시지를, 아니면 None을 돌려준다.

        Raises:
            ValueError: 다른 채널의 후보인 경우.
        """
        if record.binding != decision.binding_id:
            raise ValueError('다른 채널의 제안입니다.')
        if source['busy'] and record.kind == doc.KIND_STORY:
            return BUSY_REFUSAL
        if (record.version != decision.version
                or record.status != expected_status):
            return '이미 처리되었거나 오래된 제안입니다: ' + record.status.value
        return None

    def _close(self, record, status, user_id):
        """후보를 결정 완료 상태로 저장한다."""
        record.status = status
        record.actor = user_id
        record.decided_at = utc_now()
        self.store.put_candidate(record)

    # ----- onRejected -----

    def reject(self, decision):
        """후보를 거절한다. 문서는 바꾸지 않는다.

        Returns:
            사용자에게 보여줄 결과 메시지.
        """
        with self.context.binding_lock(decision.binding_id):
            with self.store.transaction():
                record, source = self._load(decision)
                refusal = self._check_decidable(record, source, decision,
                                                CandidateStatus.PENDING)
                if refusal:
                    return refusal
                self._close(record, CandidateStatus.REJECTED,
                            decision.user_id)
        return REJECTED_MESSAGE

    # ----- onApproved -----

    def approve(self, decision):
        """승인된 후보를 문서에 저장한다.

        문서가 제안 이후 바뀌었으면 저장하지 않고 새 미리보기를 만든다.

        Returns:
            사용자에게 보여줄 결과 메시지.

        Raises:
            ValueError: 다른 채널의 후보인 경우.
        """
        with self.context.binding_lock(decision.binding_id):
            with self.store.transaction():
                record, source = self._load(decision)
                refusal = self._check_decidable(record, source, decision,
                                                CandidateStatus.PENDING)
                if refusal:
                    return refusal
                documents = self.context.repository.find_requirements(
                    decision.binding_id)
                refreshed = None
                if documents != record.docs:
                    refreshed = self._refresh_stale_candidate(
                        record, source, documents)
                    if refreshed is None:
                        return STALE_STORY_REFUSAL
            if refreshed is not None:
                self.context.present_candidate(refreshed)
                return REFRESHED_NOTICE
            return self._apply(record, source, documents, decision.user_id)

    def _refresh_stale_candidate(self, record, source, documents):
        """문서가 바뀐 뒤의 승인 요청이면 최신 문서로 후보를 다시 만든다.

        Returns:
            다시 보여줄 후보. 기술 후보의 기준 Story가 바뀌었으면 None.
        """
        if record.kind == doc.KIND_STORY:
            record.status = CandidateStatus.STALE
            self.store.put_candidate(record)
            return self.create_candidate(
                source, Candidate.model_validate(record.payload), documents,
                CandidateOptions(thread=record.thread, target=record.target))
        stories = doc.parse_sections(documents[doc.USER_STORIES])
        story_hash = doc.compute_digest(stories.get(record.target, ''))
        if story_hash != record.story_hash:
            record.status = CandidateStatus.STALE
            self.store.put_candidate(record)
            return None
        record.docs = documents
        record.plan = doc.build_patch(documents, record.payload,
                                      record.target, record.kind)
        record.version += 1
        self.store.put_candidate(record)
        return record

    # ----- onSelected -----

    def select(self, decision, keep):
        """충돌한 요구사항 중 사용자가 고른 하나만 남기고 나머지는 지운다.

        Args:
            decision: 결정 요청(Decision).
            keep: 살릴 기존 Story ID, 또는 새 후보를 살리면 'new'.

        Returns:
            사용자에게 보여줄 결과 메시지.

        Raises:
            ValueError: 다른 채널의 후보이거나 선택지에 없는 값인 경우.
        """
        with self.context.binding_lock(decision.binding_id):
            with self.store.transaction():
                record, source = self._load(decision)
                refusal = self._check_decidable(record, source, decision,
                                                CandidateStatus.CONFLICTED)
                if refusal:
                    return refusal
                ids = record.conflict_ids
                if record.kind != KIND_CONFLICT and keep in ids:
                    self._close(record, CandidateStatus.REJECTED,
                                decision.user_id)
                    return f'{KEPT_EXISTING_PREFIX}: {keep}. 새 요구사항은 ' \
                           '반영하지 않았습니다.'
                payload, removed = self._resolve_choice(record, ids, keep)
                documents = self.context.repository.find_requirements(
                    decision.binding_id)
                stories = doc.parse_sections(documents[doc.USER_STORIES])
                if not all(story_id in stories for story_id in removed):
                    self._close(record, CandidateStatus.STALE,
                                decision.user_id)
                    return STALE_CONFLICT_REFUSAL
                record.docs = documents
                record.plan = doc.build_resolution_patch(
                    documents, payload, record.target, removed)
            return self._apply(record, source, documents, decision.user_id,
                               removed)

    @staticmethod
    def _resolve_choice(record, ids, keep):
        """선택 값을 (살릴 새 후보 payload 또는 None, 지울 ID 목록)으로 바꾼다.

        Raises:
            ValueError: 선택지에 없는 값인 경우.
        """
        if record.kind == KIND_CONFLICT and keep in ids:
            return None, [story_id for story_id in ids if story_id != keep]
        if record.kind != KIND_CONFLICT and keep == KEEP_NEW:
            return record.payload, ids
        raise ValueError('선택지에 없는 요구사항입니다.')

    # ----- 저장(공통) -----

    def _apply(self, record, source, documents, user_id, removed=()):
        """작업 저널을 남기고 후보의 패치를 문서에 저장한다.

        Returns:
            사용자에게 보여줄 결과 메시지.
        """
        binding_id = record.binding
        operation = {'id': new_id(), 'binding': binding_id,
                     'candidate': record.id, 'state': OPERATION_PREPARED,
                     'before': documents, 'after': record.plan,
                     'actor': user_id, 'time': utc_now()}
        with self.store.transaction():
            self.store.put('operation', operation)
            record.status = CandidateStatus.APPLYING
            self.store.put_candidate(record)
        try:
            self.context.repository.save(binding_id, documents, record.plan)
        except SaveFailedError as failure:
            return self._record_save_failure(operation, record, failure)
        with self.store.transaction():
            operation['state'] = OPERATION_COMMITTED
            self.store.put('operation', operation)
            self._close(record, CandidateStatus.APPLIED, user_id)
        self._show_result(record, removed)
        self._follow_up_technical_changes(record, source, removed)
        return APPLIED_PREFIX + ': ' + ', '.join(record.plan)

    def _show_result(self, record, removed):
        """저장 결과를 추가 완료·제외 완료 안내로 보인다."""
        view = self.context.view
        channel_id = self.context.channel_of(record.binding)
        is_delete = (record.payload.get('action') == 'delete'
                     or record.payload.get('delete'))
        if record.kind != KIND_CONFLICT:
            if is_delete:
                view.show_removed(channel_id, record.target, record.thread)
            else:
                view.show_added(channel_id, record, record.thread)
        for story_id in removed:
            view.show_removed(channel_id, story_id, record.thread)

    def _record_save_failure(self, operation, record, failure):
        """저장 실패 결과를 저널과 후보에 기록하고 안내 메시지를 돌려준다."""
        restored = (CandidateStatus.CONFLICTED if record.conflict
                    else CandidateStatus.PENDING)
        with self.store.transaction():
            if failure.recovery_required:
                operation['state'] = OPERATION_RECOVERY_REQUIRED
                record.status = CandidateStatus.APPLY_FAILED
            else:
                operation['state'] = OPERATION_ROLLED_BACK
                record.status = restored
            self.store.put('operation', operation)
            self.store.put_candidate(record)
        if failure.recovery_required:
            return ('부분 반영: 복구 필요 파일을 확인해주세요: '
                    + ', '.join(failure.written))
        return ('저장 실패. 이전 상태를 유지/복구했습니다. '
                '다시 승인할 수 있습니다.')

    # ----- 기술 문서 후속 변경 -----

    def _follow_up_technical_changes(self, record, source, removed):
        """Story 저장 뒤 Spec/ADR 후보를 만들거나 기술 문서를 정렬 완료로 둔다.

        기술 후보 생성에 실패해도 이미 저장한 Story는 되돌리지 않는다.
        """
        binding_id = record.binding
        try:
            with self.store.transaction():
                if record.kind in (doc.KIND_SPEC, doc.KIND_ADR):
                    self.context.put_impact(binding_id, record.target,
                                            record.kind, IMPACT_ALIGNED)
                    return
                documents = self.context.repository.find_requirements(
                    binding_id)
                changes = [(story_id, TECH_DELETE_PAYLOAD)
                           for story_id in removed]
                if record.kind == doc.KIND_STORY:
                    changes.insert(0, (record.target, record.payload))
                children = [child for story_id, payload in changes
                            for child in self._create_technical_candidates(
                                record, story_id, payload, documents)]
            for child in children:
                self.context.present_candidate(child)
        except Exception:  # noqa: BLE001 - Story 저장 성공은 유지한다.
            self.context.notify_source(
                source, '문서 반영은 완료했습니다. 기술 영향 제안 생성/게시 '
                '실패: 갱신 검토 필요.')

    def _mark_old_technical_stale(self, binding_id, story_id):
        """같은 Story의 이전 기술 후보를 오래된 것으로 막는다."""
        for old in self.store.find_candidates(binding=binding_id,
                                              target=story_id):
            if old.kind in (doc.KIND_SPEC, doc.KIND_ADR) and old.is_active:
                old.status = CandidateStatus.STALE
                self.store.put_candidate(old)
                self.context.put_impact(binding_id, story_id, old.kind,
                                        IMPACT_NEEDS_REVIEW)

    def _technical_changes(self, binding_id, story_id, payload, documents):
        """Story 변경이 요구하는 (문서 종류, 기술 변경 내용) 목록을 만든다."""
        is_delete = payload['action'] == 'delete'
        changes = []
        spec_sections = doc.parse_sections(documents[doc.SPEC])
        if payload['spec_change'] or (is_delete and story_id in spec_sections):
            changes.append((doc.KIND_SPEC, {'content': payload['spec_change'],
                                            'delete': is_delete}))
        if payload['adr_change']:
            adr_id = self.store.reserve_id(binding_id, 'ADR', documents)
            changes.append((doc.KIND_ADR, {'change': payload['adr_change'],
                                           'adr_id': adr_id}))
        return changes

    def _create_technical_candidates(self, record, story_id, payload,
                                     documents):
        """승인된 Story 변경의 Spec/ADR 변경 후보를 만든다.

        Returns:
            새로 만든 기술 후보 레코드 목록.
        """
        binding_id = record.binding
        self._mark_old_technical_stale(binding_id, story_id)
        stories = doc.parse_sections(documents[doc.USER_STORIES])
        story_hash = doc.compute_digest(stories.get(story_id, ''))
        children = []
        for kind, change in self._technical_changes(binding_id, story_id,
                                                    payload, documents):
            child = CandidateRecord(
                id=new_id(), binding=binding_id, source=record.source,
                kind=kind, target=story_id, status=CandidateStatus.PENDING,
                payload=change, docs=documents,
                plan=doc.build_patch(documents, change, story_id, kind),
                created=utc_now(), story_hash=story_hash)
            self.store.put_candidate(child)
            self.context.put_impact(binding_id, story_id, kind,
                                    IMPACT_NEEDS_REVIEW)
            children.append(child)
        return children

    # ----- 재시작 복구 -----

    def recover(self):
        """재시작 시 분석 중 표시를 풀고, 끝나지 않은 저장 작업을 판별한다."""
        for source in self.store.find_all('source'):
            with self.store.transaction():
                source['busy'] = False
                self.store.put('source', source)
        for operation in self.store.find_all('operation'):
            if operation['state'] in UNFINISHED_OPERATIONS:
                self._recover_operation(operation)

    def _recover_operation(self, operation):
        """실제 파일과 저널을 비교해 작업 상태를 확정한다(자동 재반영 없음)."""
        binding_id = operation['binding']
        with self.context.binding_lock(binding_id):
            documents = self.context.repository.find_requirements(
                binding_id, validate=False)
            record = self.store.get_candidate(operation['candidate'])
            after = operation['after']
            if all(documents[name] == text for name, text in after.items()):
                operation['state'] = OPERATION_COMMITTED
                record.status = CandidateStatus.APPLIED
                record.actor = operation['actor']
                record.decided_at = operation['time']
            elif all(documents[name] == operation['before'][name]
                     for name in after):
                operation['state'] = OPERATION_ROLLED_BACK
                record.status = CandidateStatus.PENDING
            else:
                operation['state'] = OPERATION_RECOVERY_REQUIRED
                record.status = CandidateStatus.APPLY_FAILED
            with self.store.transaction():
                self.store.put('operation', operation)
                self.store.put_candidate(record)
            self.context.view.notify(
                self.context.channel_of(binding_id),
                '미완료 저장 작업 확인: ' + operation['state'] + ' · '
                + ', '.join(after))
