import base64,hashlib,json
from pathlib import Path
h=Path(__file__).resolve().parent
sources=[h.parent/'wallet-verifier-service-v1/install.py',h.parent/'wallet-rental-service-v1/install.py']
payload={p.parent.name:base64.b64encode(p.read_bytes()).decode() for p in sources}
pins={p.parent.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
code='''"""One installation entrypoint for wallet verification and rental control on anno2."""
import base64,hashlib,json,os,stat,subprocess
from pathlib import Path
PAYLOAD=PAYLOAD_VALUE
PINS=PINS_VALUE
def main():
 if os.getuid()!=0 or os.uname().nodename!='anno2-u26':raise ValueError('Root on anno2 required')
 root=Path('/opt/yerbas-ai/wallet-service-installers')
 for p in (root.parent,*root.parent.parents):
  s=p.lstat()
  if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise ValueError('Protected installation parent required')
 root.mkdir(mode=0o755,exist_ok=True)
 s=root.lstat()
 if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise ValueError('Protected installer directory required')
 for name,encoded in PAYLOAD.items():
  raw=base64.b64decode(encoded)
  if hashlib.sha256(raw).hexdigest()!=PINS[name]:raise ValueError('Installer hash differs')
  path=root/(name+'-'+PINS[name][:16]+'.py')
  if os.path.lexists(path):
   s=path.lstat()
   if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022 or path.read_bytes()!=raw:raise ValueError('Retained installer differs')
  else:
   fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
   with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
  subprocess.run(['/usr/bin/python3','-I','-B',str(path)],check=True,timeout=180)
 print(json.dumps(dict(installed=True,services=2,coins_sent=False,gpu_started=False,keys_changed=False)))
if __name__=='__main__':main()
'''.replace('PAYLOAD_VALUE',repr(payload)).replace('PINS_VALUE',repr(pins))
(h/'install_anno2.py').write_text(code);(h/'install_anno2.py').chmod(0o600)
(h/'MANIFEST.json').write_text(json.dumps(dict(installers=pins,sha256=hashlib.sha256(code.encode()).hexdigest()),indent=2)+'\n')
