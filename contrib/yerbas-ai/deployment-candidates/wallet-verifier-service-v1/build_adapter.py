import json
from pathlib import Path
h=Path(__file__).resolve().parent;m=json.loads((h/'PACKAGE.json').read_text())
source=(Path.home()/'.local/share/yerbas-ai-migration-v1/operator-v2/coordinator-authority-candidate-v1/remote_commands.py').read_text()
start=source.index(' def preflight(self):');end=source.index(' def sign(self,claim):')
new=''' def service(self,action):
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
'''
source=source[:start]+new+source[end:]
source=source[:source.index(' def close(self):')]+''' def close(self):
  if getattr(self,'service_pending',False):
   self.service('cancel');self.service_pending=False
'''
source=source.replace('class Anno2:', 'SERVICE='+repr(m['package'])+'\nSERVICE_PINS='+repr(m['files'])+'\nclass Anno2:')
(h/'remote_commands.py').write_text(source)
