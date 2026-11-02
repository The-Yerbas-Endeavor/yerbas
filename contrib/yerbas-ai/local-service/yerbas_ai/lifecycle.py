"""POSIX process ownership and state locking for the local prototype."""
import fcntl
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess


class StateLock:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.fd = None

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.directory.is_symlink() or self.directory.stat().st_uid != os.getuid():
            raise RuntimeError('State directory must be owned by this user and not a symlink')
        os.chmod(self.directory, 0o700)
        self.fd = os.open(self.directory/'service.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self.fd)
            self.fd = None
            raise RuntimeError('Another service owns this state directory') from None
        return self

    def write_session(self, data):
        path = self.directory / ('.session-'+secrets.token_hex(8))
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump(data, stream)
            os.replace(path, self.directory/'session.json')
        finally:
            path.unlink(missing_ok=True)

    def __exit__(self, *args):
        try:
            (self.directory/'session.json').unlink(missing_ok=True)
        finally:
            os.close(self.fd)
            self.fd = None
        # Keep the lock inode: deleting it creates a race between new owners.


def stop_runtime(process):
    """Stop only the process group created for this managed runtime."""
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    # Clean up runners that outlive their runtime parent.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)
