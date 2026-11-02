"""Bind reaudited per-segment phase diagnostics to a completed receipt."""
import hashlib
import json
from pathlib import Path
from direct_evidence import bind
from direct_attempt import assignment_for
from direct_segments import aggregate, digest
from kernel_phases import analyze


def finalize(start, measurement, report, receipt, segments, phase_documents):
    legacy = bind(start, measurement, report, receipt)
    assignment = assignment_for(start)
    audited = aggregate(assignment, segments)
    if audited != measurement['direct']:
        raise ValueError('Raw segment aggregate differs from retained measurement')
    if len(phase_documents) != len(segments):
        raise ValueError('Incomplete phase evidence')
    totals = {'training':0, 'checkpoint':0}; rows=[]
    for segment, document in zip(segments,phase_documents):
        b=segment['binding'];identity=dict(run_id=b['run_id'],runtime_sha256=assignment['runtime_sha256'],recipe_sha256=digest(assignment['recipe_identity']))
        if document['identity']!=identity or document['interval_sha256']!=b['interval_sha256']:
            raise ValueError('Phase identity or interval digest differs')
        if document['instrumentation_sha256']!=hashlib.sha256(Path(__file__).with_name('phase_scope.py').read_bytes()).hexdigest():
            raise ValueError('Phase instrumentation changed')
        phases=document['phases']
        expected_checkpoints=b['end_step']//1000-b['start_step']//1000
        if sum(p['phase']=='checkpoint' for p in phases)!=expected_checkpoints:
            raise ValueError('Unexpected periodic checkpoint coverage')
        result=analyze(segment['intervals'],segment['transcript'],identity,segment['report']['kernel_records'],phases)
        for name in totals:totals[name]+=result['observed_kernel_union_ns'][name]
        rows.append(dict(start_step=b['start_step'],end_step=b['end_step'],phase_document_sha256=digest(document),attribution=result))
    if sum(totals.values())!=legacy['observed_kernel_union_ns']:
        raise ValueError('Phase totals differ from receipt-bound kernel total')
    result=dict(schema=1,kind='receipt-bound-training-kernel-attribution',
        receipt=receipt['receipt'],contribution=receipt['contribution'],provider=legacy['provider'],
        checkpoint_sha256=receipt['sha256'],attempt_id=legacy['attempt_id'],
        start_step=legacy['start_step'],end_step=legacy['end_step'],
        parent_evidence_sha256=legacy['evidence_sha256'],segments=rows,
        observed_kernel_union_ns=totals,capture_completeness_verified=False,
        calibration_verified=False,approved_gpu_ms=None,reward_eligible=False,
        trust='provider-local diagnostic; no independent honesty attestation')
    result['evidence_sha256']=digest(result)
    return result


def bind_directory(attempt,start,measurement,report,receipt):
    segments=[];documents=[]
    for index in range(measurement['direct']['execution_segments']):
        directory=attempt/('direct-segment-%02d'%index)
        def read(name):return json.loads((directory/name).read_text())
        segments.append(dict(binding=read('binding.json'),report=read('report.json'),
            transcript=(directory/'collector.jsonl').read_bytes(),intervals=(directory/'collector.jsonl.kernels').read_bytes()))
        documents.append(read('phases.json'))
    return finalize(start,measurement,report,receipt,segments,documents)
