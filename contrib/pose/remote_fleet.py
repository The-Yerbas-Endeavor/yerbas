#!/usr/bin/env python3
"""SSH backend for the real-DKG regtest campaign; requires explicitly supplied hosts.

RPC stays on each host's loopback. RuntimeMaxSec bounds every daemon independently
of the controller. This stops workloads, not cloud billing or the VPS itself.
"""
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import json
import math
from pathlib import Path
import shlex
import subprocess
import tarfile
import tempfile
import time
from recovery_network_test import Node, wait_for


class RemoteFleet:
    def __init__(self, root, hosts, runtime, max_seconds):
        if len(set(hosts)) != 5 or any(h.startswith('-') for h in hosts):
            raise ValueError('Five distinct SSH aliases are required')
        if not 600 <= max_seconds <= 43200:
            raise ValueError('Remote campaign limit must be 600..43200 seconds')
        self.root = root
        self.hosts = hosts
        self.runtime = runtime.resolve()
        self.deadline = time.monotonic() + max_seconds
        self.tag = 'yerbas-dkg-' + str(int(time.time()))
        self.remote_root = '/opt/' + self.tag
        self.addresses = {}
        self.created = []
        self.capacity = {}
        self.firewall_rules = []
        self.control_dir = tempfile.TemporaryDirectory(prefix='yerbas-ssh-')
        self.ssh = ['ssh', '-o', 'IdentitiesOnly=no', '-o', 'BatchMode=yes',
                    '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10',
                    '-o', 'ControlMaster=auto', '-o', 'ControlPersist=120',
                    '-o', 'ControlPath=' + str(Path(self.control_dir.name) / '%C')]
        for host in hosts:
            config = self.run(self.ssh + ['-G', host]).stdout
            addr = next(x.split()[1] for x in config.splitlines() if x.startswith('hostname '))
            self.addresses[host] = str(ipaddress.IPv4Address(addr))

    @staticmethod
    def run(args, timeout=180, check=True):
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        if check and r.returncode:
            raise RuntimeError(r.stderr.strip() or 'Remote command failed')
        return r

    def call(self, host, args, **kwargs):
        return self.run(self.ssh + [host, shlex.join(args)], **kwargs)

    def remaining(self):
        left = math.floor(self.deadline - time.monotonic())
        if left < 30:
            raise RuntimeError('Campaign deadline reached; stopping daemons')
        return left

    def upload(self, host, source, destination):
        self.remaining()
        self.run(['scp', *self.ssh[1:], str(source), host + ':' + destination])

    def prepare(self):
        # Inspect every host before staging anything or mining setup blocks.
        for i, host in enumerate(self.hosts):
            code = "import os,json;from pathlib import Path;m={x.split(':')[0]:int(x.split()[1]) for x in Path('/proc/meminfo').read_text().splitlines()};v=os.statvfs('/opt');print(json.dumps({'cpus':os.cpu_count(),'memoryKiB':m['MemTotal'],'availableKiB':m['MemAvailable'],'freeBytes':v.f_bavail*v.f_frsize}))"
            c = json.loads(self.call(host, ['python3', '-c', code]).stdout)
            self.capacity[host] = c
            min_cpu, min_ram, min_free = (2, 3, 10) if i == 0 else (4, 14, 40)
            if c['cpus'] < min_cpu or c['memoryKiB'] < min_ram * 1024**2 or c['freeBytes'] < min_free * 1024**3:
                raise RuntimeError(host + ': capacity below the agreed campaign profile; resize before starting 100 nodes')
        def stage(host):
            self.call(host, ['mkdir', '-m', '700', self.remote_root])
            self.upload(host, self.runtime, self.remote_root + '/runtime.tar.gz')
            self.call(host, ['tar', '-xzf', self.remote_root + '/runtime.tar.gz', '-C', self.remote_root])
            return self.call(host, ['sha256sum', self.remote_root + '/bin/yerbasd']).stdout.split()[0]
        with ThreadPoolExecutor(max_workers=5) as pool:
            hashes = list(pool.map(stage, self.hosts))
        if len(set(hashes)) != 1:
            raise RuntimeError('Daemon hashes differ across hosts')
        for host in self.hosts:
            for source in self.addresses.values():
                rule = ['allow', 'from', source, 'to', 'any', 'port', '22000:22024', 'proto', 'tcp', 'comment', self.tag]
                added = self.call(host, ['ufw', *rule]).stdout
                if 'Skipping' not in added:
                    self.firewall_rules.append((host, rule))
        (self.root / 'remote-capacity.json').write_text(json.dumps({'hosts':self.capacity,'daemonSha256':hashes[0]},indent=2)+'\n')

    def identity_service(self, index):
        host = self.hosts[1 + index // 25]
        return self.addresses[host] + ':' + str(22000 + index % 25)

    def node(self, name, binary, identity=None, index=None, **kwargs):
        host = self.hosts[0] if index is None else self.hosts[1 + index // 25]
        node = RemoteNode(self, host, name, binary, identity, **kwargs)
        self.created.append(node)
        return node

    def cleanup(self):
        errors = []
        for node in self.created:
            try: node.stop()
            except Exception: errors.append(node.name)
        for host, rule in reversed(self.firewall_rules):
            try: self.call(host, ['ufw', '--force', 'delete', *rule])
            except Exception: errors.append(host + ': firewall cleanup')
        self.firewall_rules.clear()
        (self.root / 'remote-cleanup.json').write_text(json.dumps({'stopFailures':errors,'runtimeLimitSecondsRemaining':max(0,int(self.deadline-time.monotonic()))},indent=2)+'\n')
        for host in self.hosts:
            self.run(self.ssh + ['-O', 'exit', host], check=False, timeout=15)
        self.control_dir.cleanup()
        if errors:
            raise RuntimeError('Explicit stop failed for ' + ', '.join(errors) + '; remote runtime deadlines remain active')


class RemoteNode(Node):
    def __init__(self, fleet, host, name, binary, identity, **kwargs):
        # Base Node requires loopback identities, so initialize the local staging
        # directory first and then assign the authorized public service identity.
        super().__init__(fleet.root, name, binary, None, **kwargs)
        self.fleet, self.host, self.name = fleet, host, name
        self.identity = identity
        self.port = int(identity['service'].split(':')[1]) if identity else 22000
        self.rpcport = 23000 + self.port - 22000
        self.remote_data = fleet.remote_root + '/' + name
        self.unit = fleet.tag + '-' + name
        self.launched = False

    def rpc(self, method, *args):
        self.fleet.remaining()
        values = [json.dumps(v, separators=(',', ':')) if isinstance(v, (bool, dict, list)) else str(v) for v in args]
        result = self.fleet.call(self.host, ['env', 'LD_LIBRARY_PATH=' + self.fleet.remote_root + '/lib',
                    self.fleet.remote_root + '/bin/yerbas-cli', '-regtest', '-datadir=' + self.remote_data,
                    method, *values]).stdout.strip()
        try: return json.loads(result)
        except ValueError: return result

    def start(self):
        config = (f'regtest=1\nlisten=1\nport={self.port}\nbind=0.0.0.0:{self.port}\n'
                  f'rpcbind=127.0.0.1\nrpcallowip=127.0.0.1\nrpcport={self.rpcport}\n'
                  'dnsseed=0\ndiscover=0\nupnp=0\npersistmempool=0\nprinttoconsole=0\n'
                  f'walletbroadcast={int(self.wallet_broadcast)}\ndbcache=16\npar=1\nmaxconnections={self.maxconnections}\n'
                  'poseactivationheight=600\nrecoveryactivationheight=600\n')
        if self.identity:
            config += f"externalip={self.identity['service']}\nsmartnodeblsprivkey={self.identity['key']}\n"
        config += self.extra_config
        conf = self.data / 'yerbas.conf'; conf.touch(mode=0o600); conf.write_text(config)
        archive = self.data.with_suffix('.tar.gz')
        archive.touch(mode=0o600)
        with tarfile.open(archive, 'w:gz') as output:
            output.add(self.data, arcname=self.name)
        self.fleet.upload(self.host, archive, self.fleet.remote_root + '/' + archive.name)
        self.fleet.call(self.host, ['tar', '-xzf', self.fleet.remote_root + '/' + archive.name, '-C', self.fleet.remote_root])
        self.fleet.call(self.host, ['rm', self.fleet.remote_root + '/' + archive.name])
        archive.unlink()
        left = self.fleet.remaining()
        self.launched = True # Include ambiguous SSH launch failures in cleanup.
        self.fleet.call(self.host, ['systemd-run', '--unit=' + self.unit,
            '--property=RuntimeMaxSec=' + str(left), '--property=TimeoutStopSec=30', '--property=KillMode=mixed',
            '--property=IPAddressDeny=any', '--property=IPAddressAllow=127.0.0.0/8 ' + ' '.join(self.fleet.addresses.values()),
            '--setenv=LD_LIBRARY_PATH=' + self.fleet.remote_root + '/lib',
            self.fleet.remote_root + '/bin/yerbasd', '-datadir=' + self.remote_data])
        def ready():
            try: self.rpc('getblockcount'); return True
            except RuntimeError: return False
        wait_for(ready, timeout=180)
        if self.identity:
            wait_for(lambda: self.rpc('smartnode', 'status').get('proTxHash') == self.identity['proTxHash'], timeout=180)

    def connect(self, coordinator):
        self.rpc('addnode', self.fleet.addresses[coordinator.host] + ':' + str(coordinator.port), 'onetry')

    def stop(self):
        if not self.launched: return
        self.fleet.call(self.host, ['systemctl', 'stop', self.unit], timeout=60)
        state = self.fleet.call(self.host, ['systemctl', 'is-active', self.unit], check=False).stdout.strip()
        if state not in ('inactive', 'failed', 'unknown'):
            raise RuntimeError(self.name + ': remote daemon did not stop')
        # Scrub generated operator secrets from the deployed configuration.
        self.fleet.call(self.host, ['python3', '-c', 'from pathlib import Path;Path(' + repr(self.remote_data + '/yerbas.conf') + ').write_text("regtest=1\\nlisten=0\\nconnect=0\\n")'])
        self.launched = False
