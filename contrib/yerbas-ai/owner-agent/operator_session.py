"""Single supervised operator session; stop requests are files, never arbitrary PIDs."""
import fcntl,json,os,re,time
from pathlib import Path

class StopRequested(RuntimeError):pass

def write(path,value):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2)+'\n');tmp.chmod(0o600);os.replace(tmp,path)

def snapshot(directory):
    directory=Path(directory);path=directory/'active.json'
    if not path.exists():return {'active':False}
    value=json.loads(path.read_text())
    with (directory/'session.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);active=False
        except BlockingIOError:active=True
    return dict(value,active=active)

def request_stop(directory,run=None):
    directory=Path(directory);value=snapshot(directory)
    if not value['active']:raise ValueError('No active supervised text job')
    current=value['run_id']
    if not re.fullmatch('[a-f0-9]{32}',current) or (run is not None and run!=current):raise ValueError('Active job differs from requested job')
    write(directory/(current+'.stop'),{'run_id':current,'requested_at':time.time()})
    return {'run_id':current,'stop_requested':True,'message':'Request recorded; wait for job status to confirm shutdown'}

class Session:
    def __init__(self,directory,run):
        if not re.fullmatch('[a-f0-9]{32}',run):raise ValueError('Invalid job ID')
        self.directory=Path(directory);self.directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.run=run;self.lock=(self.directory/'session.lock').open('a')
        try:fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:self.lock.close();raise ValueError('Another supervised text job is already running')
        self.phase('preflight')
    def phase(self,phase,**details):
        write(self.directory/'active.json',{'run_id':self.run,'phase':phase,'updated_at':time.time(),**details})
    def stopped(self):return (self.directory/(self.run+'.stop')).exists()
    def check(self):
        if self.stopped():raise StopRequested('Owner requested stop; no further contributions will start')
    def request(self):write(self.directory/(self.run+'.stop'),{'run_id':self.run,'requested_at':time.time()})
    def close(self,phase,**details):
        self.phase(phase,**details);self.lock.close()

def wait_child(process,session,cancel,timeout=300):
    started=time.monotonic();requested=None
    while process.poll() is None:
        if session.stopped():
            if requested is None:cancel();requested=time.monotonic();session.phase('stopping')
            if time.monotonic()-requested>=10:raise StopRequested('Owner requested stop; supervisor shutdown required')
        if time.monotonic()-started>=timeout:raise TimeoutError('Supervisor exceeded job wait bound')
        time.sleep(.2)
    if requested is not None:raise StopRequested('Owner requested stop; supervisor returned')
    session.check()
    return process.returncode
