"""One fixed HTTPS text contribution under an installed unprivileged service.

Not an enrollment server. Root-owned policy/credentials and cgroup supervision
must be provisioned before deployment. Never accepts a command or model URL from
an owner job request. Does not install services or modify legacy state.
"""
import argparse
import contextlib
import fcntl
import hashlib
import json
import ipaddress
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

HEX = re.compile(r'[a-f0-9]{64}\Z')
RUN = re.compile(r'[a-f0-9]{32}\Z')
NAME = re.compile(r'[a-zA-Z0-9_-]{1,64}\Z')
WALL_SECONDS = 240
STOP_SECONDS = 25


def read_json(path, *, owner, limit=65536):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=owner or info.st_mode&0o022 or info.st_size>limit:
            raise ValueError('Untrusted or oversized configuration')
        with os.fdopen(fd,'rb',closefd=False) as stream:raw=stream.read(limit+1)
        if len(raw)>limit:raise ValueError('Oversized configuration')
        def unique(pairs):
            value={}
            for k,v in pairs:
                if k in value:raise ValueError('Duplicate configuration field')
                value[k]=v
            return value
        value=json.loads(raw,object_pairs_hook=unique)
        if not isinstance(value,dict):raise ValueError('Configuration must be an object')
        return value
    finally:os.close(fd)


def validate_request(value):
    if set(value)!={'run_id','contribution'} or not isinstance(value['run_id'],str) or not RUN.fullmatch(value['run_id']) or not isinstance(value['contribution'],str) or not NAME.fullmatch(value['contribution']):
        raise ValueError('Only a run ID and contribution ID are accepted')
    return value


def verify_policy(value):
    keys={'schema','provider_uid','gpu','python','worker','dataset','credentials','state','locks','files','expected_identity'}
    if value.get('schema')==2:keys.add('measurement')
    if set(value)!=keys or type(value['schema']) is not int or value['schema'] not in (1,2):
        raise ValueError('Unsupported executor policy')
    if type(value['provider_uid']) is not int or value['provider_uid']<=0 or value['gpu'] not in ('0','1'):
        raise ValueError('Invalid provider account or GPU')
    for key in ('python','worker','dataset','credentials','state'):
        if not isinstance(value[key],str) or not value[key].startswith('/') or '..' in Path(value[key]).parts:
            raise ValueError('Policy requires absolute fixed paths')
    if not isinstance(value['locks'],list) or len(value['locks'])!=2 or len(set(value['locks']))!=2 or any(not isinstance(p,str) or not p.startswith('/') for p in value['locks']):
        raise ValueError('Both legacy pilot locks must be provisioned')
    if set(value['expected_identity'])!={'runner','dataset','config'} or any(not isinstance(v,str) or not HEX.fullmatch(v) for v in value['expected_identity'].values()):
        raise ValueError('Invalid approved identity')
    if not isinstance(value['files'],dict) or not value['files'] or len(value['files'])>64:
        raise ValueError('Missing pinned source and dataset manifest')
    required={value['worker']}|{str(Path(value['dataset'])/n) for n in ('manifest.json','train.jsonl','validation.jsonl')}
    if not required.issubset(value['files']):raise ValueError('Worker and corpus must be pinned')
    for name,digest in value['files'].items():
        if not name.startswith('/') or not isinstance(digest,str) or not HEX.fullmatch(digest):raise ValueError('Invalid installed manifest')
    if value['schema']==2:
        if value['measurement']!='training-attribution-v1':raise ValueError('Unsupported measurement mode')
        from measurement_policy import verify_measurement_files
        verify_measurement_files(value)
    return value


def worker_config(policy,credentials,request):
    config=dict(credentials,expected_identity=policy['expected_identity'],dataset=policy['dataset'],contribution=request['contribution'])
    if policy['schema']==2:config['training_attribution']=True
    return config


def require_root_ancestry(path):
    for parent in Path(path).parents:
        info=parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
            raise ValueError('Installed ancestry is not root controlled')


def require_service_boundary(run_id, cgroup_text=None, *, replay_only=False):
    text=Path('/proc/self/cgroup').read_text() if cgroup_text is None else cgroup_text
    expected=('/yerbas-text-replay@' if replay_only else '/yerbas-text-provider@')+run_id+'.service'
    if not any(line.startswith('0::') and line.endswith(expected) for line in text.splitlines()):
        raise ValueError('Dedicated systemd cgroup is required for descendant cleanup')


def verify_installed_files(policy):
    # Only provisioned root-owned files; writable development code is not accepted.
    for name,digest in policy['files'].items():
        path=Path(name)
        require_root_ancestry(path)
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or info.st_size>16*1024*1024:
                raise ValueError('Untrusted installed file')
            with os.fdopen(fd,'rb',closefd=False) as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
            if actual!=digest:raise ValueError('Installed source or dataset changed')
        finally:os.close(fd)


def atomic(path,value):
    temporary=path.with_name(path.name+'.new')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(value,stream,sort_keys=True,allow_nan=False);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        try:temporary.unlink()
        except FileNotFoundError:pass


@contextlib.contextmanager
def gpu_locks(paths):
    held=[]
    try:
        for path in paths:
            fd=os.open(path,os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK)
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):os.close(fd);raise ValueError('Invalid GPU lock')
            held.append(fd);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally:
        for fd in reversed(held):os.close(fd)


def reservation(path,binding,now=None):
    now=time.time() if now is None else now
    if path.exists():
        value=read_json(path,owner=os.getuid())
        if value.get('binding')!=binding:raise ValueError('Retained job binding differs')
        if not (type(value.get('started_at')) in (int,float) and type(value.get('deadline')) in (int,float)) or not value['started_at']<=now<value['deadline']<=value['started_at']+WALL_SECONDS:
            raise ValueError('Original executor deadline exhausted or clock regressed')
        return value['deadline']-now
    atomic(path,{'binding':binding,'started_at':now,'deadline':now+WALL_SECONDS})
    return WALL_SECONDS


def execution_budget(path,binding,*,replay_only=False,now=None):
    if replay_only:
        record=read_json(path,owner=os.getuid())
        if record.get('binding')!=binding:raise ValueError('Retained replay binding differs')
        return 100  # Upload only; never rewrite or extend the training reservation.
    return reservation(path,binding,now)


def supervise(command,env,stop,seconds,grace=STOP_SECONDS):
    """Own one process group. The installed unit must also use KillMode=control-group."""
    if stop.is_set():return {'exit_code':None,'reason':'owner_stop','launched':False}
    child=subprocess.Popen(command,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
    started=time.monotonic();shutdown=None;reason='completed';seen=0
    selector=selectors.DefaultSelector();selector.register(child.stdout,selectors.EVENT_READ)
    try:
        while child.poll() is None:
            now=time.monotonic()
            if shutdown is None and (stop.is_set() or now-started>=seconds):
                reason='owner_stop' if stop.is_set() else 'runtime_limit';shutdown=now
                try:os.killpg(child.pid,signal.SIGTERM)
                except ProcessLookupError:pass
            if shutdown is not None and now-shutdown>=grace:
                try:os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            for key,_ in selector.select(.05):
                chunk=os.read(key.fd,32768);seen+=len(chunk)
                if not chunk:selector.unregister(key.fileobj)
                if seen>1024*1024 and shutdown is None:
                    reason='output_limit';shutdown=time.monotonic()
                    try:os.killpg(child.pid,signal.SIGTERM)
                    except ProcessLookupError:pass
        code=child.wait()
        if code and reason=='completed':reason='worker_failed'
        return {'exit_code':code,'reason':reason,'launched':True,'elapsed_seconds':round(time.monotonic()-started,3)}
    finally:
        selector.close();child.stdout.close()
        # Cleanup same-group descendants even after their parent exits.
        try:os.killpg(child.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        child.wait()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy',type=Path,required=True);parser.add_argument('--request',type=Path,required=True)
    parser.add_argument('--replay-only',action='store_true')
    args=parser.parse_args()
    if os.getuid()==0:raise SystemExit('Executor must run as the dedicated provider, never root')
    os.umask(0o077)
    require_root_ancestry(args.policy)
    policy=verify_policy(read_json(args.policy,owner=0))
    if os.getuid()!=policy['provider_uid']:raise ValueError('Wrong provider account')
    if os.path.realpath(sys.executable)!=os.path.realpath(policy['python']):raise ValueError('Wrong installed Python runtime')
    verify_installed_files(policy)
    request=validate_request(read_json(args.request,owner=os.getuid()))
    require_service_boundary(request['run_id'],replay_only=args.replay_only)
    require_root_ancestry(policy['credentials'])
    if Path(policy['credentials']).lstat().st_mode & 0o007:raise ValueError('Enrollment credentials cannot be world accessible')
    credentials=read_json(policy['credentials'],owner=0)
    if set(credentials)!={'url','token','ca','provider'}:raise ValueError('Invalid enrolled provider credentials')
    url=urlsplit(credentials['url'])
    if url.scheme!='https' or not url.hostname or url.username or url.password or url.fragment or url.query:raise ValueError('Verified HTTPS enrollment required')
    address=ipaddress.ip_address(url.hostname)
    if not any(address in ipaddress.ip_network(net) for net in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')):raise ValueError('Private LAN coordinator address required')
    if not isinstance(credentials['token'],str) or not credentials['token'] or not NAME.fullmatch(credentials['provider']):raise ValueError('Invalid provider enrollment')
    if credentials['ca'] not in policy['files']:raise ValueError('CA must be pinned in installed policy')
    root=Path(policy['state']);info=root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise ValueError('Private provider state required')
    if shutil.disk_usage(root).free < (16*1024**2 if args.replay_only else 12*1024**3):raise ValueError('Insufficient free space for requested mode')
    stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    for lock in policy['locks']:
        require_root_ancestry(lock)
        info=Path(lock).lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o007:raise ValueError('Shared GPU lock must be root-owned and not world accessible')
    with gpu_locks(policy['locks']):
        busy='' if args.replay_only else subprocess.check_output(['/usr/bin/nvidia-smi','--id='+policy['gpu'],'--query-compute-apps=pid','--format=csv,noheader'],text=True,timeout=10)
        if busy.strip():raise ValueError('GPU busy; no workloads stopped')
        state=root/(request['run_id']+'-'+request['contribution'])
        if args.replay_only and not state.exists():raise ValueError('Retained recovery state missing')
        state.mkdir(mode=0o700,exist_ok=True)
        info=state.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise ValueError('Unsafe retained state')
        binding={'request':request,'policy':hashlib.sha256(json.dumps(policy,sort_keys=True).encode()).hexdigest(),'enrollment':hashlib.sha256(json.dumps(credentials,sort_keys=True).encode()).hexdigest()}
        remaining=execution_budget(state/'executor.json',binding,replay_only=args.replay_only)
        config=worker_config(policy,credentials,request)
        config_path=state/'config.json'
        if config_path.exists():
            if read_json(config_path,owner=os.getuid())!=config:raise ValueError('Retained configuration differs')
        elif args.replay_only:raise ValueError('Retained replay configuration missing')
        else:atomic(config_path,config)
        env={'PATH':'/usr/bin:/bin','HOME':str(root),'CUDA_VISIBLE_DEVICES':policy['gpu'],'YERBAS_PHYSICAL_GPU':policy['gpu'],'CUBLAS_WORKSPACE_CONFIG':':4096:8','PYTHONNOUSERSITE':'1'}
        worker=str(Path(policy['worker']).with_name('text_replay.py')) if args.replay_only else policy['worker']
        if worker not in policy['files']:raise ValueError('Worker is not pinned in installed policy')
        command=[policy['python'],'-B',worker,'--config',str(config_path),'--state',str(state/'worker')]
        result=supervise(command,env,stop,remaining)
        # A successful process is not independent evidence of accepted work.
        result.update(run_id=request['run_id'],contribution=request['contribution'],receipt_verified=False,replay_only=args.replay_only,training_allowed=not args.replay_only)
        atomic(state/('replay-result.json' if args.replay_only else 'executor-result.json'),result);print(json.dumps(result))
        if result['reason']!='completed' or result['exit_code']!=0:raise SystemExit(1)

if __name__=='__main__':main()
