"""Candidate fixed-recipe subprocess. Must run under existing bounded supervisor."""
import argparse,hashlib,json,resource,signal,threading,time
from pathlib import Path
from attempt_evidence import digest
from window_capture import Windows,optimizer_steps
from sustained_training import atomic_json

def collect(dataset,state,attempt,steps,seconds):
 import torch
 from text_neural import identity,run
 from kernel_timing import read_trace
 start=json.loads((attempt/'start.json').read_text());expected=start['manifest']['identity']
 if identity(dataset)!=expected:raise ValueError('Frozen recipe identity differs')
 if steps!=start['manifest']['end_step']-start['start_step'] or not 0<steps<=1000 or not 0<seconds<=120:raise ValueError('Attempt budget differs')
 if not torch.cuda.is_available() or torch.cuda.device_count()!=1 or torch.profiler.ProfilerActivity.CUDA not in torch.profiler.supported_activities():raise ValueError('Single supervised CUDA device and profiler required')
 if torch.__version__!='2.14.1+cu126':raise ValueError('Unvalidated profiling runtime')
 resource.setrlimit(resource.RLIMIT_FSIZE,(128*1024*1024,128*1024*1024))
 stop=threading.Event()
 for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
 began=time.monotonic_ns()
 windows=Windows(attempt)
 with torch.profiler.profile(schedule=torch.profiler.schedule(wait=0,warmup=0,active=100,repeat=0),on_trace_ready=windows.capture,activities=[torch.profiler.ProfilerActivity.CPU,torch.profiler.ProfilerActivity.CUDA],record_shapes=False,profile_memory=False,with_stack=False) as profiler:
  with optimizer_steps(torch,profiler):
   report=run(dataset,state,'cuda',steps,seconds,stop)
   torch.cuda.synchronize()
 wall=time.monotonic_ns()-began
 measurement=windows.finish()
 measurement.update(attempt_sha256=digest(start),recipe_identity=expected,checkpoint_sha256=report['checkpoint_sha256'],profiled_process_wall_ns=wall,scope='observed CUDA kernels for one contribution attempt including evaluation and generation',profiler_overhead_present=True)
 atomic_json(attempt/'report.json',report);atomic_json(attempt/'measurement.json',measurement)
 return report
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--dataset',type=Path,required=True);p.add_argument('--state',type=Path,required=True);p.add_argument('--attempt',type=Path,required=True);p.add_argument('--steps',type=int,required=True);p.add_argument('--max-seconds',type=int,required=True);a=p.parse_args();collect(a.dataset,a.state,a.attempt,a.steps,a.max_seconds)
