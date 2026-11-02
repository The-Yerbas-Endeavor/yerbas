"""Route retained jobs first; switch only new jobs using the root-owned selector."""
import argparse,os,sys
from pathlib import Path
from provider_executor import read_json,verify_policy,validate_request,require_root_ancestry,require_service_boundary
from future_route import choose
POLICIES={'legacy':'/etc/yerbas-ai/provider.json','measured':'/etc/yerbas-ai/provider-measured-v1.json','future':'/etc/yerbas-ai/provider-future-v1.json'}
SELECTOR='/etc/yerbas-ai/provider-future-mode.json'
ORIGINAL='/opt/yerbas-ai/provider-measured-v1/runtime_router.py'
REPLAY='/opt/yerbas-ai/receipt-migration-v1/replay_dispatch.py'
def command(selected,policy,request_path,request,replay):
 if selected=='original':
  if replay:return [policy['python'],'-I','-B',REPLAY,'--run-id',request['run_id']]
  return [policy['python'],'-B',ORIGINAL,'--request',str(request_path)]
 if selected!='future':raise ValueError('Unknown route')
 result=[policy['python'],'-B',str(Path(__file__).with_name('provider_executor.py')),'--policy',POLICIES['future'],'--request',str(request_path)]
 if replay:result.append('--replay-only')
 return result

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--request',type=Path,required=True);p.add_argument('--replay-only',action='store_true');a=p.parse_args()
 if os.getuid()==0:raise ValueError('Dedicated provider account required')
 request=validate_request(read_json(a.request,owner=os.getuid()));require_service_boundary(request['run_id'],replay_only=a.replay_only)
 policies={}
 for name,path in POLICIES.items():
  require_root_ancestry(path);policies[name]=verify_policy(read_json(path,owner=0))
  if policies[name]['provider_uid']!=os.getuid() or os.path.realpath(sys.executable)!=os.path.realpath(policies[name]['python']):raise ValueError('Runtime owner or interpreter differs')
 states=[Path(p['state']) for p in policies.values()]
 if len(set(states))!=3 or any(a in b.parents for a in states for b in states if a!=b):raise ValueError('Separate nonnested job stores required')
 require_root_ancestry(SELECTOR);mode=read_json(SELECTOR,owner=0)
 if set(mode)!={'enabled'} or type(mode['enabled']) is not bool:raise ValueError('Explicit future-job selection required')
 suffix=request['run_id']+'-'+request['contribution']
 selected=choose(*(os.path.lexists(path/suffix) for path in states),mode['enabled'],a.replay_only)
 cmd=command(selected,policies['future' if selected=='future' else 'measured'],a.request,request,a.replay_only)
 os.execv(cmd[0],cmd)
if __name__=='__main__':main()
