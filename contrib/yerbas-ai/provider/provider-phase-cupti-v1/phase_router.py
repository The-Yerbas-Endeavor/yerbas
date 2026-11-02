"""Preserve the migrated routing chain; direct collection is explicit and versioned."""
import argparse
import os
from pathlib import Path
import sys
from provider_executor import read_json,verify_policy,validate_request,require_root_ancestry,require_service_boundary
POLICIES=('/etc/yerbas-ai/provider.json','/etc/yerbas-ai/provider-measured-v1.json','/etc/yerbas-ai/provider-future-v1.json','/etc/yerbas-ai/provider-direct-cupti-v1.json','/etc/yerbas-ai/provider-phase-cupti-v1.json')
SELECTOR='/etc/yerbas-ai/provider-phase-cupti-mode.json'
PREVIOUS='/opt/yerbas-ai/provider-direct-cupti-v1/bootstrap.py'

def choose(retained,enabled,replay):
    if len(retained)!=5 or any(type(v) is not bool for v in [*retained,enabled,replay]):raise ValueError('Explicit boolean routing required')
    if sum(retained)>1:raise ValueError('Ambiguous retained job; inspect before execution')
    if retained[-1]:return 'direct'
    if any(retained[:-1]):return 'previous'
    if replay:raise ValueError('Replay requires retained state')
    return 'direct' if enabled else 'previous'

def command(route,python,request,replay):
    if route=='previous':args=[python,'-I','-B',PREVIOUS,'--request',str(request)]
    elif route=='direct':args=[python,'-B',str(Path(__file__).with_name('provider_executor.py')),'--policy',POLICIES[-1],'--request',str(request)]
    else:raise ValueError('Unknown route')
    if replay:args.append('--replay-only')
    return args

def main():
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True);p.add_argument('--replay-only',action='store_true');a=p.parse_args()
    if os.getuid()==0:raise ValueError('Dedicated provider required')
    request=validate_request(read_json(a.request,owner=os.getuid()));require_service_boundary(request['run_id'],replay_only=a.replay_only)
    policies=[]
    for name in POLICIES:
        require_root_ancestry(name);policy=verify_policy(read_json(name,owner=0))
        if policy['provider_uid']!=os.getuid() or os.path.realpath(policy['python'])!=os.path.realpath(sys.executable):raise ValueError('Provider or interpreter differs')
        policies.append(policy)
    states=[Path(p['state']) for p in policies]
    if len(set(states))!=5 or any(a in b.parents for a in states for b in states if a!=b):raise ValueError('Separate job stores required')
    require_root_ancestry(SELECTOR);mode=read_json(SELECTOR,owner=0)
    if set(mode)!={'enabled'} or type(mode['enabled']) is not bool:raise ValueError('Explicit collector selection required')
    suffix=request['run_id']+'-'+request['contribution']
    route=choose([os.path.lexists(s/suffix) for s in states],mode['enabled'],a.replay_only)
    args=command(route,policies[-1]['python'],a.request,a.replay_only);os.execv(args[0],args)
if __name__=='__main__':main()
