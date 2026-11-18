"""Owner-only fixed GPU reproduction service; no payment or signing APIs."""
import json,os,pwd,signal,socket,stat,struct,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from jobs import Journal,Jobs
ROOT=Path('/var/lib/yerbas-wallet-verifier-v1')
SOCKET=Path('/run/yerbas-wallet-verifier/control.sock')
class Executor:
 def __init__(self):self.process=None;self.log=None
 def prepare(self,run):
  self.box=ROOT/run;self.box.mkdir(mode=0o700)
  self.log=(self.box/'supervisor.log').open('xb')
  self.process=subprocess.Popen(['/usr/bin/python3','-I','-B',str(HERE/'supervise.py'),'--dataset',str(HERE/'dataset'),'--run-id',run,'--ready',str(self.box/'ready'),'--gate',str(self.box/'go')],stdin=subprocess.DEVNULL,stdout=self.log,stderr=self.log)
  until=time.monotonic()+40
  while not (self.box/'ready').exists():
   if self.process.poll() is not None:raise RuntimeError('Supervisor refused preparation; retained log')
   if time.monotonic()>until:raise TimeoutError('Readiness timed out')
   time.sleep(.1)
 def execute(self,run):
  if self.process.poll() is not None or (self.box/'ready').read_text()!=run:raise ValueError('Supervisor no longer ready')
  with (self.box/'go').open('x') as f:f.write(run);f.flush();os.fsync(f.fileno())
 def poll(self):
  if self.process is None or self.process.poll() is None:return None
  self.log.close();return {'exit_code':self.process.returncode}
 def cancel(self):
  if self.process and self.process.poll() is None:self.process.terminate();self.process.wait(timeout=40)
  if self.log:self.log.close()
def check_worker_identity(run=subprocess.run,account=None):
 account=account or pwd.getpwnam('yerbas-provider')
 result=run(['/usr/bin/id','-u'],user=account.pw_uid,group=account.pw_gid,extra_groups=[],start_new_session=True,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=10,check=True)
 if result.stdout.strip()!=str(account.pw_uid):raise ValueError('Worker account launch check failed')

def main():
 if os.geteuid()!=0 or os.uname().nodename!='anno2-u26':raise ValueError('Protected anno2 service required')
 check_worker_identity()
 ROOT.mkdir(mode=0o700,exist_ok=True)
 info=ROOT.lstat()
 if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o077:raise ValueError('Private root journal required')
 executor=Executor();jobs=Jobs(Journal(ROOT/'jobs.sqlite3'),executor)
 def stop(*_):raise KeyboardInterrupt
 signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
 server=socket.socket(socket.AF_UNIX)
 try:
  if SOCKET.exists():
   s=SOCKET.lstat()
   if not stat.S_ISSOCK(s.st_mode) or s.st_uid!=0:raise ValueError('Unexpected socket')
   SOCKET.unlink()
  server.bind(str(SOCKET));os.chown(SOCKET,0,1000);SOCKET.chmod(0o660);server.listen(4)
  while True:
   connection,_=server.accept()
   with connection:
    connection.settimeout(45)
    if struct.unpack('3i',connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]!=1000:continue
    try:
     with connection.makefile('rwb') as f:
      raw=f.readline(1025)
      if len(raw)>1024 or not raw.endswith(b'\n'):raise ValueError('Bounded request required')
      try:response={'ok':True,'result':jobs.handle(json.loads(raw))}
      except Exception as e:response={'ok':False,'error':type(e).__name__+': '+str(e)[:180]}
      f.write(json.dumps(response).encode()+b'\n');f.flush()
    except (OSError,ValueError):pass
 except KeyboardInterrupt:pass
 finally:jobs.close();server.close()
if __name__=='__main__':main()
