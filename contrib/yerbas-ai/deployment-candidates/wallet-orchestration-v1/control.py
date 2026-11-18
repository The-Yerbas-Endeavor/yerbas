"""Private-testnet wallet entrypoint. One durable launch per reviewed assignment."""
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from workflow import Journal, validate_request

HERE = Path(__file__).resolve().parent
ROOT = Path.home() / '.local/share/yerbas-wallet-orchestration-v1'


def handle(request, root=ROOT, launch=subprocess.Popen):
    validate_request(request)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    Journal(root)
    directory = root / request['quote']
    directory.mkdir(mode=0o700, exist_ok=True)
    journal = Journal(directory)
    lock = os.open(directory / 'launch.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        s = os.fstat(lock)
        if not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or s.st_nlink != 1 or s.st_mode & 0o077:
            raise ValueError('Private launch lock required')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        previous = journal.read('launch-intent.json')
        if previous is not None:
            if previous != request:
                raise ValueError('Existing wallet request differs')
            return dict(quote=request['quote'], retained=True, started=False, automatic_retry=False)
        journal.retain('launch-intent.json', request)
        fd = os.open(directory / 'worker.log', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as log:
            process = launch(['/usr/bin/python3', '-I', '-B', str(HERE / 'worker.py'), request['quote']],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                             start_new_session=True, close_fds=True)
        journal.retain('launch-acknowledgment.json', dict(pid=process.pid))
        return dict(quote=request['quote'], retained=True, started=True, automatic_retry=False)
    finally:
        os.close(lock)


if __name__ == '__main__':
    os.umask(0o077)
    raw = sys.stdin.buffer.read(16385)
    if not 0 < len(raw) <= 16384:
        raise ValueError('Bounded wallet request required')
    print(json.dumps(handle(json.loads(raw))))
