"""Exact-owner phase invoked from an immutable root-staged helper directory."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from install_phases import stage, preflight, digest
from guarded_writer import DIR_FLAGS, trusted, parts
from install_journal import Journal
from reconcile_install import reconcile


def open_home(home):
    path=Path(home)
    if not path.is_absolute() or '..' in path.parts or str(path) in ('/','/root'):
        raise ValueError('Owner home required')
    fd=os.open('/',DIR_FLAGS)
    try:
        trusted(fd,0)
        for index,part in enumerate(path.parts[1:]):
            child=os.open(part,DIR_FLAGS,dir_fd=fd)
            try:trusted(child,os.getuid() if index==len(path.parts)-2 else 0)
            except BaseException:os.close(child);raise
            os.close(fd);fd=child
        return fd
    except BaseException:os.close(fd);raise


def main():
    p=argparse.ArgumentParser();p.add_argument('--home',required=True);p.add_argument('--sha256',required=True)
    a=p.parse_args()
    if os.getuid()==0:raise ValueError('Non-root owner phase required')
    raw=sys.stdin.buffer.read(2*1024*1024+1)
    if len(raw)>2*1024*1024:raise ValueError('Oversized owner plan')
    phase=json.loads(raw)
    if digest(phase)!=a.sha256:raise ValueError('Owner plan binding differs')
    for kind in ('files','directories'):
        for name,entry in phase[kind].items():
            parts(name)
            if not (name=='.local/share/yerbas-ai-control-v1' or name.startswith('.local/share/yerbas-ai-control-v1/')):
                raise ValueError('Owner target outside fixed application directory')
            if entry['uid']!=os.getuid() or entry['gid']!=os.getgid():raise ValueError('Exact owner identity required')
    home_fd=open_home(a.home)
    try:
        preflight(home_fd,phase,a.sha256,os.getuid())
        share=os.open('.local/share',DIR_FLAGS,dir_fd=home_fd)
        try:
            trusted(share,os.getuid())
            os.mkdir('yerbas-ai-install-v2',0o700,dir_fd=share)
        finally:os.close(share)
        journal=Path(a.home)/'.local/share/yerbas-ai-install-v2/owner.jsonl'
        j=Journal(journal,a.sha256)
        try:stage(home_fd,phase,a.sha256,j,os.getuid())
        finally:j.close()
        result=reconcile(a.home,journal,a.sha256)
        if not result['passed']:raise ValueError('Owner reconciliation failed')
        print(json.dumps(dict(passed=True,entries=len(result['checks']),plan_sha256=a.sha256,services_started=False)))
    finally:os.close(home_fd)


if __name__=='__main__':main()
