"""Strict per-step attribution of observed kernels, not capture completeness."""
import re
from kernel_timing import analyze,number
PREFIX='yerbas_training_step:'
def attribute(trace):
 total=analyze(trace);markers=[];seen=set();kernels=[]
 for event in trace['traceEvents']:
  if event.get('cat')=='kernel':kernels.append(event)
  name=event.get('name','')
  if not isinstance(name,str) or not name.startswith(PREFIX):continue
  if event.get('cat')=='gpu_user_annotation':continue
  suffix=name[len(PREFIX):]
  if not re.fullmatch('0|[1-9][0-9]*',suffix) or event.get('cat')!='user_annotation' or event.get('ph')!='X':raise ValueError('Invalid training marker')
  step=int(suffix)
  if not 0<=step<6000 or step in seen:raise ValueError('Duplicate or invalid training step')
  start=number(event.get('ts'));duration=number(event.get('dur'))
  if duration<=0:raise ValueError('Empty training marker')
  seen.add(step);markers.append((start,number(start+duration),step))
 markers.sort()
 if any(a[1]>b[0] or a[2]>=b[2] for a,b in zip(markers,markers[1:])):raise ValueError('Overlapping or unordered training markers')
 training=[];outside=[];counts={step:0 for _,_,step in markers}
 for event in kernels:
  start=event['ts'];end=start+event['dur'];matched=[step for a,b,step in markers if a<=start and end<=b]
  if matched:training.append(event);counts[matched[0]]+=event['dur']>0
  elif any(start<b and end>a for a,b,_ in markers):raise ValueError('Kernel crosses training boundary')
  else:outside.append(event)
 if any(n==0 for n in counts.values()):raise ValueError('Training step has no observed kernels')
 def union(events):return analyze(dict(traceEvents=events))['observed_kernel_union_us'] if any(e['dur']>0 for e in events) else 0
 return dict(training_steps=[s for _,_,s in markers],observed_training_kernel_union_us=union(training),observed_nontraining_kernel_union_us=union(outside),observed_total_kernel_union_us=total['observed_kernel_union_us'],capture_completeness_verified=False,approved_gpu_ms=None,reward_eligible=False)

def aggregate(windows,start,end):
 if type(start) is not int or type(end) is not int or not 0<=start<end<=6000:raise ValueError('Invalid step range')
 steps=[s for w in windows for s in w['training_steps']]
 if steps!=list(range(start,end)):raise ValueError('Missing, repeated or out-of-order training step coverage')
 return dict(start_step=start,end_step=end,training_steps_covered=len(steps),observed_training_kernel_union_us=sum(w['observed_training_kernel_union_us'] for w in windows),observed_nontraining_kernel_union_us=sum(w['observed_nontraining_kernel_union_us'] for w in windows),capture_completeness_verified=False,approved_gpu_ms=None,reward_eligible=False,scope='observed kernels inside synchronized per-step ranges; complete marker coverage does not prove complete kernel capture')
