"""Opt-in diagnostic adapter; use only beneath the bounded segment supervisor.
Not installed in the live provider or sealed pilot release.
"""
import hashlib,json,resource,signal,sys,threading,time
from pathlib import Path
# Development dependencies are existing, tested modules, not copied runtime state.
ROOT=Path(__file__).resolve().parents[1]
for name in ('contribution-timing-v1','yerbas-training-prototype'):
 sys.path.append(str(ROOT/name))
from window_capture import Windows
from attempt_evidence import digest
from sustained_training import atomic_json
from training_scope import instrument,instrumentation_sha256
from training_timing import attribute,aggregate

class TrainingWindows(Windows):
 def __init__(self,directory,start,end):
  super().__init__(directory);self.start=start;self.end=end;self.attributions=[]
 def _capture(self,profiler):
  super()._capture(profiler)
  entry=self.windows[-1]
  attribution=attribute(json.loads((self.directory/entry['file']).read_text()))
  entry['training_attribution']=attribution;self.attributions.append(attribution)
 def finish(self):
  coverage=aggregate(self.attributions,self.start,self.end)
  result=super().finish();result['training_attribution']=coverage
  return result

def collect(dataset,state,attempt,steps,seconds):
 import torch,text_neural
 start=json.loads((attempt/'start.json').read_text());expected=start['manifest']['identity'];end=start['manifest']['end_step']
 if text_neural.identity(dataset)!=expected:raise ValueError('Frozen recipe identity differs')
 if steps!=end-start['start_step'] or not 0<steps<=1000 or not 0<seconds<=120:raise ValueError('Segment budget differs')
 if not torch.cuda.is_available() or torch.cuda.device_count()!=1 or torch.profiler.ProfilerActivity.CUDA not in torch.profiler.supported_activities():raise ValueError('One supervised CUDA device and profiler required')
 if torch.__version__!='2.14.1+cu126':raise ValueError('Unvalidated profiler runtime')
 resource.setrlimit(resource.RLIMIT_FSIZE,(128*1024*1024,128*1024*1024));stop=threading.Event()
 for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
 windows=TrainingWindows(attempt,start['start_step'],end);began=time.monotonic_ns()
 with torch.profiler.profile(schedule=torch.profiler.schedule(wait=0,warmup=0,active=100,repeat=0),on_trace_ready=windows.capture,activities=[torch.profiler.ProfilerActivity.CPU,torch.profiler.ProfilerActivity.CUDA],record_shapes=False,profile_memory=False,with_stack=False) as profiler:
  with instrument(text_neural,torch,profiler):
   report=text_neural.run(dataset,state,'cuda',steps,seconds,stop)
   torch.cuda.synchronize()
 measurement=windows.finish()
 if report['resumed_from_step']!=start['start_step'] or report['step']!=end or report['owner_stopped']:raise ValueError('Incomplete training segment')
 measurement.update(attempt_sha256=digest(start),recipe_identity=expected,checkpoint_sha256=report['checkpoint_sha256'],profiled_process_wall_ns=time.monotonic_ns()-began,scope='diagnostic per-step attribution; nontraining observed kernels retained separately',profiler_overhead_present=True,instrumentation_sha256=instrumentation_sha256(),analyzer_sha256=hashlib.sha256(Path(__file__).with_name('training_timing.py').read_bytes()).hexdigest())
 atomic_json(attempt/'report.json',report);atomic_json(attempt/'measurement.json',measurement)
 return report

if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--dataset',type=Path,required=True);p.add_argument('--state',type=Path,required=True);p.add_argument('--attempt',type=Path,required=True);p.add_argument('--steps',type=int,required=True);p.add_argument('--max-seconds',type=int,required=True);a=p.parse_args();collect(a.dataset,a.state,a.attempt,a.steps,a.max_seconds)
