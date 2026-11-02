"""Bounded direct CUPTI executor beneath the existing schema-4 worker."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid
from direct_segments import aggregate, digest
from kernel_phases import analyze
from sustained_training import atomic_json

RUNTIME_SHA = '0341b39fc44ec6533c42861e8dd602dfa4182fdba1ceef02a2b9187bb5001112'
CUPTI_SHA = '76dcad94420820ea9aee9094c346cc34c6cb1ff630cef9b14e04db298a86305d'

def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def runtime_files():
    sites = list(Path(sys.prefix).glob('lib/python*/site-packages'))
    if len(sites) != 1: raise ValueError('Ambiguous runtime')
    cpu = sites[0]/'torch/lib/libtorch_cpu.so'
    cupti = sites[0]/'nvidia/cuda_cupti/lib/libcupti.so.12'
    if file_sha(cpu) != RUNTIME_SHA or file_sha(cupti) != CUPTI_SHA:
        raise ValueError('Unvalidated runtime or CUPTI library')
    return cupti

def assignment_for(start):
    m = start['manifest']
    if start.get('schema') != 1 or not m['start_step'] <= start['start_step'] < m['end_step']:
        raise ValueError('Invalid retained attempt range')
    return dict(attempt_id=start['attempt_id'], provider=m['provider'], physical_gpu=start['physical_gpu'],
        recipe_identity=m['identity'], runtime_sha256=RUNTIME_SHA, start_step=start['start_step'],
        end_step=m['end_step'], initial_checkpoint_sha256=start.get('initial_checkpoint_sha256'))

def run(dataset, state, attempt, steps, seconds, *, stop=None, clock=time.monotonic, launch=subprocess.Popen, runtime=runtime_files, check=lambda:None):
    start = json.loads((attempt/'start.json').read_text()); assignment = assignment_for(start)
    if type(steps) is not int or steps != assignment['end_step']-assignment['start_step'] or not 0 < steps <= 6000:
        raise ValueError('Attempt step budget differs')
    if type(seconds) is not int or not 1 <= seconds <= 120: raise ValueError('Invalid deadline')
    stop = stop or threading.Event(); deadline = clock()+seconds
    cupti = runtime()
    atomic_json(attempt/'direct-assignment.json', assignment)
    current = assignment['start_step']; parent = assignment['initial_checkpoint_sha256']; segments = []; full_reports = []
    while current < assignment['end_step']:
        check()
        remaining = math.floor(deadline-clock())
        if stop.is_set() or remaining < 1: raise RuntimeError('Owner stop or original attempt deadline')
        checkpoint = state/'checkpoint.json'
        if (file_sha(checkpoint) if checkpoint.exists() else None) != parent:
            raise ValueError('Checkpoint changed before segment')
        end = min(current+1000, assignment['end_step']); index = len(segments)
        directory = attempt/('direct-segment-%02d'%index); directory.mkdir(mode=0o700)
        child = dict(run_id=uuid.uuid4().hex, runtime_sha256=RUNTIME_SHA, recipe_identity=assignment['recipe_identity'],
                     start_step=current, end_step=end, parent_checkpoint_sha256=parent, max_seconds=remaining)
        atomic_json(directory/'start.json',child)
        argv = [sys.executable,'-B',str(Path(__file__).with_name('direct_segment.py')),str(Path(__file__).parent),
                str(dataset),str(state),str(directory),str(cupti)]
        with (directory/'runner.log').open('w') as log:
            process = launch(argv,stdout=log,stderr=subprocess.STDOUT)
            try:
                while process.poll() is None:
                    check()
                    if stop.is_set() or clock() >= deadline: raise RuntimeError('Attempt stopped or timed out')
                    stop.wait(.1)
                if process.returncode: raise RuntimeError('Direct collector segment failed; checkpoint retained')
            finally:
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
                atomic_json(directory/'process-result.json',dict(exit_code=process.returncode))
        if stop.is_set() or clock() >= deadline: raise RuntimeError('Stopped before accepting segment')
        report = json.loads((directory/'report.json').read_text())
        full = json.loads((directory/'full-report.json').read_text())
        if any(full[k] != report[k] for k in ('identity','resumed_from_step','step','device','owner_stopped','checkpoint_sha256')):
            raise ValueError('Full report differs from measured report')
        if file_sha(checkpoint) != report['checkpoint_sha256']: raise ValueError('Checkpoint differs after segment')
        transcript = (directory/'collector.jsonl').read_bytes(); intervals = (directory/'collector.jsonl.kernels').read_bytes()
        binding = dict(assignment_sha256=digest(assignment),segment_index=index,run_id=child['run_id'],start_step=current,
            end_step=end,parent_checkpoint_sha256=parent,checkpoint_sha256=report['checkpoint_sha256'],
            transcript_sha256=hashlib.sha256(transcript).hexdigest(),interval_sha256=hashlib.sha256(intervals).hexdigest())
        phase = json.loads((directory/'phases.json').read_text())
        expected_identity = dict(run_id=child['run_id'],runtime_sha256=RUNTIME_SHA,recipe_sha256=digest(assignment['recipe_identity']))
        if phase['identity'] != expected_identity or phase['interval_sha256'] != binding['interval_sha256'] or phase['instrumentation_sha256'] != file_sha(Path(__file__).with_name('phase_scope.py')):
            raise ValueError('Phase binding differs')
        if sum(p['phase']=='checkpoint' for p in phase['phases']) != end//1000-current//1000:
            raise ValueError('Checkpoint phase count differs')
        analyze(intervals,transcript,expected_identity,report['kernel_records'],phase['phases'])
        item = dict(binding=binding,report=report,transcript=transcript,intervals=intervals)
        aggregate(assignment,segments+[item],require_complete=False)
        atomic_json(directory/'binding.json',binding)
        segments.append(item);full_reports.append(full);parent=report['checkpoint_sha256'];current=end
    measured = aggregate(assignment,segments)
    if stop.is_set() or clock() >= deadline: raise RuntimeError('Deadline reached before publishing measurement')
    report = dict(full_reports[-1],resumed_from_step=assignment['start_step'],
                  initial_bits_per_byte=full_reports[0]['initial_bits_per_byte'],
                  elapsed_training_seconds=sum(x['elapsed_training_seconds'] for x in full_reports))
    measurement = dict(schema=2,kind='direct-cupti-attempt',attempt_sha256=digest(start),
        recipe_identity=assignment['recipe_identity'],checkpoint_sha256=parent,direct=measured,
        capture_completeness_verified=False,calibration_verified=False,approved_gpu_ms=None,reward_eligible=False,
        phase_attribution_required=True, activity_scope='training loop including periodic checkpoint persistence; excludes initialization and final evaluation/generation')
    atomic_json(attempt/'report.json',report);atomic_json(attempt/'measurement.json',measurement)
    atomic_json(state/'report.json',report)
    return report

if __name__ == '__main__':
    p=argparse.ArgumentParser()
    for key in ('dataset','state','attempt'): p.add_argument('--'+key,type=Path,required=True)
    for key in ('steps','max-seconds'): p.add_argument('--'+key,type=int,required=True)
    a=p.parse_args();stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM): signal.signal(sig,lambda *_:stop.set())
    run(a.dataset,a.state,a.attempt,a.steps,a.max_seconds,stop=stop)
