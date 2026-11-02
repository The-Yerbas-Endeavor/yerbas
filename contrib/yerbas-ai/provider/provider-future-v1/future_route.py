"""Choose future policy only for runs absent from every retained state store."""
from pathlib import Path

def choose(legacy_exists,measured_exists,future_exists,enabled,replay):
 if any(type(x) is not bool for x in (legacy_exists,measured_exists,future_exists,enabled,replay)):raise ValueError('Boolean state checks required')
 if sum((legacy_exists,measured_exists,future_exists))>1:raise ValueError('Ambiguous retained job; inspect before execution')
 if legacy_exists or measured_exists:return 'original'
 if future_exists:return 'future'
 if replay:raise ValueError('Replay requires retained state')
 return 'future' if enabled else 'original'

def transition(old,new,expected_state,expected_worker,expected_credentials,new_ca,new_ca_sha):
 """Validate an operator-created new policy; never edit the original policy."""
 import copy
 if old.get('schema')!=2 or new.get('schema')!=2:raise ValueError('Measured policy required')
 if len({old['state'],expected_state})!=2 or len({old['worker'],expected_worker})!=2 or old['credentials']==expected_credentials:raise ValueError('Separate future state, code and enrollment required')
 for p in (expected_state,expected_worker,expected_credentials,new_ca):
  if not isinstance(p,str) or not Path(p).is_absolute() or '..' in Path(p).parts:raise ValueError('Fixed absolute paths required')
 # Hardware, locks, interpreter, dataset, measurement mode and approved recipe
 # are immutable. Only separate deployment locations and source pins may differ.
 changed={'worker','credentials','state','files'}
 if set(old)!=set(new) or any(old[k]!=new[k] for k in old if k not in changed):raise ValueError('Unrelated runtime policy changed')
 if new['state']!=expected_state or new['worker']!=expected_worker or new['credentials']!=expected_credentials or new['files'].get(new_ca)!=new_ca_sha:raise ValueError('Future locations or CA differ')
 return new
