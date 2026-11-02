"""Protected receipt replay entry point; only --run-id is accepted from caller.
Deployment must pin this script and receipt_transport.py in a root-owned directory.
No automatic plan issuance, training, funding, journal rebinding or deadline reset.
"""
import argparse,hashlib,json,os,re,stat,sys,signal,threading
from pathlib import Path
CONFIG=Path('/etc/yerbas-ai/receipt-migration-v1.json')

def trusted(path,owner=0,limit=65536):
 path=Path(path)
 if not path.is_absolute() or '..' in path.parts:raise ValueError('Absolute trusted path required')
 for parent in path.parents:
  s=parent.lstat()
  if not stat.S_ISDIR(s.st_mode) or s.st_uid not in (0,owner) or s.st_mode&0o022:raise ValueError('Unsafe ancestry')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  s=os.fstat(fd)
  if not stat.S_ISREG(s.st_mode) or s.st_uid!=owner or s.st_mode&0o022 or s.st_size>limit:raise ValueError('Untrusted bounded file')
  with os.fdopen(fd,'rb',closefd=False) as f:raw=f.read(limit+1)
  if len(raw)>limit:raise ValueError('Oversized file')
  return raw
 finally:os.close(fd)
def read(path,owner=0):
 def unique(pairs):
  result={}
  for k,v in pairs:
   if k in result:raise ValueError('Duplicate JSON key')
   result[k]=v
  return result
 value=json.loads(trusted(path,owner),object_pairs_hook=unique)
 if not isinstance(value,dict):raise ValueError('JSON object required')
 return value

def validate_selection(config,run_id):
 if not re.fullmatch('[a-f0-9]{32}',run_id):raise ValueError('Invalid run ID')
 if set(config)!={'schema','runtime_dir','runtime_files','bridge_sha256','jobs'} or type(config['schema']) is not int or config['schema']!=1:raise ValueError('Exact root deployment config required')
 if not isinstance(config['jobs'],dict) or run_id not in config['jobs']:raise ValueError('Run has no operator migration approval')
 job=config['jobs'][run_id]
 if not isinstance(job,dict) or set(job)!={'policy','request','plan','credentials'}:raise ValueError('Exact per-run paths required')
 for path in (config['runtime_dir'],*job.values()):
  if not isinstance(path,str) or not Path(path).is_absolute() or '..' in Path(path).parts:raise ValueError('Fixed absolute paths required')
 return job

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-id',required=True);a=p.parse_args()
 if os.getuid()==0:raise ValueError('Dedicated provider account required')
 config=read(CONFIG);job=validate_selection(config,a.run_id)
 runtime=Path(config['runtime_dir']);pins=config['runtime_files']
 if not isinstance(pins,dict) or not 1<=len(pins)<=64 or not {'provider_executor.py','text_worker.py','text_https.py','text_neural.py'}.issubset(pins):raise ValueError('Pinned runtime closure required')
 if {p.name for p in runtime.glob('*.py')}!=set(pins):raise ValueError('Runtime closure differs')
 for name,digest in pins.items():
  if Path(name).name!=name or hashlib.sha256(trusted(runtime/name,limit=16*1024*1024)).hexdigest()!=digest:raise ValueError('Runtime checksum differs')
 bridge=Path(__file__).with_name('receipt_transport.py')
 if hashlib.sha256(trusted(bridge)).hexdigest()!=config['bridge_sha256']:raise ValueError('Replay bridge checksum differs')
 sys.path[:0]=[str(bridge.parent),str(runtime)]
 import provider_executor as executor
 from text_neural import identity
 from receipt_transport import replay,digest
 policy=executor.verify_policy(read(job['policy']))
 if policy['provider_uid']!=os.getuid() or os.path.realpath(sys.executable)!=os.path.realpath(policy['python']):raise ValueError('Wrong provider or runtime')
 executor.verify_installed_files(policy)
 request=executor.validate_request(read(job['request'],os.getuid()))
 if request['run_id']!=a.run_id:raise ValueError('Requested run differs')
 executor.require_service_boundary(a.run_id,replay_only=True)
 plan=read(job['plan']);credentials=read(job['credentials'])
 trusted(credentials['ca'])
 state=Path(policy['state'])/(a.run_id+'-'+request['contribution'])
 for directory in (Path(policy['state']),state,state/'worker'):
  s=directory.lstat()
  if not stat.S_ISDIR(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&0o077:raise ValueError('Private retained state required')
 saved=read(state/'executor.json',os.getuid());worker=read(state/'config.json',os.getuid())
 if saved.get('binding',{}).get('policy')!=digest(policy):raise ValueError('Original policy differs')
 if worker!=executor.worker_config(policy,read(policy['credentials']),request):raise ValueError('Original worker configuration differs')
 approved=identity(Path(policy['dataset']))
 if approved!=policy['expected_identity']:raise ValueError('Recipe changed')
 stop=threading.Event()
 for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
 for lock in policy['locks']:
  executor.require_root_ancestry(lock)
  info=Path(lock).lstat()
  if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o007:raise ValueError('Unsafe shared lock')
 def timed_out(*_):raise TimeoutError('Receipt migration upload budget exhausted')
 signal.signal(signal.SIGALRM,timed_out);signal.setitimer(signal.ITIMER_REAL,100)
 try:
  with executor.gpu_locks(policy['locks']):
   result=replay(state/'worker',plan,saved,worker,credentials,request,approved,stop)
 finally:signal.setitimer(signal.ITIMER_REAL,0)
 print(json.dumps(dict(receipt=result,training_executed=False,deadline_extended=False)))
if __name__=='__main__':main()
