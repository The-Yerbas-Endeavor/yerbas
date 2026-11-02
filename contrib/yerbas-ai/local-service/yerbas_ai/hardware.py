"""Read-only NVIDIA inventory. Device selection uses UUIDs, not CUDA ordinals."""
import csv
import io
import subprocess


def inventory():
    fields = 'index,uuid,name,memory.total,memory.used,utilization.gpu'
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu='+fields, '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=5, check=True)
        devices = []
        for row in csv.reader(io.StringIO(result.stdout), skipinitialspace=True):
            if len(row) != 6:
                raise ValueError('Unexpected GPU inventory format')
            index, uid, name, total, used, utilization = (v.strip() for v in row)
            def number(value):
                return int(value) if value.isdigit() else None
            devices.append({'index': index, 'uuid': uid, 'name': name,
                            'memory_total_mib': number(total),
                            'memory_used_mib': number(used),
                            'utilization_percent': number(utilization)})
        return {'available': bool(devices), 'backend': 'nvidia', 'devices': devices,
                'scope': 'Host inventory; availability does not guarantee model compatibility'}
    except (OSError, subprocess.SubprocessError, ValueError):
        return {'available': False, 'backend': 'nvidia', 'devices': [],
                'reason': 'NVIDIA inventory unavailable; driver, permissions, or utility may be missing'}


def resolve_gpu(selection, report):
    for device in report['devices']:
        if selection in (device['index'], device['uuid']):
            return device['uuid']
    raise ValueError('Requested NVIDIA GPU was not found; no automatic fallback')
