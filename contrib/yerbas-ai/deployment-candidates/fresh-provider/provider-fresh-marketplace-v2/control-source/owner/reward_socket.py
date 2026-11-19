"""Local reward-request protocol, no secrets in owner configuration."""
import json,os,re,socket,stat,struct,time,uuid
from pathlib import Path
CONFIG=Path('/etc/yerbas-ai/reward-requests.json')
SOCKET='/run/yerbas-ai-reward-request.sock'
CA='/etc/yerbas-ai/future-coordinator-ca.pem'
ORIGIN='https://127.0.0.1:19444'
CA_SHA='a6b0afa9dd3e4e136d746f3ab80829631317daf6b3d81201c0e26faca73a508b'
def trusted(path,private=False):
 p=Path(path)
 for parent in p.parents:
  s=parent.lstat()
  if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise ValueError('Unsafe ancestry')
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  s=os.fstat(fd)
  if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022 or (private and s.st_mode&0o007) or s.st_size>16384:raise ValueError('Unsafe file')
  return os.read(fd,16385)
 finally:os.close(fd)
def unique(pairs):
 d={}
 for k,v in pairs:
  if k in d:raise ValueError('Duplicate field')
  d[k]=v
 return d
def load_config():
 c=json.loads(trusted(CONFIG),object_pairs_hook=unique)
 if set(c)!={'schema','owner_uid','provider_uid','provider'} or type(c['schema']) is not int or c['schema']!=1 or any(type(c[k]) is not int or c[k]<=0 for k in ('owner_uid','provider_uid')) or c['owner_uid']==c['provider_uid'] or c['provider']!=socket.gethostname():raise ValueError('Invalid reward owner configuration')
 return c
def peer_uid(c):return struct.unpack('3i',c.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]
def frame(c):
 data=b'';deadline=time.monotonic()+4
 while b'\n' not in data:
  left=deadline-time.monotonic()
  if left<=0:raise TimeoutError('Deadline')
  c.settimeout(left);part=c.recv(min(1024,8193-len(data)))
  if not part:raise ValueError('Incomplete frame')
  data+=part
  if len(data)>8192:raise ValueError('Oversized frame')
 if data.count(b'\n')!=1 or not data.endswith(b'\n'):raise ValueError('One frame required')
 return json.loads(data,object_pairs_hook=unique)
class SocketClient:
 def __init__(self):
  self.config=load_config()
  if self.config['owner_uid']!=os.getuid():raise ValueError('Wrong wallet owner')
 def exchange(self,method,params):
  s=Path(SOCKET).lstat()
  if not stat.S_ISSOCK(s.st_mode) or s.st_uid!=self.config['provider_uid'] or stat.S_IMODE(s.st_mode)!=0o660:raise ValueError('Wrong socket owner')
  with socket.socket(socket.AF_UNIX) as c:
   c.settimeout(4);c.connect(SOCKET)
   # systemd creates the listener as root; the accepted socket peer identity is root.
   if peer_uid(c)!=0:raise ValueError('System socket not root authenticated')
   rid=uuid.uuid4().hex;c.sendall((json.dumps(dict(v=1,id=rid,method=method,params=params))+'\n').encode());r=frame(c)
   if set(r)!={'v','id','ok','result'} or r['v']!=1 or r['id']!=rid or r['ok'] is not True:raise ValueError('Reward request unavailable')
   return r['result']
 def ready(self):
  try:return self.exchange('rewards.capabilities',{})=={'requests_enabled':True,'payments_enabled':False}
  except Exception:return False
 def reward(self,action,receipt):return self.exchange('rewards.'+action,{'receipt':receipt})

 def cancel_contribution(self,contribution):return self.exchange('contributions.cancel',{'contribution':contribution})
