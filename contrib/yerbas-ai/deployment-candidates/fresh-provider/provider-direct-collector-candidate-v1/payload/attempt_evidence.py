"""Bind observed CUDA timing to an execution attempt and acknowledged receipt.
Binding is diagnostic provenance, not hardware attestation or time approval.
"""
import hashlib,json,re,math

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def bind(start,measurement,report,receipt):
 if start.get('schema')!=1 or not re.fullmatch('[a-f0-9]{32}',start.get('attempt_id','')):raise ValueError('Invalid attempt')
 m=start['manifest']
 if start['physical_gpu'] not in ('0','1') or type(start['start_step']) is not int or not m['start_step']<=start['start_step']<m['end_step']:raise ValueError('Attempt GPU or step differs')
 value=measurement['observed_kernel_union_us']
 if type(value) not in (int,float) or not math.isfinite(value) or value<=0:raise ValueError('Invalid observed timing')
 if not re.fullmatch('[a-f0-9]{64}',measurement['trace_sha256']):raise ValueError('Invalid trace hash')
 if measurement['attempt_sha256']!=digest(start):raise ValueError('Measurement attempt differs')
 if measurement['recipe_identity']!=m['identity'] or report['identity']!=m['identity']:raise ValueError('Recipe differs')
 if report['resumed_from_step']!=start['start_step'] or report['step']!=m['end_step'] or report['device']!='cuda' or report['owner_stopped'] is not False:raise ValueError('Assigned segment incomplete')
 if set(receipt)!={'receipt','sha256','contribution'} or not re.fullmatch('[a-f0-9]{32}',receipt['receipt']):raise ValueError('Invalid receipt')
 if receipt['contribution']!=m['contribution'] or receipt['sha256']!=report['checkpoint_sha256'] or measurement['checkpoint_sha256']!=receipt['sha256']:raise ValueError('Receipt artifact differs')
 if measurement['capture_completeness_verified'] is not False or measurement['approved_gpu_ms'] is not None or measurement['reward_eligible'] is not False:raise ValueError('Unexpected approval claim')
 result=dict(schema=1,kind='contribution-attempt-kernel-evidence',attempt_id=start['attempt_id'],attempt_sha256=digest(start),measurement_sha256=digest(measurement),manifest_sha256=digest(m),provider=m['provider'],contribution=m['contribution'],receipt=receipt['receipt'],checkpoint_sha256=receipt['sha256'],physical_gpu=start['physical_gpu'],start_step=start['start_step'],end_step=report['step'],trace_sha256=measurement['trace_sha256'],observed_kernel_union_us=measurement['observed_kernel_union_us'],approved_gpu_ms=None,reward_eligible=False,blockers=['capture_completeness_unverified','includes_evaluation_and_generation','profiler_overhead_uncalibrated','no_operator_gpu_time_approval'],trust='provider-local evidence; hashes do not prove honest computation or measurement')
 if 'training_attribution' in measurement:
  a=measurement['training_attribution']
  if a.get('start_step')!=start['start_step'] or a.get('end_step')!=report['step'] or a.get('capture_completeness_verified') is not False or a.get('reward_eligible') is not False or a.get('approved_gpu_ms') is not None:raise ValueError('Attribution receipt binding differs')
  result['training_attribution']=a
 result['evidence_sha256']=digest(result);return result
