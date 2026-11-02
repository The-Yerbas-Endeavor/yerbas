"""Explicit testnet draft policy, never authority to approve time or spend."""
import hashlib,json
from pathlib import Path
from identity import PROFILE,GENESIS
from payment_draft import rate_units
FIELDS={'schema','kind','profile','genesis','rate_yerb_per_approved_gpu_hour','time_basis','approval_scope','signing_authorized','broadcast_authorized','provisional'}
def load_policy(path):
 with Path(path).open('rb') as f:raw=f.read(8193)
 if len(raw)>8192:raise ValueError('Bounded policy file required')
 def unique(pairs):
  value={}
  for k,v in pairs:
   if k in value:raise ValueError('Duplicate policy key')
   value[k]=v
  return value
 p=json.loads(raw,object_pairs_hook=unique)
 if not isinstance(p,dict) or set(p)!=FIELDS or type(p['schema']) is not int or p['schema']!=1 or p['kind']!='testnet-unsigned-reward-draft-policy' or p['profile']!=PROFILE or p['genesis']!=GENESIS:raise ValueError('Private testnet draft policy required')
 if p['time_basis']!='operator-approved GPU-active milliseconds' or p['approval_scope']!='rate only; no contribution time approved' or p['signing_authorized'] is not False or p['broadcast_authorized'] is not False or p['provisional'] is not True:raise ValueError('Policy cannot approve work or spending')
 rate_units(p['rate_yerb_per_approved_gpu_hour'])
 return dict(policy=p,policy_sha256=hashlib.sha256(json.dumps(p,sort_keys=True,separators=(',',':')).encode()).hexdigest())
