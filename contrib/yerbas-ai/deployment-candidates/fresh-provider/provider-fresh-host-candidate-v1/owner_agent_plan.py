"""Owner-specific agent plan only. No home-directory creation or activation."""
import hashlib,os,re
from pathlib import Path
from verify import ROOT,verify,AGENT_SHA256

def plan(uid,gid,home):
 if any(type(v)is not int or v<=0 for v in (uid,gid)):raise ValueError('Non-root owner IDs required')
 home=Path(home)
 if not re.fullmatch(r'/[a-zA-Z0-9_./-]+',str(home)) or '..' in home.parts or str(home) in ('/','/root'):raise ValueError('Plain absolute owner home required')
 destination=home/'.local/share/yerbas-ai-control-v1'
 if len(os.fsencode(destination/'state/control.sock'))>=108:raise ValueError('Owner socket path exceeds Linux limit')
 verify(ROOT)
 dirs={str(destination/n):dict(uid=uid,gid=gid,mode=0o700) for n in ('','code','workspace','workspace/work','workspace/outputs','state')}
 unit=f'''[Unit]
Description=Yerbas AI per-user control agent (broker submissions disabled)
[Service]
Type=simple
User={uid}
Group={gid}
ExecStart=/usr/bin/python3 -I -B {destination}/code/wallet_agent.py --workspace {destination}/workspace --state {destination}/state
WorkingDirectory={destination}/workspace
UMask=0077
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths={destination}/state {destination}/workspace
RestrictAddressFamilies=AF_UNIX
RestrictSUIDSGID=yes
LockPersonality=yes
MemoryMax=128M
TasksMax=8
Restart=on-failure
RestartSec=3
TimeoutStopSec=5
'''
 return dict(owner_uid=uid,owner_gid=gid,owner_home=str(home),directories=dirs,code=dict(source='owner-agent/wallet_agent.py',sha256=AGENT_SHA256,destination=str(destination/'code/wallet_agent.py'),uid=uid,gid=gid,mode=0o600),unit=dict(destination='/etc/systemd/system/yerbas-wallet-agent.service',content=unit,sha256=hashlib.sha256(unit.encode()).hexdigest(),uid=0,gid=0,mode=0o644),requires_existing_owner_home=True,refuse_existing_destination=True,copy_existing_state=False,activate=False,installable=False,remaining='Separate owner-home ancestry checks and owner-phase writer integration required')
