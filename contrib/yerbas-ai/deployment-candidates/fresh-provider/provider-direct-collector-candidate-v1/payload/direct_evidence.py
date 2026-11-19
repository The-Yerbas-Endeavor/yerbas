"""Versioned receipt binding; never upgrades diagnostics into payable time."""
import re
from direct_segments import digest
from direct_attempt import assignment_for

def bind(start, measurement, report, receipt):
    assignment = assignment_for(start); m = start['manifest']; d = measurement['direct']
    if measurement.get('schema') != 2 or measurement.get('kind') != 'direct-cupti-attempt':
        raise ValueError('Unexpected direct measurement version')
    if measurement['attempt_sha256'] != digest(start) or d['assignment_sha256'] != digest(assignment):
        raise ValueError('Attempt binding differs')
    if measurement['recipe_identity'] != m['identity'] or report['identity'] != m['identity']:
        raise ValueError('Recipe differs')
    if (report['resumed_from_step'] != start['start_step'] or report['step'] != m['end_step']
            or report['device'] != 'cuda' or report['owner_stopped'] is not False):
        raise ValueError('Incomplete assigned attempt')
    if (set(receipt) != {'receipt','sha256','contribution'} or not re.fullmatch('[a-f0-9]{32}',receipt['receipt'])
            or receipt['contribution'] != m['contribution']): raise ValueError('Receipt differs')
    if any(value != receipt['sha256'] for value in (report['checkpoint_sha256'],measurement['checkpoint_sha256'],d['checkpoint_sha256'])):
        raise ValueError('Receipt checkpoint differs')
    if (d['provider'] != m['provider'] or d['physical_gpu'] != start['physical_gpu']
            or d['start_step'] != start['start_step'] or d['end_step'] != m['end_step'] or d['assignment_complete'] is not True):
        raise ValueError('Direct assignment incomplete or differs')
    total=records=0;parent=assignment['initial_checkpoint_sha256'];current=start['start_step'];runs=set()
    for index, segment in enumerate(d['segments']):
        b=segment['binding'];v=segment['measurement']
        if (b['assignment_sha256'] != digest(assignment) or b['segment_index'] != index or b['start_step'] != current
                or not current < b['end_step'] <= min(current+1000,m['end_step']) or b['parent_checkpoint_sha256'] != parent
                or b['run_id'] in runs or b['interval_sha256'] != v['interval_sha256']):
            raise ValueError('Segment chain differs')
        ns=v['observed_kernel_union_ns'];count=v['kernel_records']
        if type(ns) is not int or ns<=0 or type(count) is not int or count<=0: raise ValueError('Invalid interval total')
        if ns>v['observed_kernel_sum_ns'] or ns>v['observed_kernel_span_ns']: raise ValueError('Invalid interval bounds')
        if v['approved_gpu_ms'] is not None or v['reward_eligible'] is not False or v['capture_completeness_verified'] is not False or v['calibration_verified'] is not False:
            raise ValueError('Unexpected segment approval')
        runs.add(b['run_id']);current=b['end_step'];parent=b['checkpoint_sha256'];total+=ns;records+=count
    if (current!=m['end_step'] or parent!=receipt['sha256'] or len(runs)!=d['execution_segments']
            or total!=d['observed_kernel_union_ns'] or records!=d['kernel_records']): raise ValueError('Aggregate differs')
    for value in (measurement,d):
        if (value['approved_gpu_ms'] is not None or any(value[k] is not False for k in
                ('reward_eligible','capture_completeness_verified','calibration_verified'))): raise ValueError('Unexpected approval claim')
    if d['provider_execution_attested'] is not False: raise ValueError('Unexpected attestation')
    result=dict(schema=2,kind='contribution-attempt-direct-cupti-evidence',attempt_id=start['attempt_id'],
        attempt_sha256=digest(start),measurement_sha256=digest(measurement),manifest_sha256=digest(m),
        provider=m['provider'],contribution=m['contribution'],receipt=receipt['receipt'],checkpoint_sha256=receipt['sha256'],
        physical_gpu=start['physical_gpu'],start_step=start['start_step'],end_step=report['step'],
        observed_kernel_union_ns=total,approved_gpu_ms=None,reward_eligible=False,
        blockers=['capture_completeness_unverified','includes_periodic_checkpoint_persistence','calibration_unverified','no_operator_gpu_time_approval'],
        trust='provider-local evidence; hashes do not prove honest computation or measurement')
    result['evidence_sha256']=digest(result)
    return result
