"""A crash-released project export lock for macOS and Windows."""
from contextlib import contextmanager
from functools import wraps
import os


@contextmanager
def export_lock(directory):
    # Keep the file after release: unlinking a held inode permits a second lock.
    with open(directory / '.export.lock', 'a+b') as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b'\0')
            handle.flush()
        handle.seek(0)
        acquired = False
        try:
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError as error:
                raise ValueError('此项目已有导出任务，请等待完成或先取消。') from error
            yield
        finally:
            if acquired:
                handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def exclusive_export(function):
    @wraps(function)
    def guarded(project, *args, **kwargs):
        with export_lock(project.directory):
            return function(project, *args, **kwargs)
    return guarded
