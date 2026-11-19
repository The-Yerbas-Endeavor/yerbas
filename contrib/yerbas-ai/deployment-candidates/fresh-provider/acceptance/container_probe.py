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
r=subprocess.run(command,capture_output=True,text=True,timeout=1500)
Path('/evidence/install.stdout').write_text(r.stdout);Path('/evidence/install.stderr').write_text(r.stderr)
print(r.stdout[-6000:]);print(r.stderr[-2000:]);print('exit',r.returncode,flush=True)
status=Path('/var/lib/yerbas-ai-install-v2/status.json')
if status.exists():Path('/evidence/install-status.json').write_bytes(status.read_bytes())
for name in ('result.json','commands.log'):
 p=Path('/opt/yerbas-ai/runtime-v1')/name
 if p.exists():Path('/evidence/runtime-'+name).write_bytes(p.read_bytes())
if r.returncode:raise SystemExit(r.returncode)
retry=subprocess.run(command,capture_output=True,text=True,timeout=60)
assert retry.returncode and 'Existing installation preserved' in retry.stdout
Path('/evidence/REINSTALL-REFUSAL.json').write_text(retry.stdout)
assert not list(Path('/etc/systemd/system').glob('*.wants/yerbas*'))
print(json.dumps(dict(passed=True,clean_filesystem_install=True,offline_wheels=True,live_state_copied=False,systemd_boot_tested=False,gpu_tested=False,services_started=False,network='none')))
