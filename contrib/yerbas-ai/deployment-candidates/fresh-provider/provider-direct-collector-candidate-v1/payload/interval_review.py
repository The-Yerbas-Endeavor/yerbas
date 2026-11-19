"""Union observed kernel intervals across streams; no reward-time calibration."""
import hashlib
import json
from collector_review import MAX_BYTES, MAX_EVENTS, natural, unique, review


def intervals(raw, transcript, expected, kernel_count):
    review(transcript, expected)
    if type(kernel_count) is not int or kernel_count <= 0:
        raise ValueError('Positive observed kernel count required')
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES or not raw.endswith(b'\n'):
        raise ValueError('Oversized or truncated interval file')
    lines = raw.splitlines()
    if len(lines) != kernel_count + 2 or len(lines) > MAX_EVENTS:
        raise ValueError('Kernel interval count differs')
    buffers = {e['buffer'] for e in (json.loads(l) for l in transcript.splitlines()) if e['kind'] == 'buffer_completed'}
    spans = []; seen = set(); devices = set()
    for seq, line in enumerate(lines):
        e = json.loads(line, object_pairs_hook=unique)
        if not isinstance(e, dict) or type(e.get('seq')) is not int or e['seq'] != seq:
            raise ValueError('Missing or reordered interval')
        if seq == 0:
            if e != dict(expected, seq=0, kind='start', schema=1) or type(e.get('schema')) is not int:
                raise ValueError('Interval identity differs')
        elif seq == len(lines)-1:
            if e != dict(seq=seq, kind='finish', kernel_records=kernel_count) or type(e.get('kernel_records')) is not int:
                raise ValueError('Interval footer differs')
        else:
            if set(e) != {'seq','kind','buffer','device','stream','correlation','start_ns','end_ns'} or e['kind'] != 'kernel':
                raise ValueError('Unexpected kernel fields')
            if not isinstance(e['buffer'], str) or e['buffer'] not in buffers:
                raise ValueError('Kernel buffer not completed')
            for key in ('device','stream','correlation','start_ns','end_ns'):
                if natural(e[key]) >= 2**64:
                    raise ValueError('Kernel value exceeds bounds')
            start, end = e['start_ns'], e['end_ns']
            if not 0 < start < end or end-start > 60_000_000_000:
                raise ValueError('Missing, reversed or unbounded timestamps')
            identity = tuple(e[k] for k in ('device','stream','correlation','start_ns','end_ns'))
            if identity in seen:
                raise ValueError('Duplicate kernel record')
            seen.add(identity); devices.add(e['device']); spans.append((start, end))
    if len(devices) != 1:
        raise ValueError('Single-device diagnostic required')
    spans.sort(); first, end = spans[0]; union = 0; begin = first
    for start, stop in spans[1:]:
        if start > end:
            union += end-begin; begin, end = start, stop
        else:
            end = max(end, stop)
    union += end-begin
    span = end-first
    if span > 60_000_000_000:
        raise ValueError('Observed span exceeds diagnostic deadline')
    return dict(kernel_records=kernel_count, cupti_device_id=next(iter(devices)),
                observed_kernel_union_ns=union, observed_kernel_sum_ns=sum(b-a for a,b in spans),
                observed_kernel_span_ns=span, interval_sha256=hashlib.sha256(raw).hexdigest(),
                scope='union of reported kernel intervals across streams on one device; excludes gaps and transfers',
                capture_completeness_verified=False, calibration_verified=False,
                approved_gpu_ms=None, reward_eligible=False)
