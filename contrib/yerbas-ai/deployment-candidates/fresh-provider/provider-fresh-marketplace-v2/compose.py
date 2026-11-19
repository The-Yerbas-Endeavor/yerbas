"""Compose a disabled fresh-host plan. No live install or activation operation."""
import hashlib
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
LEGACY = ROOT.parent / 'provider-fresh-host-candidate-v1'
sys.path.insert(0, str(LEGACY))
from provision_plan import build as setup
from owner_agent_plan import plan as owner_setup
from verify import DATA_PINS
from build_runtime import checked


def compose(owner_uid, owner_gid, provider_uid, provider_gid, home, hostname):
    if not isinstance(hostname, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', hostname):
        raise ValueError('Explicit provider hostname required')
    root = setup(owner_uid, owner_gid, provider_uid, provider_gid)
    owner = owner_setup(owner_uid, owner_gid, home)
    files = {}
    def add(target, raw, uid=0, gid=0, mode=0o644):
        if target in files:
            raise ValueError('Duplicate target')
        files[target] = dict(content_hex=raw.hex(), sha256=hashlib.sha256(raw).hexdigest(),
                             uid=uid, gid=gid, mode=mode)
    for target, entry in root['files'].items():
        raw = entry['content'].encode()
        if target.endswith('/broker.json'):
            config = json.loads(raw);config['rentals_enabled'] = False
            raw = (json.dumps(config, sort_keys=True)+'\n').encode()
        add(target, raw, entry['uid'], entry['gid'], entry['mode'])
    source = json.loads((ROOT/'CONTROL-SOURCES.json').read_text())
    for name, record in source['files'].items():
        raw = checked(ROOT/'control-source', name, record['sha256'])
        group, leaf = name.split('/')
        if name == 'broker/provider_broker_daemon.py':
            old = b"POLICY=Path('/etc/yerbas-ai/provider.json')"
            if raw.count(old) != 1:raise ValueError('Broker policy baseline differs')
            raw = raw.replace(old, b"POLICY=Path('/etc/yerbas-ai/provider-direct-cupti-v1.json')")
        if group == 'owner':
            add(str(Path(home)/'.local/share/yerbas-ai-control-v1/code'/leaf), raw,
                owner_uid, owner_gid, 0o600)
        else:
            prefix = 'broker-v1' if group == 'broker' else 'reward-requests-v1'
            add('/opt/yerbas-ai/'+prefix+'/'+leaf, raw)
    runtime_root = ROOT/'staged-direct-runtime'
    manifest = json.loads((runtime_root/'MANIFEST.json').read_text())
    for name, digest in manifest['files'].items():
        raw = checked(runtime_root, name, digest)
        group, leaf = name.split('/',1)
        prefix = 'provider-direct-cupti-v1' if group == 'runtime' else 'provider-direct-payload-v1'
        add('/opt/yerbas-ai/'+prefix+'/'+leaf, raw)
        if name in ('runtime/provider_executor.py','runtime/direct_policy.py','runtime/measurement_policy.py'):
            add('/opt/yerbas-ai/broker-v1/'+leaf, raw)
    for name, digest in DATA_PINS.items():
        if name.startswith('source-license/'):
            raw = checked(LEGACY/'rootfs/opt/yerbas-ai/provider-v1', name, digest)
            add('/opt/yerbas-ai/provider-direct-payload-v1/'+name, raw)
    add('/etc/yerbas-ai/provider-direct-cupti-mode.json', b'{"enabled":false}\n', mode=0o600)
    add('/etc/yerbas-ai/reward-requests.json', (json.dumps(dict(schema=1,owner_uid=owner_uid,
        provider_uid=provider_uid,provider=hostname),sort_keys=True)+'\n').encode())
    unitbase = LEGACY/'rootfs/etc/systemd/system'
    add('/etc/systemd/system/yerbas-provider-broker.service', (unitbase/'yerbas-provider-broker.service').read_bytes())
    for mode in ('provider','replay'):
        text = (unitbase/('yerbas-text-'+mode+'@.service')).read_text()
        lines = []
        for line in text.splitlines():
            if line.startswith('ExecStart='):
                line = 'ExecStart=/opt/yerbas-ai/runtime-v1/venv/bin/python -I -B /opt/yerbas-ai/provider-direct-cupti-v1/bootstrap.py --request /var/lib/yerbas-ai-provider/requests/%i.json'+(' --replay-only' if mode=='replay' else '')
            line = line.replace('WorkingDirectory=/opt/yerbas-ai/provider-v1/code', 'WorkingDirectory=/opt/yerbas-ai/provider-direct-cupti-v1')
            line = line.replace('ReadWritePaths=/var/lib/yerbas-ai-provider/jobs','ReadWritePaths=/var/lib/yerbas-ai-provider/direct-cupti-jobs-v1')
            lines.append(line)
        add('/etc/systemd/system/yerbas-text-'+mode+'@.service', ('\n'.join(lines)+'\n').encode())
    add(owner['unit']['destination'], owner['unit']['content'].encode())
    gates = '\n'.join('ConditionPathExists='+path for path in (
        '/etc/yerbas-ai/provider-future-enrollment.json',
        '/etc/yerbas-ai/marketplace-buyer-v1.json',
        '/etc/yerbas-ai/future-coordinator-ca.pem'))
    add('/etc/systemd/system/yerbas-ai-reward-request.socket', (f'''[Unit]
Description=Yerbas enrolled marketplace relay socket
{gates}
[Socket]
ListenStream=/run/yerbas-ai-reward-request.sock
SocketUser={provider_uid}
SocketGroup={owner_gid}
SocketMode=0660
FileDescriptorName=reward-request
RemoveOnStop=yes
''').encode())
    add('/etc/systemd/system/yerbas-ai-reward-request.service', (f'''[Unit]
Description=Yerbas enrolled marketplace HTTPS relay
Requires=yerbas-ai-reward-request.socket
After=yerbas-ai-reward-request.socket
{gates}
[Service]
User={provider_uid}
Group={provider_gid}
ExecStart=/usr/bin/python3 -I -B /opt/yerbas-ai/reward-requests-v1/reward_daemon.py
WorkingDirectory=/opt/yerbas-ai/reward-requests-v1
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
RestrictAddressFamilies=AF_UNIX AF_INET
IPAddressDeny=any
IPAddressAllow=127.0.0.1/32
CapabilityBoundingSet=
RestrictSUIDSGID=yes
LockPersonality=yes
MemoryMax=64M
TasksMax=4
TimeoutStopSec=8
Restart=on-failure
RestartSec=3
''').encode())
    directories = root['directories'] | owner['directories']
    directories['/var/lib/yerbas-ai-provider/direct-cupti-jobs-v1'] = dict(uid=provider_uid,gid=provider_gid,mode=0o700)
    anchors = {'/','/opt','/etc','/etc/systemd','/etc/systemd/system','/etc/tmpfiles.d','/var','/var/lib','/run',str(Path(home)),str(Path(home)/'.local'),str(Path(home)/'.local/share')}
    for target, entry in files.items():
        for parent in Path(target).parents:
            name = str(parent)
            if name in anchors:break
            directories.setdefault(name, dict(uid=entry['uid'],gid=entry['gid'],mode=0o700 if entry['uid'] else 0o755))
    return dict(schema=2,files=files,directories=directories,submissions_enabled=False,
                activate_services=False,installable=False,existing_state_copied=False,
                remaining=['credential and GPU enrollment',
                           'guarded root/owner application and fresh physical-host acceptance'])


if __name__ == '__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('owner-uid','owner-gid','provider-uid','provider-gid'):
        p.add_argument('--'+name,type=int,required=True)
    p.add_argument('--home',required=True);p.add_argument('--hostname',required=True)
    a=p.parse_args();result=compose(a.owner_uid,a.owner_gid,a.provider_uid,a.provider_gid,a.home,a.hostname)
    print(json.dumps(result,indent=2))
