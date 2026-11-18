"""Install persistent owner-only rental settlement preparation; no signing or payment."""
import base64,json,os,pwd,stat,subprocess,time
from pathlib import Path
PAYLOAD={} # GENERATED
DEST=Path('/opt/yerbas-ai/unset') # GENERATED
UNIT='''[Unit]
Description=Yerbas owner rental settlement control
After=local-fs.target
[Service]
User=yerbas-coordinator
Group=yerbas-coordinator
SupplementaryGroups=anno2
ExecStart=/usr/bin/python3 -I -B PACKAGE/server.py
RuntimeDirectory=yerbas-wallet-rental
RuntimeDirectoryMode=0755
UMask=0077
NoNewPrivileges=true
CapabilityBoundingSet=
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/lib/yerbas-coordinator/cutover-6b369f541521422486b3963d9629cf83/state
RestrictAddressFamilies=AF_UNIX
Restart=on-failure
RestartSec=5
[Install]
WantedBy=multi-user.target
'''
def run(args):return subprocess.run(args,check=True,capture_output=True,text=True,timeout=60)
def directory(p):
 s=p.lstat()
 if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise ValueError('Protected directory required')
def put(p,data):
 if os.path.lexists(p):
  s=p.lstat()
  if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022 or p.read_bytes()!=data:raise ValueError('Installed content differs')
 else:
  fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
  with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
def main():
 if os.getuid()!=0 or os.uname().nodename!='anno2-u26' or pwd.getpwnam('anno2').pw_uid!=1000:raise ValueError('Root on anno2 required')
 for p in (DEST.parent,*DEST.parent.parents):directory(p)
 DEST.mkdir(mode=0o755,exist_ok=True);directory(DEST)
 for name,encoded in PAYLOAD.items():
  if Path(name).name!=name:raise ValueError('Flat protected package required')
  put(DEST/name,base64.b64decode(encoded))
 code='import sys;sys.path.insert(0,'+repr(str(DEST))+');import rental;print(rental.execute({"action":"status","quote_id":"0"*32}))'
 run(['runuser','-u','yerbas-coordinator','-g','yerbas-coordinator','-G','anno2','--','/usr/bin/python3','-I','-B','-c',code])
 unit=Path('/etc/systemd/system/yerbas-wallet-rental.service');put(unit,UNIT.replace('PACKAGE',str(DEST)).encode())
 run(['systemd-analyze','verify',str(unit)]);run(['systemctl','daemon-reload']);run(['systemctl','enable','--now',unit.name])
 for _ in range(50):
  if Path('/run/yerbas-wallet-rental/control.sock').exists():break
  time.sleep(.1)
 code="import socket,struct,json;s=socket.socket(socket.AF_UNIX);s.settimeout(15);s.connect('/run/yerbas-wallet-rental/control.sock');s.sendall(b'{\"action\":\"status\",\"quote_id\":\"00000000000000000000000000000000\"}\\n');r=json.loads(s.makefile().readline());assert r['ok'];print(json.dumps(r['result']))"
 run(['runuser','-u','anno2','--','/usr/bin/python3','-I','-B','-c',code])
 print(json.dumps(dict(installed=True,package=str(DEST),owner_socket_verified=True,temporary_quote_controls_required=False,coins_sent=False,gpu_started=False,authority_changed=False)))
if __name__=='__main__':main()
