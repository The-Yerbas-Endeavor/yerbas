"""Unprivileged retained filesystem rehearsal; never installs into the host."""
import copy
import json
import os
from pathlib import Path
import tempfile
from install_phases import phases, digest, stage
from guarded_writer import DIR_FLAGS
from install_journal import Journal
from reconcile_install import reconcile

ROOT=Path(__file__).resolve().parent


def main():
    if os.getuid()==0:
        raise ValueError('Run this rehearsal as an unprivileged user')
    original=phases(1000,1000,1100,1100,'/home/newowner','new-provider')
    base=Path(tempfile.mkdtemp(prefix='installation-rehearsal-',dir=ROOT))
    results={}
    for name,source in original['phases'].items():
        phase=copy.deepcopy(source)
        for kind in ('files','directories'):
            for entry in phase[kind].values():
                entry.update(uid=os.getuid(),gid=os.getgid())
        root=base/name;root.mkdir(mode=0o700)
        # Provision only empty OS/home anchors inside this new sandbox.
        for target in (*phase['files'],*phase['directories']):
            for parent in reversed(Path(target).parents):
                if str(parent)=='.' or str(parent) in phase['directories']:continue
                if any(str(p) in phase['directories'] for p in parent.parents):continue
                (root/parent).mkdir(mode=0o700,parents=True,exist_ok=True)
        expected=digest(phase)
        journal=base/(name+'.jsonl')
        j=Journal(journal,expected);fd=os.open(root,DIR_FLAGS)
        try:stage(fd,phase,expected,j,os.getuid())
        finally:os.close(fd);j.close()
        result=reconcile(root,journal,expected)
        results[name]=dict(passed=result['passed'],reconciled_entries=len(result['checks']),
            original_plan_sha256=digest(source),rehearsal_plan_sha256=expected,
            journal=str(journal),filesystem=str(root))
    report=dict(passed=all(r['passed'] for r in results.values()),phases=results,
        scope='unprivileged filesystem rehearsal; ownership mapped to current user',
        root_ownership_tested=False,systemd_activation_tested=False,
        fresh_gpu_host_acceptance=False,installed_on_host=False,
        gpu_started=False,payment_sent=False,automatic_retry=False)
    (base/'ACCEPTANCE.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    print('Evidence: '+str(base/'ACCEPTANCE.json'))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
