"""Cross-platform advisory lock, released even when a process crashes."""
from contextlib import contextmanager
from pathlib import Path

@contextmanager
def single_instance(folder):
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=True)
    with (folder/'runtime.lock').open('a+b') as handle:
        handle.seek(0); handle.write(b'0'); handle.flush(); handle.seek(0)
        try:
            import os
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError: raise RuntimeError('FastReqs가 이미 실행 중입니다. 기존 프로세스를 종료하세요.') from None
        try: yield
        finally:
            handle.seek(0)
            if os.name=='nt': msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else: fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
