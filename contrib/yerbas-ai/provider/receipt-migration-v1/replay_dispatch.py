"""Preserve the installed router unless this exact run has root approval."""
import argparse,hashlib,os,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from protected_replay import CONFIG,read,trusted,validate_selection
ROUTER=Path('/opt/yerbas-ai/provider-measured-v1/runtime_router.py')
ROUTER_SHA='ecfc64f12e1fda188ca8c1db7ce788a3ac1549a4b09b2425eca7b8ebb48915c5'
PYTHON='/opt/yerbas-ai/runtime-v1/venv/bin/python'
def command(run_id,config):
 if not isinstance(run_id,str) or not re.fullmatch('[a-f0-9]{32}',run_id):raise ValueError('Invalid run ID')
 if config is not None:
  if not isinstance(config.get('jobs'),dict):raise ValueError('Malformed migration routing')
  # Validate the full schema even when the run is not approved. Malformed
  # installed approval must fail closed, never silently select the old server.
  if set(config)!={'schema','runtime_dir','runtime_files','bridge_sha256','jobs'} or type(config['schema']) is not int or config['schema']!=1:raise ValueError('Malformed migration routing')
  if run_id in config['jobs']:
   validate_selection(config,run_id)
   return [PYTHON,'-I','-B',str(Path(__file__).with_name('protected_replay.py')),'--run-id',run_id]
 return [PYTHON,'-B',str(ROUTER),'--replay-only','--request','/var/lib/yerbas-ai-provider/requests/'+run_id+'.json']
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-id',required=True);a=p.parse_args()
 if os.getuid()==0:raise ValueError('Dedicated provider required')
 if hashlib.sha256(trusted(ROUTER)).hexdigest()!=ROUTER_SHA:raise ValueError('Original router changed; review required')
 config=read(CONFIG) if os.path.lexists(CONFIG) else None
 cmd=command(a.run_id,config);os.execv(cmd[0],cmd)
if __name__=='__main__':main()
