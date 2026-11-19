"""Validate checkpoint-segment training attribution without approving time."""
import math,re

def combine(segments):
 if not segments:raise ValueError('Training attribution segments required')
 first=segments[0]['start']['start_step'];step=first;training=other=0.;identity=None
 for segment in segments:
  start=segment['start'];m=segment['measurement'];a=m.get('training_attribution')
  if not isinstance(a,dict):raise ValueError('Training attribution missing from segment')
  end=start['manifest']['end_step']
  if start['start_step']!=step or a.get('start_step')!=step or a.get('end_step')!=end or a.get('training_steps_covered')!=end-step:raise ValueError('Training attribution coverage differs')
  if a.get('capture_completeness_verified') is not False or a.get('approved_gpu_ms') is not None or a.get('reward_eligible') is not False:raise ValueError('Unexpected attribution approval')
  hashes=tuple(m.get(k) for k in ('instrumentation_sha256','analyzer_sha256'))
  if any(not isinstance(h,str) or not re.fullmatch('[a-f0-9]{64}',h) for h in hashes):raise ValueError('Attribution implementation identity missing')
  if identity is not None and identity!=hashes:raise ValueError('Attribution implementation changed between segments')
  identity=hashes;values=[a.get('observed_training_kernel_union_us'),a.get('observed_nontraining_kernel_union_us'),m.get('observed_kernel_union_us')]
  if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in values) or values[0]<=0:raise ValueError('Invalid attributed timing')
  if not math.isclose(values[0]+values[1],values[2],rel_tol=1e-12,abs_tol=1e-6):raise ValueError('Attributed timing does not reconcile')
  training+=values[0];other+=values[1];step=end
 return dict(start_step=first,end_step=step,training_steps_covered=step-first,execution_segments=len(segments),observed_training_kernel_union_us=training,observed_nontraining_kernel_union_us=other,instrumentation_sha256=identity[0],analyzer_sha256=identity[1],capture_completeness_verified=False,approved_gpu_ms=None,reward_eligible=False,scope='sum of observed per-step kernel unions in checkpoint-linked processes; excludes observed nontraining kernels; not calibrated reward time')
