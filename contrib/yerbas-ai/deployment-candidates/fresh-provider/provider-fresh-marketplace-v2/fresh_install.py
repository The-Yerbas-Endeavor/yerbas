"""Fresh-host disabled installation. Never enables or starts services."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import socket
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))

from host_preflight import check
from install_phases import phases, stage, digest
from guarded_writer import DIR_FLAGS
from install_journal import Journal
from reconcile_install import reconcile
from prepare_runtime import prepare, CPU_CHECK
from runtime_tree import audit

ROOT=Path(__file__).resolve().parent
OLD=ROOT.parent/'provider-fresh-host-candidate-v1'
STATE=Path('/var/lib/yerbas-ai-install-v2')


def orchestrate(operations, save):
    report=dict(passed=False,phase='preflight_complete',services_started=False,
                submissions_enabled=False,gpu_started=False,payments_sent=False,automatic_retry=False)
    save(report)
    try:
        for name in ('root','runtime','owner','units'):
            report['phase']=name+'_started';save(report)
            result=operations[name]()
            report[name]=result
            if result.get('passed') is not True:raise ValueError(name+' phase failed')
            report['phase']=name+'_complete';save(report)
        report.update(passed=True,phase='installed_disabled')
    except Exception as exc:
        report['error']=type(exc).__name__+': '+str(exc)
        report['inspection_required']=True
    save(report)
    return report


def install(owner_name,wheels,*,offline_services=False):
    if os.getuid()!=0:raise ValueError('Root required only for the explicit install operation')
    preflight=check(owner_name,wheels,offline_services=offline_services)
    owner=pwd.getpwnam(owner_name);provider=pwd.getpwnam('yerbas-provider')
    bundle=phases(owner.pw_uid,owner.pw_gid,provider.pw_uid,provider.pw_gid,owner.pw_dir,socket.gethostname())
    if bundle['phase_sha256']!=preflight['phase_sha256']:raise ValueError('Plan changed after preflight')
    os.umask(0o022)
    STATE.mkdir(mode=0o755)  # exclusive; retained attempts always refuse restart
    private=STATE/'private';private.mkdir(mode=0o700)
    def save(report):
        raw=(json.dumps(report,indent=2)+'\n').encode()
        temporary=STATE/'status.new'
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(temporary,STATE/'status.json')
        fd=os.open(STATE,DIR_FLAGS)
        try:os.fsync(fd)
        finally:os.close(fd)
    def root_phase():
        phase=bundle['phases']['root'];expected=digest(phase)
        j=Journal(private/'root.jsonl',expected);fd=os.open('/',DIR_FLAGS)
        try:stage(fd,phase,expected,j,0)
        finally:os.close(fd);j.close()
        result=reconcile('/',private/'root.jsonl',expected)
        return dict(passed=result['passed'],entries=len(result['checks']),plan_sha256=expected)
    def runtime_phase():
        target=Path('/opt/yerbas-ai/runtime-v1')
        result=prepare(str(target),wheels,_root_mode=True)
        if not result['passed']:return dict(passed=False,reason='Offline preparation failed; inspect retained runtime logs')
        before=audit(target/'venv',0)
        os.chown(target,0,provider.pw_gid);target.chmod(0o750)
        run=subprocess.run([str(target/'venv/bin/python'),'-I','-B','-c',CPU_CHECK],
            user=provider.pw_uid,group=provider.pw_gid,extra_groups=[],cwd='/',
            env={'PATH':'/usr/bin:/bin','HOME':'/nonexistent','CUDA_VISIBLE_DEVICES':'','PYTHONDONTWRITEBYTECODE':'1'},
            capture_output=True,text=True,timeout=60)
        if run.returncode:raise ValueError('Dedicated provider CPU runtime check failed')
        after=audit(target/'venv',0)
        if before['tree_sha256']!=after['tree_sha256']:raise ValueError('Runtime changed during provider check')
        return dict(passed=True,tree_sha256=after['tree_sha256'],cpu_check=json.loads(run.stdout),gpu_started=False)
    def owner_phase():
        # Snapshot public helper code into root-owned storage before dropping uid.
        tools=STATE/'owner-tools';tools.mkdir(mode=0o755)
        sources={n:OLD/n for n in ('guarded_writer.py','install_journal.py','reconcile_install.py')}
        sources.update({n:ROOT/n for n in ('install_phases.py','owner_install_phase.py')})
        pins={}
        for name,source in sources.items():
            if source.is_symlink():raise ValueError('Helper source symlink refused')
            raw=source.read_bytes();compile(raw,name,'exec')
            with (tools/name).open('xb') as f:f.write(raw)
            (tools/name).chmod(0o644);pins[name]=hashlib.sha256(raw).hexdigest()
        (tools/'MANIFEST.json').write_text(json.dumps(pins,sort_keys=True)+'\n')
        phase=bundle['phases']['owner'];expected=digest(phase)
        run=subprocess.run(['/usr/bin/python3','-I','-B',str(tools/'owner_install_phase.py'),
            '--home',owner.pw_dir,'--sha256',expected],input=json.dumps(phase),
            user=owner.pw_uid,group=owner.pw_gid,extra_groups=[],cwd='/',
            env={'PATH':'/usr/bin:/bin','HOME':owner.pw_dir},capture_output=True,text=True,timeout=120)
        if run.returncode:raise ValueError('Owner staging failed: '+run.stderr[-2000:])
        result=json.loads(run.stdout)
        if result.get('plan_sha256')!=expected or result.get('services_started') is not False:
            raise ValueError('Owner phase result differs')
        return result
    def units_phase():
        units=['/'+n for n in bundle['phases']['root']['files']
               if n.startswith('etc/systemd/system/') and n.endswith(('.service','.socket'))]
        run=subprocess.run(['/usr/bin/systemd-analyze','verify','--man=no','--generators=no',
            '--instance='+'0'*32,*units],env={'PATH':'/usr/bin:/bin','SYSTEMD_LOG_COLOR':'0'},
            capture_output=True,text=True,timeout=30)
        return dict(passed=run.returncode==0,exit_code=run.returncode,units=len(units),
                    diagnostics=(run.stdout+run.stderr)[-4000:],services_started=False)
    return orchestrate(dict(root=root_phase,runtime=runtime_phase,owner=owner_phase,units=units_phase),save)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--owner',required=True)
    p.add_argument('--wheels',type=Path,required=True);p.add_argument('--install-disabled',action='store_true')
    p.add_argument('--offline-services',action='store_true',help='Disabled image staging only; refused on running systemd hosts')
    a=p.parse_args()
    try:result=install(a.owner,a.wheels,offline_services=a.offline_services) if a.install_disabled else check(a.owner,a.wheels,offline_services=a.offline_services)
    except (ValueError,OSError,KeyError,subprocess.SubprocessError) as exc:
        print(json.dumps(dict(passed=False,error=str(exc),automatic_retry=False)));return 2
    print(json.dumps(result,indent=2));return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
