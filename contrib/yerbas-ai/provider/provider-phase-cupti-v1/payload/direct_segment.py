"""Execute one checkpoint-bound direct-collector segment in its own process."""
from contextlib import contextmanager
import ctypes
import hashlib
import json
from pathlib import Path
import resource
import signal
import sys
import threading
from collector_review import review
from interval_review import intervals
from phase_scope import scoped
import text_neural


def main():
    base, dataset, state, segment, cupti = map(Path, sys.argv[1:])
    resource.setrlimit(resource.RLIMIT_FSIZE, (16*1024*1024, 16*1024*1024))
    start = json.loads((segment/'start.json').read_text())
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: stop.set())
    import torch
    if torch.__version__ != '2.14.1+cu126' or torch.cuda.device_count() != 1:
        raise ValueError('Approved single-GPU runtime required')
    recipe = text_neural.identity(dataset)
    if recipe != start['recipe_identity']: raise ValueError('Recipe differs')
    checkpoint = state/'checkpoint.json'
    parent = hashlib.sha256(checkpoint.read_bytes()).hexdigest() if checkpoint.exists() else None
    if parent != start['parent_checkpoint_sha256']: raise ValueError('Checkpoint parent differs')
    if checkpoint.exists() and text_neural.read_checkpoint(checkpoint, recipe)['step'] != start['start_step']:
        raise ValueError('Checkpoint step differs')
    collector = ctypes.CDLL(str(base/'collector.so'))
    collector.yerbas_collector_start.argtypes = [ctypes.c_char_p]*5
    collector.yerbas_collector_kernel_records.restype = ctypes.c_ulong
    identity = dict(run_id=start['run_id'], runtime_sha256=start['runtime_sha256'], recipe_sha256=text_neural.digest(recipe))
    transcript = segment/'collector.jsonl'
    clock = ctypes.CDLL(str(cupti))
    clock.cuptiGetTimestamp.argtypes = [ctypes.POINTER(ctypes.c_uint64)]
    clock.cuptiGetTimestamp.restype = ctypes.c_int
    def stamp():
        value = ctypes.c_uint64()
        if clock.cuptiGetTimestamp(ctypes.byref(value)) or not value.value:
            raise RuntimeError('CUPTI timestamp unavailable')
        return value.value
    phases = []; active = False
    @contextmanager
    def boundary(name):
        nonlocal active
        if name == 'checkpoint' and not active:
            yield
            return
        if name == 'checkpoint':
            torch.cuda.synchronize(); began = stamp()
            try: yield
            finally:
                torch.cuda.synchronize()
                phases.append(dict(phase=name,cupti_start_ns=began,cupti_end_ns=stamp()))
            return
        torch.cuda.synchronize()
        code = collector.yerbas_collector_start(str(cupti).encode(), str(transcript).encode(),
                    identity['run_id'].encode(), identity['runtime_sha256'].encode(), identity['recipe_sha256'].encode())
        if code: raise RuntimeError('Collector startup failed: '+str(code))
        active = True; began = stamp()
        try: yield
        finally:
            torch.cuda.synchronize()
            phases.append(dict(phase='loop',cupti_start_ns=began,cupti_end_ns=stamp()))
            active = False
            code = collector.yerbas_collector_finish()
            if code: raise RuntimeError('Collector finalization failed: '+str(code))
    with scoped(text_neural, boundary):
        report = text_neural.run(dataset, state, 'cuda', start['end_step']-start['start_step'], start['max_seconds'], stop)
    if report['step'] != start['end_step'] or report['resumed_from_step'] != start['start_step'] or report['owner_stopped']:
        raise ValueError('Incomplete segment; checkpoint retained, no timing aggregate')
    kernels = collector.yerbas_collector_kernel_records()
    intervals(Path(str(transcript)+'.kernels').read_bytes(), transcript.read_bytes(), identity, kernels)
    result = {k: report[k] for k in ('identity','resumed_from_step','step','device','owner_stopped','checkpoint_sha256')}
    result['kernel_records'] = kernels
    if hashlib.sha256(checkpoint.read_bytes()).hexdigest() != report['checkpoint_sha256']:
        raise ValueError('Saved checkpoint differs')
    document = dict(identity=identity,phases=phases,interval_sha256=hashlib.sha256(Path(str(transcript)+'.kernels').read_bytes()).hexdigest(),instrumentation_sha256=hashlib.sha256((base/'phase_scope.py').read_bytes()).hexdigest())
    (segment/'phases.json').write_text(json.dumps(document,indent=2)+'\n')
    (segment/'full-report.json').write_text(json.dumps(report, indent=2)+'\n')
    (segment/'report.json').write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__': main()
