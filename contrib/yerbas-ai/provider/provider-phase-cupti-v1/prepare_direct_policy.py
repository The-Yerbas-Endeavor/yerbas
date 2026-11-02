"""Prepare a policy for review only; does not install files or start a job."""
import argparse
import json
from pathlib import Path
from provider_executor import verify_policy
from direct_policy import PINS


def prepare(current, code, state):
    verify_policy(current)
    code, state = Path(code), Path(state)
    if not code.is_absolute() or not state.is_absolute() or '..' in code.parts or '..' in state.parts:
        raise ValueError('Absolute normalized candidate paths required')
    old_code,old_state=Path(current['worker']).parent,Path(current['state'])
    if any(a==b or a in b.parents or b in a.parents for a,b in ((code,old_code),(state,old_state))):
        raise ValueError('Separate code and state required; preserve existing recovery bindings')
    if code == state or code in state.parents or state in code.parents:
        raise ValueError('Code and writable state must be separate')
    result=dict(current,schema=3,measurement='direct-cupti-v1',worker=str(code/'text_gpu.py'),state=str(state))
    # Keep corpus and public CA pins, replacing only worker-directory pins.
    old_code=Path(current['worker']).parent
    result['files']={p:h for p,h in current['files'].items() if Path(p).parent!=old_code}
    result['files'].update({str(code/n):h for n,h in PINS.items()})
    return verify_policy(result)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--current-policy',type=Path,required=True)
    p.add_argument('--candidate-code',required=True)
    p.add_argument('--candidate-state',required=True)
    a=p.parse_args()
    print(json.dumps(prepare(json.loads(a.current_policy.read_text()),a.candidate_code,a.candidate_state),indent=2))
