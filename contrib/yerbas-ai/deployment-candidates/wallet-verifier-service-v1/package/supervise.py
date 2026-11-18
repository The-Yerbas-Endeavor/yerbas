"""Preserve the existing relay pause and fixed GPU supervisor gates."""
import fcntl,os,runpy,signal,stat,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from relay_guard import paused
def interrupted(signum,frame):raise SystemExit(128+signum)
for signum in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):signal.signal(signum,interrupted)
fd=os.open('/run/lock/yerbas-verifier-relay.lock',os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600)
s=os.fstat(fd)
if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_mode&0o077:raise ValueError('Protected relay lock required')
fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
with os.fdopen(fd,'w'),paused():runpy.run_path(str(HERE/'start_verifier.py'),run_name='__main__')
