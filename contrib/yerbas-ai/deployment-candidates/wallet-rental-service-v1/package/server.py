"""Persistent enrolled-owner rental control; no signing or coin broadcast."""
import hashlib,json,os,socket,struct,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
for name,pin in json.loads((ROOT/'manifest.json').read_text()).items():
 p=ROOT/name
 if p.is_symlink() or p.stat().st_uid!=0 or p.stat().st_mode&0o022 or hashlib.sha256(p.read_bytes()).hexdigest()!=pin:raise ValueError('Protected runtime differs')
sys.path.insert(0,str(ROOT))
from rental import execute
SOCKET='/run/yerbas-wallet-rental/control.sock'
def unique(pairs):
 d={}
 for k,v in pairs:
  if k in d:raise ValueError('Duplicate field')
  d[k]=v
 return d

def main():
 if os.getuid()==0:raise ValueError('Coordinator service account required')

 if os.path.lexists(SOCKET):
  import stat
  info=os.lstat(SOCKET)
  if not stat.S_ISSOCK(info.st_mode) or info.st_uid!=os.getuid():raise ValueError('Unexpected socket')
  os.unlink(SOCKET)
 server=socket.socket(socket.AF_UNIX);server.bind(SOCKET);os.chown(SOCKET,-1,1000);os.chmod(SOCKET,0o660);server.listen(4);server.settimeout(2)
 deadline=None
 try:
  while True:
   try:conn,_=server.accept()
   except socket.timeout:continue
   with conn:
    conn.settimeout(10)
    if struct.unpack('3i',conn.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]!=1000:continue
    try:
     with conn.makefile('rwb') as f:
      raw=f.readline(65537)
      if len(raw)>65536 or not raw.endswith(b'\n'):raise ValueError('Bounded complete request required')
      request=json.loads(raw,object_pairs_hook=unique)
      try:result=dict(ok=True,result=execute(request))
      except Exception as e:result=dict(ok=False,error=type(e).__name__+': '+str(e)[:300])
      f.write(json.dumps(result).encode()+b'\n');f.flush()
    except (OSError,ValueError):pass
 finally:
  server.close();os.unlink(SOCKET)
if __name__=='__main__':main()
