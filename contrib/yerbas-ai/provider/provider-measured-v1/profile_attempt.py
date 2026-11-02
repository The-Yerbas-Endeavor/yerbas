"""Profile one contribution in sequential, separately exited CUDA processes.
All descendants remain in the original supervisor's process group/cgroup.
"""
import argparse,hashlib,json,math,signal,subprocess,sys,threading,time
from pathlib import Path
from attempt_evidence import digest
from sustained_training import atomic_json
SEGMENT_STEPS=1000
MAX_TRACE_BYTES=1024*1024*1024

def file_sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def aggregate(start,segments,*,require_complete=True,training_only=False):
 if not segments:raise ValueError('No complete segments')
 step=start['start_step'];parent=start.get('initial_checkpoint_sha256');total_bytes=0;total_us=0
 for index,item in enumerate(segments):
  child=item['start'];report=item['report'];measurement=item['measurement']
  end=min(start['manifest']['end_step'],step+SEGMENT_STEPS)
  expected=dict(start,manifest=dict(start['manifest'],end_step=end),start_step=step,parent_attempt_sha256=digest(start),segment_index=index,parent_checkpoint_sha256=parent)
  if child!=expected:raise ValueError('Segment assignment or checkpoint chain differs')
  if report['identity']!=start['manifest']['identity'] or report['resumed_from_step']!=step or report['step']!=end or report['device']!='cuda' or report['owner_stopped'] is not False:raise ValueError('Segment execution incomplete')
  if measurement['attempt_sha256']!=digest(child) or measurement['recipe_identity']!=report['identity'] or measurement['checkpoint_sha256']!=report['checkpoint_sha256']:raise ValueError('Segment measurement binding differs')
  if measurement['reward_eligible'] is not False or measurement['approved_gpu_ms'] is not None or measurement['capture_completeness_verified'] is not False:raise ValueError('Unexpected segment approval claim')
  value=measurement['observed_kernel_union_us'];size=measurement['trace_bytes']
  if type(value) not in (int,float) or not math.isfinite(value) or value<=0 or type(size) is not int or size<0:raise ValueError('Invalid segment timing/size')
  total_us+=value;total_bytes+=size
  if total_bytes>MAX_TRACE_BYTES:raise ValueError('Attempt trace budget exceeded')
  parent=report['checkpoint_sha256'];step=end
 if require_complete and step!=start['manifest']['end_step']:raise ValueError('Attempt incomplete')
 report=dict(segments[-1]['report'],resumed_from_step=start['start_step'],initial_bits_per_byte=segments[0]['report']['initial_bits_per_byte'],elapsed_training_seconds=sum(x['report']['elapsed_training_seconds'] for x in segments),execution_scope='aggregate of sequential checkpoint-linked processes; per-process reports retained',execution_segments=len(segments))
 measurement=dict(schema=1,attempt_sha256=digest(start),recipe_identity=report['identity'],checkpoint_sha256=parent,observed_kernel_union_us=total_us,trace_bytes=total_bytes,trace_windows=sum(x['measurement']['trace_windows'] for x in segments),execution_segments=len(segments),capture_completeness_verified=False,approved_gpu_ms=None,gpu_active_ms=None,reward_eligible=False,profiler_overhead_present=True,scope='observed kernels across sequential processes; includes repeated evaluation/generation and initialization',trace_kind='hashed-index-of-checkpoint-linked-processes')
 if training_only:
  from segment_attribution import combine
  measurement["training_attribution"]=combine(segments)
 return report,measurement

def run_segments(dataset,state,attempt,steps,seconds,*,launch=None,clock=time.monotonic,stop=None,training_only=False):
 start=json.loads((attempt/'start.json').read_text())
 if steps!=start['manifest']['end_step']-start['start_step'] or not 0<steps<=6000 or not 1<=seconds<=120:raise ValueError('Attempt budget differs')
 stop=stop or threading.Event();deadline=clock()+seconds;segments=[];step=start['start_step'];parent=start.get('initial_checkpoint_sha256')
 while step<start['manifest']['end_step']:
  if stop.is_set():raise RuntimeError('Owner stopped profiled attempt')
  remaining=math.floor(deadline-clock())
  if remaining<1:raise RuntimeError('Profiled attempt deadline reached')
  checkpoint=state/'checkpoint.json'
  actual=file_sha(checkpoint) if checkpoint.exists() else None
  if actual!=parent:raise ValueError('Retained checkpoint changed between processes')
  # Initial resume parent is recorded separately; it is already verified by
  # the schema-4 worker against its assignment before invoking this executor.
  child=dict(start,manifest=dict(start['manifest'],end_step=min(step+SEGMENT_STEPS,start['manifest']['end_step'])),start_step=step,parent_attempt_sha256=digest(start),segment_index=len(segments),parent_checkpoint_sha256=parent)
  directory=attempt/('segment-%02d'%len(segments));directory.mkdir(mode=0o700);atomic_json(directory/'start.json',child)
  command=[sys.executable,str(Path(__file__).with_name('profile_training.py' if training_only else 'profile_contribution.py')),'--dataset',str(dataset),'--state',str(state),'--attempt',str(directory),'--steps',str(child['manifest']['end_step']-step),'--max-seconds',str(remaining)]
  if launch is None:
   process=subprocess.Popen(command)
   try:
    while process.poll() is None:
     if stop.is_set() or clock()>=deadline:raise RuntimeError('Profiled attempt stopped or timed out')
     stop.wait(.1)
    code=process.returncode
   finally:
    if process.poll() is None:
     process.terminate()
     try:process.wait(timeout=10)
     except subprocess.TimeoutExpired:process.kill();process.wait()
    atomic_json(directory/'process-result.json',dict(exit_code=process.returncode,signal=-process.returncode if process.returncode is not None and process.returncode<0 else None))
  else:code=launch(command,directory,child)
  if code:raise RuntimeError('Profile segment exited with code '+str(code))
  if stop.is_set():raise RuntimeError('Owner stopped profiled attempt')
  if clock()>=deadline:raise RuntimeError('Profiled attempt timed out after segment')
  report=json.loads((directory/'report.json').read_text());measurement=json.loads((directory/'measurement.json').read_text())
  if file_sha(checkpoint)!=report['checkpoint_sha256']:raise ValueError('Segment checkpoint differs from report')
  item=dict(start=child,report=report,measurement=measurement);segments.append(item)
  aggregate(start,segments,require_complete=False,training_only=training_only)
  parent=report['checkpoint_sha256'];step=report['step']
 if stop.is_set():raise RuntimeError('Owner stopped profiled attempt')
 if clock()>=deadline:raise RuntimeError('Profiled attempt deadline reached before aggregation')
 report,measurement=aggregate(start,segments,training_only=training_only)
 index=attempt/'segment-index.json';atomic_json(index,dict(schema=1,segments=segments));measurement['trace_sha256']=file_sha(index)
 atomic_json(attempt/'report.json',report);atomic_json(attempt/'measurement.json',measurement);atomic_json(state/'report.json',report)
 return report
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--dataset',type=Path,required=True);p.add_argument('--state',type=Path,required=True);p.add_argument('--attempt',type=Path,required=True);p.add_argument('--steps',type=int,required=True);p.add_argument('--max-seconds',type=int,required=True);p.add_argument('--training-attribution',action='store_true');a=p.parse_args();stop=threading.Event()
 for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
 run_segments(a.dataset,a.state,a.attempt,a.steps,a.max_seconds,stop=stop,training_only=a.training_attribution)
