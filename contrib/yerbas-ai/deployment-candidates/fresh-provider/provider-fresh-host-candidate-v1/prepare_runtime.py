"""Prepare a new offline runtime staging tree; never changes an installed provider."""
import argparse,hashlib,json,os,platform,re,stat,subprocess,sys
from pathlib import Path
from verify import ROOT,verify
from runtime_inventory import inspect

CPU_CHECK="""import json,torch
assert not torch.cuda.is_initialized()
x=torch.tensor([2.],requires_grad=True);(x*x).sum().backward()
assert x.grad.item()==4. and not torch.cuda.is_initialized()
print(json.dumps(dict(torch=torch.__version__,backward_passed=True,cuda_initialized=False)))
"""
def normalize(name):return re.sub(r'[-_.]+','-',name).lower()
def versions_match(expected,installed):
 wanted={normalize(p['name']):p['version'] for p in expected['packages']}
 actual={normalize(p['name']):p['version'] for p in installed}
 if wanted!=actual:raise ValueError('Installed distribution set differs from pinned manifest')
 return len(wanted)
def check_destination(destination):
 p=Path(destination)
 if not p.is_absolute() or str(p)!=str(destination) or '..' in p.parts:raise ValueError('Canonical absolute destination required')
 for parent in reversed(p.parents):
  info=parent.lstat()
  sticky_root=info.st_uid==0 and bool(info.st_mode&stat.S_ISVTX)
  if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0,os.getuid()) or (stat.S_IMODE(info.st_mode)&0o022 and not sticky_root):raise ValueError('Trusted parent or root-owned sticky temporary directory required: '+str(parent))
 if os.path.lexists(p):raise ValueError('Existing destination preserved')
 return p

def copy_wheel(source,target,expected):
 fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or info.st_size>4*1024**3:raise ValueError('Bounded regular wheel required')
  h=hashlib.sha256();size=0
  with target.open('xb') as out:
   while True:
    chunk=os.read(fd,1024*1024)
    if not chunk:break
    size+=len(chunk)
    if size>info.st_size:raise ValueError('Wheel grew during snapshot')
    out.write(chunk);h.update(chunk)
   out.flush();os.fsync(out.fileno())
  after=os.fstat(fd)
  if size!=info.st_size or (info.st_mtime_ns,info.st_ctime_ns)!=(after.st_mtime_ns,after.st_ctime_ns) or h.hexdigest()!=expected:raise ValueError('Wheel snapshot hash or metadata changed')
 finally:os.close(fd)

def prepare(destination,wheels,*,_root_mode=False):
 # Root deployment is a separate step: this command cannot overwrite /opt.
 if _root_mode:
  if os.getuid()!=0:raise ValueError('Root preparation requires root')
 elif os.getuid()==0:raise ValueError('Run staging as an unprivileged owner')
 if sys.implementation.name!='cpython' or sys.version_info[:2]!=(3,14) or platform.machine()!='x86_64':raise ValueError('Pinned CPython 3.14 x86_64 profile required')
 verify(ROOT);destination=check_destination(destination)
 manifest=json.loads((ROOT/'runtime/WHEELS.json').read_text())
 inventory=inspect(manifest,wheels)
 if not inventory['passed']:raise ValueError('Wheel inventory incomplete or changed')
 destination.mkdir(mode=0o700) # exclusive: never repair or overwrite an old attempt
 report=dict(passed=False,scope='new offline runtime tree; activation is a separate operation',destination=str(destination),network_used=False,installed_provider_runtimes_changed=False,gpu_started=False)
 env={'PATH':'/usr/bin:/bin','HOME':str(destination),'CUDA_VISIBLE_DEVICES':'','PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1','LC_ALL':'C.UTF-8'}
 def command(args,cwd=None):
  result=subprocess.run(args,cwd=cwd or destination,env=env,capture_output=True,text=True,timeout=900)
  with (destination/'commands.log').open('a') as log:log.write(json.dumps(args)+'\n'+result.stdout+result.stderr+'\n')
  if result.returncode:raise RuntimeError('Runtime command failed; retained commands.log')
  return result.stdout
 try:
  cache=destination/'wheels';cache.mkdir(mode=0o700)
  for item in manifest['packages']:copy_wheel(Path(wheels)/item['filename'],cache/item['filename'],item['sha256'])
  report['snapshotted_wheels']=len(manifest['packages'])
  req=destination/'requirements.txt';req.write_bytes((ROOT/'runtime/offline-requirements.txt').read_bytes())
  venv=destination/'venv'
  command([sys.executable,'-I','-m','venv','--without-pip','--copies',str(venv)])
  pip=[sys.executable,'-I','-m','pip','--isolated','--python',str(venv/'bin/python')]
  command(pip+['install','--no-index','--no-deps','--require-hashes','--no-compile','--no-cache-dir','--disable-pip-version-check','-r',str(req)],cwd=cache)
  report['dependency_check']=command(pip+['check']).strip()
  installed=json.loads(command([str(venv/'bin/python'),'-I','-B','-c',"import importlib.metadata as m,json;print(json.dumps([dict(name=d.metadata['Name'],version=d.version) for d in m.distributions()]))"]))
  report['versions_matched']=versions_match(manifest,installed)
  report['cpu_smoke']=json.loads(command([str(venv/'bin/python'),'-I','-B','-c',CPU_CHECK]))
  report['passed']=True
 except Exception as exc:
  report['error']=type(exc).__name__+': '+str(exc)
 finally:(destination/'result.json').write_text(json.dumps(report,indent=2)+'\n')
 return report

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--destination',required=True);p.add_argument('--wheels',type=Path,required=True);p.add_argument('--run',action='store_true');a=p.parse_args()
 if not a.run:
  check_destination(a.destination);print(json.dumps(dict(executed=False,offline_only=True,existing_destination_refused=True)));return 0
 result=prepare(a.destination,a.wheels);print(json.dumps(result,indent=2));return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
