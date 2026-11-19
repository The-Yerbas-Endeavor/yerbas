"""Bounded profiler exports; no claim of calibrated or complete GPU time."""
import hashlib,json
from contextlib import contextmanager
from kernel_timing import read_trace
MAX_WINDOWS=61
MAX_TOTAL_BYTES=1024*1024*1024

@contextmanager
def optimizer_steps(torch,profiler):
 original=torch.optim.SGD.step
 def step(optimizer,*args,**kwargs):
  result=original(optimizer,*args,**kwargs)
  # Complete submitted GPU work before switching capture windows.
  torch.cuda.synchronize();profiler.step()
  return result
 torch.optim.SGD.step=step
 try:yield
 finally:torch.optim.SGD.step=original

class Windows:
 def __init__(self,directory):self.directory=directory;self.windows=[];self.bytes=0
 def capture(self,profiler):
  try:self._capture(profiler)
  except Exception as exc:
   (self.directory/'capture-failure.json').write_text(json.dumps(dict(error_type=type(exc).__name__,error=str(exc),completed_windows=len(self.windows),trace_bytes=self.bytes))+'\n')
   raise
 def _capture(self,profiler):
  if len(self.windows)>=MAX_WINDOWS:raise ValueError('Trace window bound exceeded')
  path=self.directory/('trace-%03d.json'%len(self.windows));profiler.export_chrome_trace(str(path))
  self.bytes+=path.stat().st_size
  if self.bytes>MAX_TOTAL_BYTES:raise ValueError('Total trace size bound exceeded')
  result=read_trace(path)
  # Kernel timestamps must not overlap exported windows; otherwise summing
  # their individual unions would double count time.
  events=json.loads(path.read_text())['traceEvents']
  kernels=[e for e in events if e.get('cat')=='kernel' and e.get('dur',0)>0]
  first=min(e['ts'] for e in kernels);last=max(e['ts']+e['dur'] for e in kernels)
  if self.windows and first<self.windows[-1]['last_kernel_us']:raise ValueError('Overlapping trace windows')
  self.windows.append(dict(file=path.name,bytes=path.stat().st_size,first_kernel_us=first,last_kernel_us=last,measurement=result))
 def finish(self):
  if not self.windows:raise ValueError('No captured windows')
  index=self.directory/'trace-index.json';index.write_text(json.dumps(dict(schema=1,windows=self.windows),indent=2)+'\n')
  return dict(schema=1,logical_device=0,kernel_events=sum(w['measurement']['kernel_events'] for w in self.windows),observed_kernel_union_us=sum(w['measurement']['observed_kernel_union_us'] for w in self.windows),trace_sha256=hashlib.sha256(index.read_bytes()).hexdigest(),trace_kind='hashed-index-of-nonoverlapping-kernel-windows',trace_windows=len(self.windows),trace_bytes=self.bytes,capture_completeness_verified=False,approved_gpu_ms=None,gpu_active_ms=None,reward_eligible=False)
