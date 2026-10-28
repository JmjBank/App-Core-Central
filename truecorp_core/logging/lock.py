"""Cross-process lock built on fcntl.flock (Linux/CentOS 7).

flock locks are owned by the open file, so the kernel releases them when the owner
process dies: no stale-lock cleanup is ever needed, and the lock file itself is never
deleted. Non-blocking on purpose: logging must never make the application wait.
"""
import errno
import os

try:
    import fcntl
except ImportError:  # shortcut: Windows developer machines only; production is Linux. No cross-process protection there.
    fcntl = None


class FileLock(object):
    def __init__(self, path):
        self.path = path
        self._fd = None

    def try_acquire(self):
        """True if the lock is now held, False if another process/thread holds it."""
        if self._fd is not None:
            return True
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        if fcntl is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (IOError, OSError) as exc:
                os.close(fd)
                if exc.errno in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                    return False
                raise
        self._fd = fd
        return True

    def release(self):
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
