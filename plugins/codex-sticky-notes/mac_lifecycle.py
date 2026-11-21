"""Coordinate Finder and source launches using locks in the user's data directory."""

import fcntl
import os

from data import APP_HOME


def _open(name):
    directory = APP_HOME / "runtime"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return os.open(directory / name, os.O_CREAT | os.O_RDWR, 0o600)


class Instance:
    def __init__(self, name):
        self.handle = _open(f"{name}.lock")
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.primary = False
            self.close()
        except OSError:
            self.close()
            raise
        else:
            self.primary = True

    def close(self):
        if self.handle is not None:
            os.close(self.handle)
            self.handle = None


class Event:
    def __init__(self, name):
        self.handle = _open(f"{name}.event")

    def signal(self):
        fcntl.flock(self.handle, fcntl.LOCK_EX)
        try:
            os.pwrite(self.handle, b"1", 0)
        finally:
            fcntl.flock(self.handle, fcntl.LOCK_UN)

    def wait(self):
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        try:
            if os.pread(self.handle, 1, 0) != b"1":
                return False
            os.ftruncate(self.handle, 0)
            return True
        finally:
            fcntl.flock(self.handle, fcntl.LOCK_UN)

    def close(self):
        if self.handle is not None:
            os.close(self.handle)
            self.handle = None
