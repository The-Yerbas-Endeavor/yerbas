#!/usr/bin/env python3
"""Bounded SSH-driven five-host regtest connectivity smoke, not a 100-node DKG test.

Requires a local runtime archive containing bin/yerbasd, bin/yerbas-cli and lib/.
Each remote daemon is a transient systemd service with a hard runtime limit.
Only the listed campaign hosts and localhost may communicate with its cgroup.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import json
from pathlib import Path
import shlex
import subprocess
import time

SSH = ['ssh', '-o', 'IdentitiesOnly=no', '-o', 'BatchMode=yes', '-o',
       'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10']


def command(args, timeout=120, check=True):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Command failed')
    return result


def remote(host, args, **kwargs):
    return command(SSH + [host, shlex.join(args)], **kwargs)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--hosts', nargs=5, required=True, help='Coordinator followed by four smartnode hosts')
    p.add_argument('--runtime', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--max-seconds', type=int, default=900)
    args = p.parse_args()
    if not 120 <= args.max_seconds <= 43200:
        p.error('--max-seconds must be between 120 and 43200 (12 hours)')
    if len(set(args.hosts)) != 5 or any(h.startswith('-') for h in args.hosts):
        p.error('Supply five distinct SSH aliases')
    if args.output.exists():
        p.error('Output must not already exist')
    tag = 'yerbas-regtest-smoke-' + str(int(time.time()))
    root = '/opt/' + tag
    addresses = {}
    for host in args.hosts:
        config = command(SSH + ['-G', host]).stdout
        address = next(line.split()[1] for line in config.splitlines() if line.startswith('hostname '))
        addresses[host] = str(ipaddress.IPv4Address(address))
    started = []; firewall_rules = []; results = {'campaign': tag, 'maxSeconds': args.max_seconds,
                             'scope': 'One unregistered regtest full node per host; no DKG or RC validation.',
                             'hosts': {}, 'checks': [], 'stopped': {}}

    def rpc(host, *values):
        raw = remote(host, ['env', 'LD_LIBRARY_PATH=' + root + '/lib',
                           root + '/bin/yerbas-cli', '-regtest', '-datadir=' + root + '/data',
                           *map(str, values)]).stdout.strip()
        try:
            return json.loads(raw)
        except ValueError:
            return raw

    def wait(predicate, seconds=120):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate(): return
            time.sleep(1)
        raise RuntimeError('Timed out waiting for smoke condition')

    def prepare(host):
        capacity = remote(host, ['python3', '-c', "import os,json;from pathlib import Path;m={x.split(':')[0]:int(x.split()[1]) for x in Path('/proc/meminfo').read_text().splitlines()};print(json.dumps({'cpus':os.cpu_count(),'memoryKiB':m['MemTotal'],'availableKiB':m['MemAvailable']}))"]).stdout
        results['hosts'][host] = json.loads(capacity)
        remote(host, ['mkdir', '-m', '700', root])
        command(['scp', '-o', 'IdentitiesOnly=no', '-o', 'BatchMode=yes', '-o',
                 'StrictHostKeyChecking=yes', str(args.runtime.resolve()), host + ':' + root + '/runtime.tar.gz'])
        remote(host, ['tar', '-xzf', root + '/runtime.tar.gz', '-C', root])
        config = ('regtest=1\nserver=1\nlisten=1\nbind=0.0.0.0:22421\nport=22421\n'
                  'rpcbind=127.0.0.1\nrpcallowip=127.0.0.1\nrpcport=22422\n'
                  'dnsseed=0\ndiscover=0\nupnp=0\nconnect=0\ndbcache=16\npar=1\n'
                  'maxconnections=16\nprinttoconsole=0\nposeactivationheight=600\nrecoveryactivationheight=600\n')
        setup = 'from pathlib import Path;p=Path(' + repr(root + '/data') + ');p.mkdir(mode=0o700);(p/"yerbas.conf").write_text(' + repr(config) + ')'
        remote(host, ['python3', '-c', setup])
        hashes = remote(host, ['sha256sum', root + '/bin/yerbasd']).stdout.split()[0]
        results['hosts'][host]['daemonSha256'] = hashes

    try:
        with ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(prepare, args.hosts))
        assert len({v['daemonSha256'] for v in results['hosts'].values()}) == 1
        for host in args.hosts:
            for source in addresses.values():
                rule = ['allow', 'from', source, 'to', 'any', 'port', '22421', 'proto', 'tcp', 'comment', tag]
                added = remote(host, ['ufw', *rule]).stdout
                if 'Skipping' not in added:
                    firewall_rules.append((host, rule))
            # Track before launch so cleanup also covers an ambiguous SSH response.
            started.append(host)
            remote(host, ['systemd-run', '--unit=' + tag, '--property=RuntimeMaxSec=' + str(args.max_seconds),
                          '--property=TimeoutStopSec=30', '--property=KillMode=mixed',
                          '--property=IPAddressDeny=any',
                          '--property=IPAddressAllow=127.0.0.0/8 ' + ' '.join(addresses.values()),
                          '--setenv=LD_LIBRARY_PATH=' + root + '/lib',
                          root + '/bin/yerbasd', '-datadir=' + root + '/data'])
            def ready():
                try: return rpc(host, 'getblockcount') == 0
                except RuntimeError: return False
            wait(ready)
            print(host + ': daemon ready with systemd runtime limit', flush=True)
        first = args.hosts[0]
        address = rpc(first, 'getnewaddress')
        rpc(first, 'generatetoaddress', 1, address)
        for host in args.hosts[1:]:
            rpc(host, 'addnode', addresses[first] + ':22421', 'onetry')
        wait(lambda: all(rpc(h, 'getblockcount') == 1 for h in args.hosts))
        results['checks'].append('Five hosts synchronize the bootstrap block over public P2P services')
        start = time.monotonic()
        rpc(first, 'generatetoaddress', 20, address)
        tip = rpc(first, 'getbestblockhash')
        wait(lambda: all(rpc(h, 'getbestblockhash') == tip for h in args.hosts))
        results['propagationCheckSeconds'] = time.monotonic() - start
        results['height'] = 21; results['tip'] = tip
        for host in args.hosts:
            assert rpc(host, 'getblockchaininfo')['chain'] == 'regtest'
            results['hosts'][host]['peers'] = rpc(host, 'getconnectioncount')
        results['checks'].append('Twenty additional blocks accepted with an identical tip on all five hosts')
        results['passed'] = True
    finally:
        for host in reversed(started):
            try:
                remote(host, ['systemctl', 'stop', tag], timeout=60)
                status = remote(host, ['systemctl', 'is-active', tag], check=False).stdout.strip()
                results['stopped'][host] = status in ('inactive', 'failed', 'unknown')
            except Exception:
                results['stopped'][host] = False
        results['firewallCleanupFailures'] = []
        for host, rule in reversed(firewall_rules):
            try: remote(host, ['ufw', '--force', 'delete', *rule])
            except Exception: results['firewallCleanupFailures'].append(host)
        args.output.write_text(json.dumps(results, indent=2) + '\n')
    if not all(results['stopped'].values()):
        raise RuntimeError('Some stop commands failed; remote runtime limits remain in effect')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
