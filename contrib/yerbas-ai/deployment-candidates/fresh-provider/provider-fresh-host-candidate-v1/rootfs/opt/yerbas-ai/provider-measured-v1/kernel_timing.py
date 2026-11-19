"""Diagnostic union of traced CUDA kernel intervals, never a reward approval."""
import hashlib,json,math
from pathlib import Path
MAX_BYTES=128*1024*1024

def number(value):
 if type(value) not in (int,float) or not math.isfinite(value) or value<0:raise ValueError('Finite nonnegative trace time required')
 return value

def analyze(trace,device=0):
 if type(device) is not int or device<0:raise ValueError('Explicit logical device required')
 if not isinstance(trace,dict) or not isinstance(trace.get('traceEvents'),list) or len(trace['traceEvents'])>1000000:raise ValueError('Bounded Chrome trace required')
 intervals=[]
 for event in trace['traceEvents']:
  if not isinstance(event,dict):raise ValueError('Invalid trace event')
  if event.get('cat')!='kernel':continue
  if event.get('ph')!='X':raise ValueError('Complete kernel interval required')
  args=event.get('args')
  if not isinstance(args,dict) or type(args.get('device')) is not int:raise ValueError('Kernel device attribution missing')
  if args['device']!=device:raise ValueError('Unexpected GPU in trace')
  start=number(event.get('ts'));duration=number(event.get('dur'));end=number(start+duration)
  if duration>0:intervals.append((start,end))
 if not intervals:raise ValueError('No measurable CUDA kernels; timing unavailable')
 intervals.sort();start,end=intervals[0];union=0
 for left,right in intervals[1:]:
  if left>end:union+=end-start;start,end=left,right
  else:end=max(end,right)
 union+=end-start
 return dict(schema=1,logical_device=device,kernel_events=len(intervals),observed_kernel_union_us=union,observed_kernel_sum_us=sum(b-a for a,b in intervals),observed_kernel_span_us=max(b for a,b in intervals)-intervals[0][0],measurement_scope='union of observed CUDA kernel intervals across streams; excludes CPU, transfers and gaps',capture_completeness_verified=False,gpu_active_ms=None,approved_gpu_ms=None,reward_eligible=False)

def read_trace(path,device=0):
 with Path(path).open('rb') as f:raw=f.read(MAX_BYTES+1)
 if len(raw)>MAX_BYTES:raise ValueError('Trace exceeds diagnostic size limit')
 def reject(value):raise ValueError('Non-finite JSON number')
 result=analyze(json.loads(raw,parse_constant=reject),device)
 result['trace_sha256']=hashlib.sha256(raw).hexdigest();return result
