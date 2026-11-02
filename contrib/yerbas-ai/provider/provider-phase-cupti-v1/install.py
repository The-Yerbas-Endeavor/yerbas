"""Install isolated direct runtime; optional future-job routing, no job starts."""
import argparse,fcntl,hashlib,json,os,pwd,stat,subprocess,tempfile
from pathlib import Path
from direct_policy import PINS
from prepare_direct_policy import prepare
from provider_executor import read_json,require_root_ancestry,verify_installed_files
from stage_files import stage_files
PACKAGE=Path(__file__).resolve().parent
TARGET=Path('/opt/yerbas-ai/provider-phase-cupti-v1')
POLICY=Path('/etc/yerbas-ai/provider-phase-cupti-v1.json')
STATE=Path('/var/lib/yerbas-ai-provider/phase-cupti-jobs-v1')
SELECTOR=Path('/etc/yerbas-ai/provider-phase-cupti-mode.json')
CURRENT=Path('/etc/yerbas-ai/provider-direct-cupti-v1.json')
ROOT_FILES=('provider_executor.py','measurement_policy.py','direct_policy.py','phase_router.py','bootstrap.py')

def payload(package):
    manifest=json.loads((package/'INSTALL-SHA256.json').read_text());result={}
    for name,relative in [(n,n) for n in ROOT_FILES]+[(n,'payload/'+n) for n in PINS]:
        path=package/relative
        if path.is_symlink() or not path.is_file():raise ValueError('Regular package file required')
        raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest()
        if sha!=manifest.get(relative) or (name in PINS and sha!=PINS[name]):raise ValueError('Package hash differs: '+relative)
        result[name]=raw
    result['RUNTIME.json']=(json.dumps(dict(schema=1,files={n:hashlib.sha256(v).hexdigest() for n,v in result.items()}),sort_keys=True)+'\n').encode()
    return result

def override(mode):
    if mode not in ('provider','replay'):raise ValueError('Unknown unit mode')
    return '[Service]\nExecStart=\nExecStart=/opt/yerbas-ai/runtime-v1/venv/bin/python -I -B /opt/yerbas-ai/provider-phase-cupti-v1/bootstrap.py --request /var/lib/yerbas-ai-provider/requests/%i.json'+(' --replay-only' if mode=='replay' else '')+'\nReadWritePaths=/var/lib/yerbas-ai-provider/phase-cupti-jobs-v1\n'

def exclusive(path,raw,mode=0o644):
    require_root_ancestry(path)
    if os.path.lexists(path):
        s=path.lstat()
        if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022 or path.read_bytes()!=raw:raise ValueError('Existing file differs: '+str(path))
        return
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    path.chmod(mode)

def routing_targets():
    targets=[]
    for mode in ('provider','replay'):
        unit='yerbas-text-'+mode+'@.service'
        folder=Path('/etc/systemd/system')/(unit+'.d');target=folder/'90-phase-cupti.conf'
        require_root_ancestry(target)
        instance=unit.replace('@.service','@'+'0'*32+'.service')
        paths=subprocess.check_output(['systemctl','show',instance,'-p','DropInPaths','--value'],text=True,timeout=10).split()
        expected={str(folder/'50-measured-router.conf'),str(folder/('70-future-'+mode+'.conf'))}
        expected.add(str(folder/'80-direct-cupti.conf'))
        if mode=='replay':expected.add(str(folder/'60-migration-dispatch.conf'))
        if set(paths) not in (expected,expected|{str(target)}):raise ValueError('Unreviewed service overrides')
        if target.exists() and target.read_text()!=override(mode):raise ValueError('Existing direct override differs')
        targets.append((target,override(mode).encode()))
    return targets

def select(enabled):
    old=read_json(SELECTOR,owner=0)
    if set(old)!={'enabled'} or type(old['enabled']) is not bool:raise ValueError('Invalid direct selector')
    fd,name=tempfile.mkstemp(prefix='.phase-mode-',dir=SELECTOR.parent)
    try:
        with os.fdopen(fd,'w') as stream:json.dump(dict(enabled=enabled),stream);stream.flush();os.fsync(stream.fileno())
        os.chmod(name,0o644);os.replace(name,SELECTOR)
    finally:
        if os.path.exists(name):os.unlink(name)

def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group();g.add_argument('--activate',action='store_true');g.add_argument('--disable',action='store_true');args=p.parse_args()
    if os.geteuid()!=0:raise ValueError('Interactive sudo required')
    os.umask(0o077)
    for path in (TARGET,POLICY,STATE,SELECTOR,CURRENT):require_root_ancestry(path)
    fd=os.open('/etc/yerbas-ai/phase-install.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        current=read_json(CURRENT,owner=0);verify_installed_files(current)
        policy=prepare(current,str(TARGET),str(STATE));account=pwd.getpwnam('yerbas-provider')
        if policy['provider_uid']!=account.pw_uid:raise ValueError('Wrong provider account')
        targets=routing_targets() if args.activate else []
        if STATE.exists():
            info=STATE.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid!=account.pw_uid or info.st_mode&0o077:raise ValueError('Unsafe candidate state')
        stage_files(TARGET,payload(PACKAGE))
        if not STATE.exists():STATE.mkdir(mode=0o700);os.chown(STATE,account.pw_uid,account.pw_gid)
        exclusive(POLICY,(json.dumps(policy,indent=2)+'\n').encode())
        if not os.path.lexists(SELECTOR):exclusive(SELECTOR,b'{"enabled": false}\n')
        verify_installed_files(policy)
        subprocess.run(['runuser','-u','yerbas-provider','--',policy['python'],'-I','-B','-c',
            'import runpy; runpy.run_path("/opt/yerbas-ai/provider-phase-cupti-v1/bootstrap.py")["checked"]()'],check=True,timeout=20)
        if args.disable:select(False)
        if args.activate:
            for target,raw in targets:exclusive(target,raw)
            subprocess.run(['systemctl','daemon-reload'],check=True,timeout=20)
            select(True)
        print(json.dumps(dict(installed=True,future_direct_jobs_enabled=read_json(SELECTOR,owner=0)['enabled'],
            existing_state_preserved=True,services_restarted=False,gpu_started=False,credentials_changed=False,policy=str(POLICY))))
if __name__=='__main__':main()
