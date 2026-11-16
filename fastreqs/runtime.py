"""한 컴퓨터에서 봇이 하나만 실행되도록 막는 잠금.

프로세스가 비정상 종료돼도 운영체제가 잠금을 풀어 준다.

사용 예:
    with single_instance(config.data_dir):
        run(config)
"""

import os
from contextlib import contextmanager
from pathlib import Path

LOCK_FILE_NAME = 'runtime.lock'
IS_WINDOWS = os.name == 'nt'

if IS_WINDOWS:
    import msvcrt
else:
    import fcntl


def _lock(handle):
    """파일 잠금을 기다리지 않고 시도한다(실패하면 OSError)."""
    if IS_WINDOWS:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle):
    """파일 잠금을 푼다."""
    handle.seek(0)
    if IS_WINDOWS:
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def single_instance(folder):
    """폴더 안 잠금 파일로 단일 실행을 보장한다.

    Raises:
        RuntimeError: 이미 다른 프로세스가 실행 중인 경우.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / LOCK_FILE_NAME).open('a+b') as handle:
        handle.seek(0)
        handle.write(b'0')
        handle.flush()
        handle.seek(0)
        try:
            _lock(handle)
        except OSError:
            raise RuntimeError('FastReqs가 이미 실행 중입니다. '
                               '기존 프로세스를 종료하세요.') from None
        try:
            yield
        finally:
            _unlock(handle)
