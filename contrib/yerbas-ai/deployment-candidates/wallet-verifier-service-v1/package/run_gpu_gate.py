"""Wait for the existing inference run to close, then run one bounded GPU probe."""
import json
import os
from pathlib import Path
import platform
import pwd
import subprocess
import time
import uuid

ROOT = Path('/var/lib/yerbas-training-experiment')
REMOTE_PROJECT = Path('/home/anno2/Documents/Codex/2026-10-28/files-pasted-by-the-user-codex')


def provider_processes(uid):
    busy = []
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():
            continue
        try:
            if p.stat().st_uid == uid:
                busy.append(int(p.name))
        except FileNotFoundError:
            pass
    return busy


def supervisors_closed(box, host):
    try:
        closed = json.loads((box / 'closed.json').read_text())
        ready = json.loads((box / 'ready.json').read_text())
        if not isinstance(closed, dict) or not isinstance(ready, dict):
            return False
        return (closed.get('closed') is True and closed.get('host') == host
                and ready.get('host') == host
                and type(ready.get('pid')) is int
                and not Path('/proc', str(ready['pid'])).exists()
                and (box / 'closed.json').stat().st_mtime_ns >=
                    (box / 'ready.json').stat().st_mtime_ns)
    except (OSError, ValueError, KeyError):
        return False


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo in your terminal.')
    host = platform.node()
    if host.lower() == 'u26-2t':
        gpu = '1'
        box = Path('/home/anno/yerbas-pilot-lan-anno2-u26/hour-pilot-control-02')
    elif host == 'anno2-u26':
        gpu = '0'
        box = REMOTE_PROJECT / 'work/hour-pilot/local-control-02'
    else:
        raise SystemExit('Unrecognized pilot host')
    if not (ROOT / 'INSTALL-COMPLETE.txt').is_file():
        raise SystemExit('Verified runtime installation is missing')
    account = pwd.getpwnam('yerbas-provider')
    deadline = time.monotonic() + 3900
    next_update = 0
    while not supervisors_closed(box, host) or provider_processes(account.pw_uid):
        if time.monotonic() >= deadline:
            raise SystemExit('Timed out waiting for inference shutdown; no GPU probe started')
        if time.monotonic() >= next_update:
            print(host + ': waiting for inference shutdown; no processes will be stopped.', flush=True)
            next_update = time.monotonic() + 60
        time.sleep(5)
    # Reserve this experiment against duplicate launcher invocations.
    import fcntl
    with (ROOT / 'gpu-probe.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if provider_processes(account.pw_uid):
            raise SystemExit('Provider account became busy; no GPU probe started')
        compute = subprocess.run(['nvidia-smi', '--id=' + gpu,
                                  '--query-compute-apps=pid', '--format=csv,noheader,nounits'],
                                 capture_output=True, text=True, check=True, timeout=15)
        if compute.stdout.strip():
            raise SystemExit('Selected GPU has another compute process; no probe started')
        # The operator must not start another pilot while this bounded probe runs.
        tag = uuid.uuid4().hex
        probe = ROOT / ('probe-' + tag + '.py')
        probe.write_bytes(Path(__file__).with_name('check_training_runtime.py').read_bytes())
        probe.chmod(0o644)
        command = ['runuser', '-u', 'yerbas-provider', '--', 'env', '-i',
                   'PATH=/usr/bin:/bin', 'HOME=' + account.pw_dir,
                   'PYTHONNOUSERSITE=1', 'CUDA_VISIBLE_DEVICES=' + gpu,
                   'CUBLAS_WORKSPACE_CONFIG=:4096:8',
                   'timeout', '--signal=TERM', '--kill-after=10s', '120s',
                   str(ROOT / 'environment/venv/bin/python'), str(probe),
                   '--device', '0', '--run-gpu-test']
        print(host + ': running bounded GPU probe on physical GPU ' + gpu, flush=True)
        result = subprocess.run(command, capture_output=True, text=True)
        try:
            evidence = json.loads(result.stdout)
        except ValueError:
            evidence = None
        report = {'host': host, 'physical_gpu': gpu, 'exit_code': result.returncode,
                  'passed': result.returncode == 0 and isinstance(evidence, dict)
                            and evidence.get('passed') is True,
                  'evidence': evidence, 'stdout': result.stdout, 'stderr': result.stderr}
        destination = ROOT / ('gpu-result-' + tag + '.json')
        destination.write_text(json.dumps(report, indent=2) + '\n')
        destination.chmod(0o644)
        print(json.dumps(report, indent=2), flush=True)
        print('Saved evidence: ' + str(destination), flush=True)
        if not report['passed']:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
