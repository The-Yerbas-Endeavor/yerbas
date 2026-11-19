"""Read-only fresh-host checks. No install, service changes or downloads."""
import argparse
import grp
import json
import os
import platform
from pathlib import Path
import pwd
import shutil
import socket
import subprocess
import sys
from install_phases import phases, preflight as phase_preflight
from guarded_writer import DIR_FLAGS
from owner_agent_phase import open_home
from runtime_inventory import inspect as inspect_wheels
from verify import ROOT as OLD_ROOT, verify

PATTERNS = ['yerbas-provider-broker.*','yerbas-text-provider@*','yerbas-text-replay@*',
            'yerbas-wallet-agent.*','yerbas-ai-reward-request.*','yerbas-ai-availability.*']


def identity(owner, provider, owner_group, provider_group):
    values=(owner.pw_uid,owner.pw_gid,provider.pw_uid,provider.pw_gid)
    if any(type(v) is not int or v<=0 for v in values):
        raise ValueError('Non-root owner and provider accounts required')
    if owner.pw_uid==provider.pw_uid or owner.pw_gid==provider.pw_gid:
        raise ValueError('Separate owner/provider users and primary groups required')
    if owner_group.gr_gid!=owner.pw_gid or provider_group.gr_gid!=provider.pw_gid:
        raise ValueError('Primary group lookup differs')
    if owner.pw_name in provider_group.gr_mem or provider.pw_name in owner_group.gr_mem:
        raise ValueError('Owner/provider supplemental group separation required')
    if provider.pw_shell not in ('/usr/sbin/nologin','/sbin/nologin','/bin/false','/usr/bin/false'):
        raise ValueError('Dedicated provider must have a non-login shell')
    home=Path(owner.pw_dir)
    if not home.is_absolute() or str(home) in ('/','/root') or '..' in home.parts:
        raise ValueError('Explicit non-root owner home required')


def inventory_empty(verb, result):
    # systemd may return 1 for an empty list-unit-files inventory.
    empty=(verb=='list-unit-files' and result.returncode==1
           and not result.stdout.strip() and not result.stderr.strip())
    if (result.returncode and not empty) or result.stdout.strip() or result.stderr.strip():
        raise ValueError('Existing provider units or unavailable systemd; host preserved')


def runtime_profile():
    if sys.implementation.name!='cpython' or sys.version_info[:2]!=(3,14) or platform.machine()!='x86_64':
        raise ValueError('Pinned runtime requires CPython 3.14 on x86_64')
    if platform.system()!='Linux':
        raise ValueError('Linux provider required')


def service_inventory(offline=False):
    if offline:
        # Explicit image staging only. Never substitute this for a live-host check.
        if Path('/run/systemd/system').exists() or Path('/proc/1/comm').read_text().strip()=='systemd':
            raise ValueError('Offline service inventory refused on a running systemd host')
        commands=[('list-unit-files',['/usr/bin/systemctl','--root=/','list-unit-files'])]
    else:
        commands=[(verb,['/usr/bin/systemctl',verb]) for verb in ('list-unit-files','list-units')]
    for verb,args in commands:
        result=subprocess.run(args+['--all','--no-legend','--no-pager',*PATTERNS],
            env={'PATH':'/usr/bin:/bin','LC_ALL':'C'},capture_output=True,text=True,timeout=15)
        inventory_empty(verb,result)


def check(owner_name, wheels, *, offline_services=False):
    owner=pwd.getpwnam(owner_name);provider=pwd.getpwnam('yerbas-provider')
    identity(owner,provider,grp.getgrgid(owner.pw_gid),grp.getgrgid(provider.pw_gid))
    bundle=phases(owner.pw_uid,owner.pw_gid,provider.pw_uid,provider.pw_gid,
                  owner.pw_dir,socket.gethostname())
    # Occupancy first: never inspect or adopt an existing installation's secrets.
    for name in ('/opt/yerbas-ai','/etc/yerbas-ai','/var/lib/yerbas-ai-install-v1',
                 '/var/lib/yerbas-ai-install-v2',
                 str(Path(owner.pw_dir)/'.local/share/yerbas-ai-install-v2'),
                 str(Path(owner.pw_dir)/'.local/share/yerbas-ai-control-v1')):
        if os.path.lexists(name):raise ValueError('Existing installation preserved: '+name)
    root_fd=os.open('/',DIR_FLAGS)
    try:phase_preflight(root_fd,bundle['phases']['root'],bundle['phase_sha256']['root'],0)
    finally:os.close(root_fd)
    home_fd=open_home(owner.pw_dir,owner.pw_uid)
    try:phase_preflight(home_fd,bundle['phases']['owner'],bundle['phase_sha256']['owner'],owner.pw_uid)
    finally:os.close(home_fd)
    # Existing .local/share anchors must already be owner-controlled. Creating
    # them is a separate owner-phase prerequisite, not an implicit root action.
    runtime_profile()
    service_inventory(offline_services)
    for command in (('/usr/bin/systemd-analyze',) if offline_services else ('/usr/bin/systemd-analyze','/usr/bin/nvidia-smi')):
        if not os.access(command,os.X_OK):raise ValueError('Required host tool absent: '+command)
    # Staging copies the wheel cache and unpacks the environment; reserve ample
    # space here, then the runtime preparer rechecks before actual installation.
    free=shutil.disk_usage('/opt').free
    if free<20*1024**3:raise ValueError('At least 20 GiB free on /opt required for offline staging')
    verify(OLD_ROOT)
    manifest=json.loads((OLD_ROOT/'runtime/WHEELS.json').read_text())
    inventory=inspect_wheels(manifest,wheels)
    if not inventory['passed']:raise ValueError('Offline runtime wheels missing or changed')
    return dict(passed=True,scope='read-only fresh-host preflight; not acceptance', offline_services=offline_services,
        phase_sha256=bundle['phase_sha256'],wheels_verified=len(inventory['wheels']),
        mutations=False,services_started=False,gpu_started=False,installable=False,
        remaining=['GPU and credential enrollment',
                   'privileged service and fresh-GPU-host acceptance'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner',required=True)
    parser.add_argument('--wheels',type=Path,required=True)
    args=parser.parse_args()
    try:result=check(args.owner,args.wheels)
    except (ValueError,OSError,KeyError,subprocess.SubprocessError) as exc:
        print(json.dumps(dict(passed=False,reason=str(exc),mutations=False,
                              services_started=False,gpu_started=False)))
        return 2
    print(json.dumps(result,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
