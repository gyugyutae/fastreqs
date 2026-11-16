"""요구사항 문서 리포지토리(설계의 RequirementDocumentRepository).

설계 오퍼레이션과의 대응:
    findRequirements(channelId)      -> find_requirements()
    exists(channelId, requirementId) -> exists()
    save(channelId, change)          -> save()

채널에 연결된 로컬 폴더의 Markdown 문서를 읽고, 승인된 변경(추가·수정·
삭제)만 save() 한 경로로 저장한다. 저장 도중 실패하면 이미 쓴 파일을
되돌린다.
"""

from pathlib import Path

from . import documents as doc


class DocumentChangedError(ValueError):
    """저장 직전에 문서가 외부에서 바뀐 경우."""


class SaveFailedError(Exception):
    """문서 저장에 실패한 경우.

    Attributes:
        written: 실패 전에 저장한 파일 이름 목록.
        recovery_required: 되돌리기에도 실패해 수동 복구가 필요한지 여부.
    """

    def __init__(self, written, recovery_required):
        """저장 결과를 보관한다."""
        super().__init__('문서 저장 실패')
        self.written = written
        self.recovery_required = recovery_required


class RequirementDocumentRepository:
    """채널별 문서 폴더에 대한 읽기·저장 접근을 감춘다.

    Attributes:
        store: 채널-폴더 연결을 가진 StateStore.
    """

    def __init__(self, store):
        """연결 정보를 읽을 저장소를 주입받는다."""
        self.store = store

    def folder_of(self, binding_id):
        """채널 연결 ID의 문서 폴더 경로를 돌려준다."""
        return Path(self.store.get('binding', binding_id)['folder'])

    def find_requirements(self, binding_id, validate=True):
        """채널에 연결된 네 문서를 읽어 {파일명: 내용}으로 돌려준다."""
        return doc.read_documents(self.folder_of(binding_id),
                                  validate_structure=validate)

    def exists(self, binding_id, requirement_id):
        """채널 문서에 활성 Story가 있는지 돌려준다."""
        stories = self.find_requirements(binding_id)[doc.USER_STORIES]
        return requirement_id in doc.parse_sections(stories)

    def save(self, binding_id, before, patch):
        """승인된 패치를 문서 폴더에 저장한다.

        Args:
            binding_id: 채널 연결 ID.
            before: 승인 시점의 문서 내용.
            patch: 저장할 {파일명: 새 내용}.

        Raises:
            SaveFailedError: 저장 중 실패한 경우. 가능한 파일은 되돌린다.
        """
        folder = self.folder_of(binding_id)
        written = []
        try:
            if self.find_requirements(binding_id) != before:
                raise DocumentChangedError('저장 직전 문서가 바뀌었습니다.')
            for name, content in patch.items():
                if doc.read_text(folder / name) != before[name]:
                    raise DocumentChangedError('저장 중 문서가 바뀌었습니다.')
                doc.atomic_write(folder / name, content)
                written.append(name)
        except Exception:
            recovered = self._roll_back(folder, written, before, patch)
            raise SaveFailedError(written, not recovered) from None

    @staticmethod
    def _roll_back(folder, written, before, patch):
        """이미 저장한 파일을 이전 내용으로 되돌린다.

        외부에서 다시 고친 파일은 덮어쓰지 않는다.

        Returns:
            모든 파일을 되돌렸으면 True.
        """
        recovered = True
        for name in written:
            try:
                if doc.read_text(folder / name) != patch[name]:
                    raise OSError('외부 편집 감지')
                doc.atomic_write(folder / name, before[name])
            except Exception:  # noqa: BLE001 - 파일마다 복구를 계속 시도한다.
                recovered = False
        return recovered
