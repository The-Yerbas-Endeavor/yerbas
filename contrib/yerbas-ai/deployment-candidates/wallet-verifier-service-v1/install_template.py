"""Install the owner-only fixed verifier. No GPU job is started by installation."""
import base64,hashlib,json,os,pwd,stat,subprocess,time
from pathlib import Path
PAYLOAD = {} # GENERATED
DEST = Path('/opt/yerbas-ai/unset') # GENERATED
UNIT='''[Unit]
Description=Yerbas fixed testnet verification service
After=local-fs.target
[Service]
Type=simple
User=root
Group=root
ExecStart=/usr/bin/python3 -I -B PACKAGE/server.py
StateDirectory=yerbas-wallet-verifier-v1
StateDirectoryMode=0700
RuntimeDirectory=yerbas-wallet-verifier
RuntimeDirectoryMode=0755
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
CapabilityBoundingSet=CAP_CHOWN CAP_SETUID CAP_SETGID CAP_DAC_OVERRIDE
AmbientCapabilities=CAP_SETUID
ReadWritePaths=/var/lib/yerbas-training-experiment /run/lock
RestrictAddressFamilies=AF_UNIX AF_NETLINK
KillMode=control-group
TimeoutStopSec=70
Restart=no
[Install]
WantedBy=multi-user.target
'''
def run(args,timeout=60):return subprocess.run(args,check=True,capture_output=True,text=True,timeout=timeout)
def directory(path):
 s=path.lstat()
 if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise ValueError('Root-controlled directory required')
def put(path,data):
 if os.path.lexists(path):
  s=path.lstat()
  if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022 or path.read_bytes()!=data:raise ValueError('Existing installed content differs')
 else:
  fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
  with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
def main():
 if os.getuid()!=0 or os.uname().nodename!='anno2-u26' or pwd.getpwnam('anno2').pw_uid!=1000:raise ValueError('Root on enrolled anno2 required')
 for p in (DEST.parent,*DEST.parent.parents):directory(p)
 DEST.mkdir(mode=0o755,exist_ok=True);directory(DEST)
 for name,encoded in PAYLOAD.items():
  relative=Path(name)
  if relative.is_absolute() or '..' in relative.parts:raise ValueError('Invalid package path')
  path=DEST/name;path.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
  for parent in (path.parent,*path.parent.parents):directory(parent)
  put(path,base64.b64decode(encoded))
 run(['/usr/bin/python3','-I','-B','-c','import sys;sys.path.insert(0,'+repr(str(DEST))+');import jobs,server,text_neural,text_baseline;from text_baseline import load_dataset;load_dataset('+repr(str(DEST/'dataset'))+')'])
 unit=Path('/etc/systemd/system/yerbas-wallet-verifier.service')
 desired=UNIT.replace('PACKAGE',str(DEST)).encode()
 if unit.exists() and unit.read_bytes()!=desired:
  previous=unit.read_bytes()
  allowed=[UNIT.replace('AmbientCapabilities=CAP_SETUID\n','').replace('PACKAGE','/opt/yerbas-ai/wallet-verifier-1bc5410f81a18e73').encode(),UNIT.replace('PACKAGE','/opt/yerbas-ai/wallet-verifier-79a2ef62940957fb').encode()]
  if previous not in allowed:raise ValueError('Unknown prior service')
  info=unit.lstat()
  if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or unit.read_bytes()!=previous:raise ValueError('Unexpected service definition; preserve it')
  import sqlite3
  with sqlite3.connect('file:/var/lib/yerbas-wallet-verifier-v1/jobs.sqlite3?mode=ro',uri=True) as db:
   if db.execute("SELECT 1 FROM jobs WHERE phase IN ('preparing','ready','running')").fetchone():raise ValueError('Active verifier must finish before upgrade')
  run(['systemctl','stop',unit.name])
  put(Path('/var/lib/yerbas-wallet-verifier-v1/service-before-account-launch-'+hashlib.sha256(previous).hexdigest()[:16]),previous)
  temporary=unit.with_suffix('.service.new')
  put(temporary,desired);os.replace(temporary,unit)
 else:put(unit,desired)
 run(['systemd-analyze','verify',str(unit)])
 run(['systemctl','daemon-reload']);run(['systemctl','enable','--now',unit.name])
 for _ in range(50):
  if Path('/run/yerbas-wallet-verifier/control.sock').exists():break
  time.sleep(.1)
 result=run(['runuser','-u','anno2','--','/usr/bin/python3','-I','-B',str(DEST/'client.py'),'status','0'*32])
 if json.loads(result.stdout)['phase']!='absent':raise ValueError('Unexpected diagnostic run')
 print(json.dumps(dict(installed=True,package=str(DEST),owner_socket_verified=True,service_enabled=True,gpu_started=False,coins_sent=False,keys_changed=False)))
if __name__=='__main__':main()
