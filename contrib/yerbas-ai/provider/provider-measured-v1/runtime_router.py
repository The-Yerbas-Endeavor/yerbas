"""Route retained jobs to their original policy; never execute training for replay."""
import argparse
import os
from pathlib import Path
from provider_executor import read_json,require_root_ancestry,validate_request,verify_policy

LEGACY='/etc/yerbas-ai/provider.json'
MEASURED='/etc/yerbas-ai/provider-measured-v1.json'
MODE='/etc/yerbas-ai/provider-runtime-mode.json'
LEGACY_EXECUTOR='/opt/yerbas-ai/provider-v1/code/provider_executor.py'
MEASURED_EXECUTOR='/opt/yerbas-ai/provider-measured-v1/provider_executor.py'


def choose(legacy_exists,measured_exists,default,replay):
    if default not in ('legacy','measured'):raise ValueError('Unknown default runtime')
    if legacy_exists and measured_exists:raise ValueError('Ambiguous retained job; operator inspection required')
    if legacy_exists:return 'legacy'
    if measured_exists:return 'measured'
    if replay:raise ValueError('Replay requires retained state')
    return default


def main():
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True);p.add_argument('--replay-only',action='store_true');a=p.parse_args()
    if os.getuid()==0:raise ValueError('Dedicated provider account required')
    request=validate_request(read_json(a.request,owner=os.getuid()))
    policies={}
    for name,path in (('legacy',LEGACY),('measured',MEASURED)):
        require_root_ancestry(path);policies[name]=verify_policy(read_json(path,owner=0))
        if policies[name]['provider_uid']!=os.getuid():raise ValueError('Provider account differs')
    require_root_ancestry(MODE);mode=read_json(MODE,owner=0)
    if set(mode)!={'default'}:raise ValueError('Invalid runtime selector')
    suffix=request['run_id']+'-'+request['contribution']
    selected=choose(*(os.path.lexists(Path(policies[n]['state'])/suffix) for n in ('legacy','measured')),mode['default'],a.replay_only)
    policy=policies[selected];executor=LEGACY_EXECUTOR if selected=='legacy' else MEASURED_EXECUTOR
    command=[policy['python'],'-B',executor,'--policy',LEGACY if selected=='legacy' else MEASURED,'--request',str(a.request)]
    if a.replay_only:command.append('--replay-only')
    os.execv(command[0],command)
if __name__=='__main__':main()
