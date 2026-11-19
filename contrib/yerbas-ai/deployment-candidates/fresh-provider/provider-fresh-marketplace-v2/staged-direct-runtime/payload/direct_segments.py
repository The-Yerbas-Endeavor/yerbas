"""Aggregate checkpoint-linked collector segments without approving GPU time.

The assignment is supplied independently of provider reports. This validates
diagnostic provenance and interval arithmetic, not honest execution or credits.
"""
import hashlib
import json
import re
from interval_review import intervals


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def sha(value, length=64):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{%d}' % length, value):
        raise ValueError('Invalid digest or execution identity')
    return value


def step(value):
    if type(value) is not int or not 0 <= value <= 6000:
        raise ValueError('Invalid training step')
    return value


def aggregate(assignment, segments, *, require_complete=True):
    fields = {'attempt_id', 'provider', 'physical_gpu', 'recipe_identity', 'runtime_sha256',
              'start_step', 'end_step', 'initial_checkpoint_sha256'}
    if set(assignment) != fields:
        raise ValueError('Unexpected assignment fields')
    sha(assignment['attempt_id'], 32); sha(assignment['runtime_sha256'])
    if not isinstance(assignment['provider'], str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}', assignment['provider']):
        raise ValueError('Invalid provider')
    if assignment['physical_gpu'] not in ('0', '1'):
        raise ValueError('Unsupported GPU binding')
    recipe = assignment['recipe_identity']
    if not isinstance(recipe, dict) or set(recipe) != {'dataset', 'config', 'runner'}:
        raise ValueError('Incomplete recipe identity')
    for value in recipe.values(): sha(value)
    current, target = step(assignment['start_step']), step(assignment['end_step'])
    if current >= target or not isinstance(segments, list) or not 1 <= len(segments) <= 6000:
        raise ValueError('Empty or invalid assignment')
    parent = assignment['initial_checkpoint_sha256']
    if current == 0:
        if parent is not None: raise ValueError('Fresh assignment cannot have a checkpoint parent')
    else:
        sha(parent)
    assignment_sha = digest(assignment)
    runs = set(); traces = set(); interval_files = set(); measurements = []
    total_ns = 0; total_records = 0; total_bytes = 0
    for index, segment in enumerate(segments):
        if set(segment) != {'binding', 'report', 'transcript', 'intervals'}:
            raise ValueError('Unexpected segment fields')
        binding, report = segment['binding'], segment['report']
        if set(binding) != {'assignment_sha256', 'segment_index', 'run_id', 'start_step', 'end_step',
                            'parent_checkpoint_sha256', 'checkpoint_sha256', 'transcript_sha256', 'interval_sha256'}:
            raise ValueError('Unexpected segment binding fields')
        run = sha(binding['run_id'], 32)
        if run in runs: raise ValueError('Duplicate segment execution')
        runs.add(run)
        end = step(binding['end_step'])
        if binding['assignment_sha256'] != assignment_sha or type(binding['segment_index']) is not int or binding['segment_index'] != index:
            raise ValueError('Segment assignment or order differs')
        if type(binding['start_step']) is not int or binding['start_step'] != current or not current < end <= min(target, current+1000):
            raise ValueError('Overlapping, skipped or oversized checkpoint segment')
        if binding['parent_checkpoint_sha256'] != parent:
            raise ValueError('Checkpoint ancestry differs')
        checkpoint = sha(binding['checkpoint_sha256'])
        if set(report) != {'identity','resumed_from_step','step','device','owner_stopped','checkpoint_sha256','kernel_records'}:
            raise ValueError('Unexpected segment report fields')
        if (report['identity'] != recipe or type(report['resumed_from_step']) is not int
                or report['resumed_from_step'] != current or type(report['step']) is not int
                or report['step'] != end or report['device'] != 'cuda' or report['owner_stopped'] is not False
                or report['checkpoint_sha256'] != checkpoint):
            raise ValueError('Segment report differs from assignment')
        transcript, raw = segment['transcript'], segment['intervals']
        if not isinstance(transcript, bytes) or not isinstance(raw, bytes):
            raise ValueError('Raw collector artifacts required')
        total_bytes += len(transcript)+len(raw)
        if total_bytes > 128*1024*1024:
            raise ValueError('Aggregate diagnostic byte budget exceeded')
        trace_sha = hashlib.sha256(transcript).hexdigest(); interval_sha = hashlib.sha256(raw).hexdigest()
        if trace_sha != sha(binding['transcript_sha256']) or interval_sha != sha(binding['interval_sha256']):
            raise ValueError('Collector artifact digest differs')
        if trace_sha in traces or interval_sha in interval_files:
            raise ValueError('Collector evidence reused')
        traces.add(trace_sha); interval_files.add(interval_sha)
        identity = dict(run_id=run, runtime_sha256=assignment['runtime_sha256'], recipe_sha256=digest(recipe))
        measurement = intervals(raw, transcript, identity, report['kernel_records'])
        total_ns += measurement['observed_kernel_union_ns']; total_records += measurement['kernel_records']
        measurements.append(dict(binding=binding, measurement=measurement))
        current = end; parent = checkpoint
    if require_complete and current != target:
        raise ValueError('Assigned range incomplete; partial timing is not aggregated')
    return dict(schema=1, kind='checkpoint-linked-direct-collector-diagnostic',
                assignment_sha256=assignment_sha, provider=assignment['provider'], physical_gpu=assignment['physical_gpu'],
                start_step=assignment['start_step'], end_step=current, assignment_complete=current == target, checkpoint_sha256=parent,
                execution_segments=len(segments), kernel_records=total_records, artifact_bytes=total_bytes,
                observed_kernel_union_ns=total_ns, segments=measurements,
                scope='sum of per-process observed kernel unions over contiguous checkpoint-linked segments; no cross-process clock comparison',
                provider_execution_attested=False, capture_completeness_verified=False,
                calibration_verified=False, approved_gpu_ms=None, reward_eligible=False)
