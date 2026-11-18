"""Anno2 supervisor readiness gate; no gate opens before durable assignment."""
import hashlib,json,re,shlex,subprocess,time
from pathlib import Path
SERVICE='/opt/yerbas-ai/wallet-verifier-610321f45f8bbd6a'
SERVICE_PINS={'client.py': '15dccd6b4bcd1f022b11a8580db5343962124f9f36ed869e2d5f11a221aa8767', 'dataset/manifest.json': 'c814209c81bfb94c58b51db35f729595831f8c9ff78d046802cffa062bfe1fa8', 'dataset/train.jsonl': 'd78ec2c19bc097fc92ba62ef3797530ef4aadefb4968fe29145bf36f8e19a7f6', 'dataset/validation.jsonl': '3b4402864bafb8f305d493c5eb4e4a0fc3beefe96cd6337af92aba054b4585c8', 'jobs.py': 'b4a5270f67db55e924e29fe02789025bea2f610c164cc6f2f5f1daa82bbb4e57', 'relay_guard.py': 'b15defa6d35c3ed8f8c8bf7d2e5b3da5e63e9b09fa18fd9726322e634e7a8239', 'run_gpu_gate.py': 'ce9f71136012a4d466f2c76ad4e77fa1c615b0c846c62f134332be037025d2a8', 'server.py': '529acd3949bbd65bb2b112166a7c006b41cb372248c7c304f7ecd67ebb68130b', 'start_verifier.py': '9ebbc9f532c0d0739e103d0d6d6791d7eaf303ad66f083c9c2bb916b5f1bf4a7', 'supervise.py': '7515ceee8d1e1e6aaa74fd7d213cd188be4129dd261c3f89b1379a64136bb472', 'text_baseline.py': 'cc7059a7095d3c5604f66a36acc7d8ee0ffbe7f95d76b09256deac53d8679dd6', 'text_neural.py': '029e5dea3594350f0489f3dab33cbf1470778c973deefd70e368c890425313b2'}
class Anno2:
 def __init__(self,config,plan):
  self.c=config;self.plan=plan;self.process=None;self.ready=False
  run=plan['binding']['run_id']
  if plan['binding']['provider']!='anno2-u26' or not re.fullmatch('[a-f0-9]{32}',run):raise ValueError('Exact anno2 run required')
  self.run=run;self.box=str(Path(config['evidence_root'])/('run-'+run))
  self.ssh=['/usr/bin/ssh','-i',config['ssh_identity'],'-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+config['known_hosts'],'-o','ConnectTimeout=5']
 def remote(self,argv,**kw):
  return subprocess.run([*self.ssh,'anno2@192.168.0.36',shlex.join(argv)],check=True,timeout=30,**kw)
 def check_files(self):
  pins=self.c['pins']
  if any(name not in pins for name in (self.c['supervisor'],self.c['signer'])):raise ValueError('Pinned remote entrypoints required')
  # JSON arrives over stdin, never as shell source. Public hashes only.
  code="import json,sys,hashlib,socket;from pathlib import Path;pins=json.load(sys.stdin);assert socket.gethostname()=='anno2-u26';assert all(Path(n).is_absolute() and not Path(n).is_symlink() and hashlib.sha256(Path(n).read_bytes()).hexdigest()==h for n,h in pins.items())"
  self.remote(['/usr/bin/python3','-c',code],input=json.dumps(pins),text=True)
  check="""import json,sys,hashlib
from pathlib import Path
c=json.load(sys.stdin)
sys.path.insert(0,str(Path(c['signer']).parent))
from launch import checked,BASE
checked();sys.path.insert(1,str(BASE/'code'))
from coordinator_binding import load
from text_neural import identity
b=load(c['binding'],c['ca'])
assert all(b[k]==c['expected_binding'][k] for k in ('origin','ca_sha256'))
assert identity(c['dataset'])==c['expected_recipe']
m=json.loads((Path(c['wallet_package'])/'RELEASE.json').read_text())
assert m['version']=='5.0.0.0'
assert all(not (Path(c['wallet_package'])/n).is_symlink() and hashlib.sha256((Path(c['wallet_package'])/n).read_bytes()).hexdigest()==m['files'][n] for n in ('yerbasd','yerbas-cli'))
assert {str(p) for p in Path(c['supervisor']).parent.glob('*.py')}.issubset(c['pins'])
"""
  public={k:self.c[k] for k in ('signer','binding','ca','dataset','wallet_package','supervisor','pins')}
  public.update(expected_binding=self.plan['binding'],expected_recipe=self.plan['manifest']['identity'])
  self.remote(['/usr/bin/python3','-c',check],input=json.dumps(public),text=True)
 def service(self,action):
  args=['/usr/bin/python3','-I','-B',SERVICE+'/client.py',action,self.run]
  r=subprocess.run([*self.ssh,'anno2@192.168.0.36',shlex.join(args)],check=True,timeout=55,capture_output=True,text=True)
  result=json.loads(r.stdout)
  if result.get('run_id')!=self.run:raise ValueError('Service run differs')
  return result
 def preflight(self):
  self.check_files()
  check="""import hashlib,json,stat,sys;from pathlib import Path
config=json.load(sys.stdin);root=Path(config['package'])
for name,digest in config['files'].items():
 p=root/name;s=p.lstat()
 assert stat.S_ISREG(s.st_mode) and s.st_uid==0 and not s.st_mode&0o022
 for parent in p.parents:
  s=parent.lstat();assert stat.S_ISDIR(s.st_mode) and s.st_uid==0 and not s.st_mode&0o022
 assert hashlib.sha256(p.read_bytes()).hexdigest()==digest
sys.path.insert(0,str(root));from text_neural import identity
assert identity(root/'dataset')==config['recipe']
"""
  self.remote(['/usr/bin/python3','-I','-B','-c',check],input=json.dumps(dict(package=SERVICE,files=SERVICE_PINS,recipe=self.plan['manifest']['identity'])),text=True)
  self.remote(['mkdir','-m','700',self.box])
  self.service_pending=True
  reply=self.service('prepare')
  if reply['phase']!='ready':raise ValueError('Verifier not ready')
  self.ready=True
 def execute(self,plan):
  if not self.ready or plan!=self.plan:raise ValueError('Fresh matching remote gate required')
  self.ready=False
  reply=self.service('execute')
  if reply['phase']!='running':raise ValueError('Execution outcome uncertain')
  until=time.monotonic()+210
  while True:
   result=self.service('status')
   if result['phase'] in ('complete','failed','cancelled','interrupted'):
    self.service_pending=False
    if result['phase']!='complete' or result['result']!={'exit_code':0}:raise RuntimeError('Verification did not complete; retain evidence')
    break
   if time.monotonic()>until:raise TimeoutError('Verification status timed out; retain run')
   time.sleep(.5)
  base='/var/lib/yerbas-training-experiment/text-demo-'+self.run
  status=json.loads(self.remote(['cat',base+'/status.json'],capture_output=True,text=True).stdout)
  artifact=self.remote(['cat',base+'/verified-public-checkpoint.json'],capture_output=True).stdout
  return status,artifact
 def sign(self,claim):
  if claim['run_id']!=self.run or claim['provider']!='anno2-u26':raise ValueError('Remote claim differs')
  args=['/usr/bin/python3','-I','-B',self.c['signer'],'--package',self.c['wallet_package'],'--binding',self.c['binding'],'--ca',self.c['ca'],'--output',self.box+'/signed.json']
  # Wallet startup/signing may take longer than ordinary SSH checks.
  r=subprocess.run([*self.ssh,'anno2@192.168.0.36',shlex.join(args)],input=json.dumps(claim),text=True,capture_output=True,check=True,timeout=90)
  return json.loads(r.stdout)
 def close(self):
  if getattr(self,'service_pending',False):
   self.service('cancel');self.service_pending=False
