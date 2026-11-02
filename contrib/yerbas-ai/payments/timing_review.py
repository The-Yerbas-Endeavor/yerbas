"""Display supplied diagnostic evidence without granting reward authority."""
import hashlib,json,math,re
from pathlib import Path

def load_review(path):
 with Path(path).open('rb') as f:raw=f.read(32769)
 if len(raw)>32768:raise ValueError('Timing review exceeds size bound')
 def unique(pairs):
  d={}
  for k,v in pairs:
   if k in d:raise ValueError('Duplicate timing review key')
   d[k]=v
  return d
 value=json.loads(raw,object_pairs_hook=unique)
 if not isinstance(value,dict) or value.get('schema')!=1 or value.get('kind')!='operator-reward-time-evidence-review-not-an-approval':raise ValueError('Diagnostic review required')
 if not re.fullmatch('[a-f0-9]{32}',value.get('receipt','')) or not re.fullmatch('[a-f0-9]{64}',value.get('checkpoint_sha256','')):raise ValueError('Receipt and artifact binding required')
 if value.get('approved_gpu_ms') is not None or any(value.get(k) is not False for k in ('approval_created','unsigned_draft_created','payments_authorized')):raise ValueError('Diagnostic review cannot grant authority')
 return dict(body=value,sha256=hashlib.sha256(raw).hexdigest())

def describe(review,receipt,record):
 if review is None:return None
 value=review['body']
 if value['receipt']!=receipt or not record or value['producer']!=record['provider'] or value['checkpoint_sha256']!=record['artifact_sha256']:raise ValueError('Timing review differs from live receipt')
 m=value['measurement']
 if m.get('approved_gpu_ms') is not None or m.get('reward_eligible') is not False or m.get('capture_completeness_verified') is not False:raise ValueError('Expected unapproved diagnostic measurement')
 values=[m['observed_training_kernel_union_us'],m['observed_nontraining_kernel_union_us']]
 if any(type(x) not in (int,float) or not math.isfinite(x) or x<0 for x in values):raise ValueError('Invalid diagnostic duration')
 audit=value.get('retained_trace_audit',{})
 return dict(scope='supplied diagnostic evidence bound to the live receipt; not reward authority',review_sha256=review['sha256'],observed_training_kernel_union_us=values[0],observed_nontraining_kernel_union_us=values[1],retained_trace_audit_reported_passed=audit.get('passed') is True,capture_completeness_verified=False,profiler_overhead_calibrated=False,approved_gpu_ms=None,may_convert_to_reward=False,remaining_checks=['capture completeness','profiler overhead calibration','explicit operator GPU-time approval'])
