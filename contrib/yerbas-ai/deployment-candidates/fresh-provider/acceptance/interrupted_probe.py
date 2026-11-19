"""Disabled clean-filesystem install; no live state or network is mounted."""
import json,os,subprocess,sys
from pathlib import Path
if not Path('/CLEAN_INSTALL_CONTAINER').exists():raise ValueError('Disposable container required')
for args in (['groupadd','-g','2000','test-owner'],['groupadd','-g','2001','yerbas-provider'],['useradd','-u','2000','-g','2000','-m','test-owner'],['useradd','-u','2001','-g','2001','-M','-s','/usr/sbin/nologin','yerbas-provider']):subprocess.run(args,check=True)
for name in ('/etc/tmpfiles.d','/etc/systemd/system'):
 Path(name).mkdir(parents=True,exist_ok=True)
h=Path('/home/test-owner');(h/'.local/share').mkdir(parents=True);os.chown(h,2000,2000)
for p in (h/'.local',h/'.local/share'):os.chown(p,2000,2000);p.chmod(0o700)
command=['/usr/bin/python3','-I','-B','/candidate/provider-fresh-marketplace-v2/fresh_install.py','--owner','test-owner','--wheels','/wheels','--offline-services','--install-disabled']
import signal,time,hashlib
with open('/evidence/interrupted.stdout','w') as log:
 process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
 status=Path('/var/lib/yerbas-ai-install-v2/status.json');end=time.monotonic()+60
 while True:
  if status.exists():
   state=json.loads(status.read_text())
   if state['phase']=='runtime_started':break
  if process.poll() is not None or time.monotonic()>end:raise RuntimeError('Install did not reach interruption point')
  time.sleep(.02)
 os.killpg(process.pid,signal.SIGKILL);process.wait()
 journal=Path('/var/lib/yerbas-ai-install-v2/private/root.jsonl')
 before=hashlib.sha256(journal.read_bytes()).hexdigest()
 retry=subprocess.run(command,capture_output=True,text=True,timeout=60)
 assert retry.returncode and 'Existing installation preserved' in retry.stdout
 assert hashlib.sha256(journal.read_bytes()).hexdigest()==before
 assert not list(Path('/etc/systemd/system').glob('*.wants/yerbas*'))
 result=dict(passed=True,interrupted_phase='runtime_started',root_entries=state['root']['entries'],retry_refused=True,journal_preserved=True,services_started=False,gpu_started=False,coins_sent=False)
 Path('/evidence/INTERRUPTED-INSTALL.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result))
