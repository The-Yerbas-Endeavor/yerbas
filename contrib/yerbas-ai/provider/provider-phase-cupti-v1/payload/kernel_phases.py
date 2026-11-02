"""Partition validated kernel intervals using synchronized CUPTI-clock bounds."""
import json
from interval_review import intervals


def union(spans):
    total = 0; end = 0
    for a, b in sorted(spans):
        total += max(0, b-max(a, end)); end=max(end,b)
    return total


def partition(spans, loop, checkpoint):
    for bounds in (loop, checkpoint):
        if len(bounds)!=2 or any(type(x) is not int for x in bounds) or not 0<bounds[0]<bounds[1]:
            raise ValueError('Invalid phase timestamps')
    if not loop[0]<=checkpoint[0]<checkpoint[1]<=loop[1]:
        raise ValueError('Checkpoint not nested in loop')
    groups={'training':[], 'checkpoint':[]}
    for a,b in spans:
        if type(a) is not int or type(b) is not int or not loop[0]<=a<b<=loop[1]:
            raise ValueError('Kernel outside synchronized loop')
        if checkpoint[0]<=a<b<=checkpoint[1]:
            groups['checkpoint'].append((a,b))
        elif b<=checkpoint[0] or a>=checkpoint[1]:
            groups['training'].append((a,b))
        else:
            raise ValueError('Kernel crosses checkpoint boundary; attribution ambiguous')
    values={name:union(items) for name,items in groups.items()}
    if sum(values.values())!=union(spans):
        raise ValueError('Phase unions do not reconcile')
    return dict(observed_kernel_union_ns=values,kernel_records={name:len(items) for name,items in groups.items()},
                total_observed_kernel_union_ns=union(spans),capture_completeness_verified=False,
                calibration_verified=False,approved_gpu_ms=None,reward_eligible=False,
                scope='observed kernel intervals inside synchronized CUPTI-clock ranges; checkpoint kernels excluded from training bucket; no elapsed-time subtraction')


def analyze(raw, transcript, identity, count, phases):
    validated=intervals(raw,transcript,identity,count)
    if not (len(phases)==1 and phases[0]['phase']=='loop') and not (len(phases)==2 and {p['phase'] for p in phases}=={'loop','checkpoint'}):
        raise ValueError('Expected exactly one loop and checkpoint')
    bounds={p['phase']:(p['cupti_start_ns'],p['cupti_end_ns']) for p in phases}
    spans=[(e['start_ns'],e['end_ns']) for e in map(json.loads,raw.splitlines()) if e['kind']=='kernel']
    if 'checkpoint' in bounds:
        result=partition(spans,bounds['loop'],bounds['checkpoint'])
    else:
        a,b=bounds['loop']
        if type(a) is not int or type(b) is not int or not 0<a<b or any(not a<=x<y<=b for x,y in spans):
            raise ValueError('Invalid loop or out-of-range kernel')
        result=dict(observed_kernel_union_ns={'training':union(spans),'checkpoint':0},kernel_records={'training':len(spans),'checkpoint':0},total_observed_kernel_union_ns=union(spans),capture_completeness_verified=False,calibration_verified=False,approved_gpu_ms=None,reward_eligible=False,scope='observed kernels in synchronized loop without periodic checkpoint')
    if result['total_observed_kernel_union_ns']!=validated['observed_kernel_union_ns']:
        raise ValueError('Raw interval union differs')
    return result
