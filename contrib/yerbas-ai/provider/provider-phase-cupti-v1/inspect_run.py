"""Reaudit private installed phase evidence, without GPU work or mutation."""
import argparse
import json
import re
import runpy
import socket
import sys
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);args=p.parse_args()
    if not re.fullmatch('[a-f0-9]{32}',args.run_id):raise ValueError('Invalid run ID')
    sys.dont_write_bytecode=True
    code=Path('/opt/yerbas-ai/provider-phase-cupti-v1')
    runpy.run_path(str(code/'bootstrap.py'))['checked']()
    sys.path.insert(0,str(code))
    from phase_evidence import bind_directory
    from direct_segments import digest
    base=Path('/var/lib/yerbas-ai-provider/phase-cupti-jobs-v1')/(args.run_id+'-text-'+args.run_id)
    evidence=[]
    for attempt in sorted((base/'worker/training/measurements').iterdir()):
        saved=attempt/'receipt-phase-evidence.json'
        if not saved.exists():continue
        item=json.loads(saved.read_text())
        receipt=dict(receipt=item['receipt'],contribution=item['contribution'],sha256=item['checkpoint_sha256'])
        read=lambda name:json.loads((attempt/name).read_text())
        computed=bind_directory(attempt,read('start.json'),read('measurement.json'),read('report.json'),receipt)
        if computed!=item:raise ValueError('Retained phase evidence differs from raw reanalysis')
        if item['provider']!=socket.gethostname() or item['contribution']!='text-'+args.run_id:
            raise ValueError('Provider/contribution binding differs')
        evidence.append(item)
    if not evidence:raise ValueError('No completed receipt-bound phase evidence')
    print(json.dumps(dict(passed=True,host=socket.gethostname(),run_id=args.run_id,
        read_only=True,raw_segment_artifacts_reaudited=True,evidence=evidence,
        new_gpu_work=False,calibration_verified=False,reward_eligible=False),indent=2))


if __name__=='__main__':main()
