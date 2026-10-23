#!/usr/bin/env python3
"""Run 15 simultaneous RC identities, partition and fork checks on localhost.

Inputs are the matching blocks and generated keys from recovery_consensus_lifecycle.
This exercises real P2P/RPC but uses constructed starting quorum history, not DKG.
Never publish the generated keys or reuse them on a public network.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
from pathlib import Path
import shutil
import socket
import subprocess
import time


_allocated_ports = set()


def free_port():
    # Keep process-local allocations distinct even before daemons bind them.
    while True:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        if port not in _allocated_ports:
            _allocated_ports.add(port)
            return port


def wait_for(predicate, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.25)
    raise AssertionError('Timed out waiting for network condition')


class Node:
    def __init__(self, root, name, binary, identity=None, extra_config="", maxconnections=32, wallet_broadcast=False, smartnode_connections=False):
        self.data = root / name
        self.data.mkdir()
        self.binary = binary
        self.identity = identity
        self.extra_config = extra_config
        self.smartnode_connections = smartnode_connections
        self.wallet_broadcast = wallet_broadcast
        self.maxconnections = maxconnections
        self.rpcport = free_port()
        self.port = int(identity['service'].split(':')[1]) if identity else free_port()
        if identity:
            assert identity['service'] == f'127.0.0.1:{self.port}', 'Requires loopback fixture'
        self.process = None

    def rpc(self, method, *args):
        cookie = (self.data / 'regtest' / '.cookie').read_text().strip()
        conn = http.client.HTTPConnection('127.0.0.1', self.rpcport, timeout=180)
        try:
            conn.request('POST', '/', json.dumps({'id': 1, 'method': method, 'params': list(args)}),
                         {'Authorization': 'Basic ' + base64.b64encode(cookie.encode()).decode(),
                          'Content-Type': 'application/json'})
            result = json.loads(conn.getresponse().read())
        finally:
            conn.close()
        if result.get('error'):
            raise RuntimeError(result['error'])
        return result['result']

    def start(self):
        config = (f'regtest=1\nlisten=1\nport={self.port}\nbind=127.0.0.1:{self.port}\n'
                  f'rpcport={self.rpcport}\nconnect=0\ndnsseed=0\ndiscover=0\nupnp=0\n'
                  f'persistmempool=0\nwalletbroadcast={int(self.wallet_broadcast)}\nprinttoconsole=0\n'
                  f'dbcache=16\nmaxconnections={self.maxconnections}\npar=1\n'
                  'poseactivationheight=600\nrecoveryactivationheight=600\n')
        if self.identity:
            config += (f"externalip={self.identity['service']}\n"
                       f"smartnodeblsprivkey={self.identity['key']}\n")
        if self.smartnode_connections:
            config = config.replace("connect=0\n", "")
        config += self.extra_config
        conf = self.data / 'yerbas.conf'
        conf.touch(mode=0o600)
        conf.write_text(config)
        with (self.data / 'console.log').open('a') as out:
            self.process = subprocess.Popen([str(self.binary), f'-datadir={self.data}'], stdout=out, stderr=out)

        def ready():
            if self.process.poll() is not None:
                raise RuntimeError(f'Daemon exited; inspect {self.data}/console.log locally')
            try:
                self.rpc('getblockcount')
                return True
            except (OSError, RuntimeError):
                return False
        wait_for(ready)
        if self.identity:
            wait_for(lambda: self.rpc('smartnode', 'status').get('proTxHash') == self.identity['proTxHash'])

    def stop(self):
        if self.process and self.process.poll() is None:
            try:
                self.rpc('stop')
            except Exception:
                self.process.terminate()
            try:
                self.process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process = None

    def connect(self, coordinator):
        self.rpc('addnode', f'127.0.0.1:{coordinator.port}', 'onetry')


def rejects(node, fragment, method, *args):
    try:
        node.rpc(method, *args)
    except RuntimeError as error:
        assert fragment in str(error), str(error)
    else:
        raise AssertionError('Invalid request accepted')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bin-dir', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--keys', type=Path, required=True)
    parser.add_argument('--workdir', type=Path, required=True)
    args = parser.parse_args()
    root = args.workdir.resolve()
    root.mkdir(parents=True, exist_ok=False)
    root.chmod(0o700)
    secrets = json.loads(args.keys.read_text())
    for identity in secrets['signers']:
        _allocated_ports.add(int(identity['service'].split(':')[1]))
    lines = args.fixture.read_text().splitlines()
    expected, blocks = json.loads(lines[0]), lines[1:]
    assert len(blocks) == 1540 and len(secrets['signers']) == 15
    binary = (args.bin_dir / 'yerbasd').resolve()
    # The expiry scenario intentionally mines and discards a longer local branch.
    coordinator = Node(root, 'coordinator', binary, extra_config='disablesafemode=1\n')
    nodes = [coordinator]
    results = []

    def record(case):
        results.append({'case': case, 'passed': True})
        print(case, flush=True)

    def sync(members):
        tip = coordinator.rpc('getbestblockhash')
        wait_for(lambda: all(n.rpc('getbestblockhash') == tip for n in members))

    try:
        coordinator.start()
        for height, block in enumerate(blocks[:1539], 1):
            assert coordinator.rpc('submitblock', block) is None, height
        assert coordinator.rpc('recovery', 'status')['canAuthorize']
        coordinator.stop()
        signers = []
        for i, identity in enumerate(secrets['signers']):
            node = Node(root, f'signer{i}', binary, identity)
            nodes.append(node)
            signers.append(node)
            shutil.copytree(coordinator.data / 'regtest', node.data / 'regtest',
                            ignore=shutil.ignore_patterns('wallet.dat', '.cookie', '.lock',
                                                         'debug.log', 'db.log', '*.pid', 'peers.dat', 'mempool.dat'))
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda n: n.start(), nodes))
        for node in signers:
            node.connect(coordinator)
        wait_for(lambda: all(n.rpc('getconnectioncount') > 0 for n in signers))
        sync(signers)
        assert all(n.rpc('recovery', 'status')['committeeHash'] == expected['committee'] for n in nodes)
        record('15 simultaneous active smartnodes agree on roster and tip over localhost P2P')

        # Actual process outages: only ten signers can supply fresh approvals.
        stopped = signers[10:]
        for node in stopped:
            node.stop()
            assert node.process is None and not (node.data / 'regtest' / '.cookie').exists()
        request = coordinator.rpc('recovery', 'request', expected['target'], '1519', '1539')
        certificate = request
        for node in signers[:10]:
            certificate = coordinator.rpc('recovery', 'merge', certificate,
                                          node.rpc('recovery', 'sign', request))
        rejects(coordinator, 'bad-recovery-signatures', 'recovery', 'maketx', certificate)
        assert coordinator.rpc('recovery', 'status')['consumed'] == 0
        record('five stopped RC processes leave ten fresh approvals and cannot authorize a penalty')
        stopped[0].start()
        stopped[0].connect(coordinator)
        sync([stopped[0]])
        certificate = coordinator.rpc('recovery', 'merge', certificate,
                                      stopped[0].rpc('recovery', 'sign', request))
        assert coordinator.rpc('recovery', 'maketx', certificate)
        record('restarting one RC process restores the eleven-signature authorization threshold')
        stopped[0].stop()
        assert coordinator.rpc('recovery', 'maketx', certificate)
        for node in signers[:10]:
            node.rpc('setnetworkactive', False)
        wait_for(lambda: all(n.rpc('getconnectioncount') == 0 for n in signers[:10]))
        coordinator.rpc('generatetoaddress', 30, coordinator.rpc('getnewaddress'))
        rejects(coordinator, 'bad-recovery-window', 'recovery', 'maketx', certificate)
        record('previously collected approvals survive a signer outage but expire at the certificate deadline')
        # Return to the shared fixture tip before running the independent partition scenario.
        coordinator.rpc('invalidateblock', coordinator.rpc('getblockhash', 1540))
        assert coordinator.rpc('getblockcount') == 1539
        for node in stopped:
            node.start()
            node.connect(coordinator)
        for node in signers[:10]:
            node.rpc('setnetworkactive', True)
            node.connect(coordinator)
        sync(signers)

        online, isolated = signers[:8], signers[8:]
        for node in isolated:
            node.rpc('setnetworkactive', False)
        wait_for(lambda: all(n.rpc('getconnectioncount') == 0 for n in isolated))
        address = coordinator.rpc('getnewaddress')
        coordinator.rpc('generatetoaddress', 1, address)
        sync(online)
        request = coordinator.rpc('recovery', 'request', expected['target'], '1519', '1540')
        with ThreadPoolExecutor(max_workers=8) as pool:
            parts = list(pool.map(lambda n: n.rpc('recovery', 'sign', request), online))
        certificate = request
        for part in parts:
            certificate = coordinator.rpc('recovery', 'merge', certificate, part)
        rejects(coordinator, 'bad-recovery-signatures', 'recovery', 'maketx', certificate)
        for node in isolated:
            assert node.rpc('getblockcount') == 1539
            rejects(node, 'bad-recovery-window', 'recovery', 'sign', request)
        assert all(n.rpc('recovery', 'status')['consumed'] == 0 for n in nodes)
        record('8/7 partition leaves eight current approvals; lagging signers refuse and no penalty applies')

        fork_node = isolated[-1]
        fork_node.rpc('generatetoaddress', 1, coordinator.rpc('getnewaddress'))
        assert fork_node.rpc('getbestblockhash') != coordinator.rpc('getbestblockhash')
        rejects(fork_node, 'bad-recovery-branch', 'recovery', 'sign', request)
        record('same-height competing branch refuses the observation certificate')

        for node in isolated[:3]:
            node.rpc('setnetworkactive', True)
            node.connect(coordinator)
        current = online + isolated[:3]
        sync(current)
        for node in isolated[:3]:
            part = node.rpc('recovery', 'sign', request)
            certificate = coordinator.rpc('recovery', 'merge', certificate, part)
        raw = coordinator.rpc('recovery', 'maketx', certificate)
        coordinator.rpc('importprivkey', secrets['fundingKey'], 'regtest-fixture', True)
        funded = coordinator.rpc('fundrawtransaction', raw)
        signed = coordinator.rpc('signrawtransaction', funded['hex'])
        assert signed['complete']
        txid = coordinator.rpc('sendrawtransaction', signed['hex'])
        mined = coordinator.rpc('generatetoaddress', 1, address)[0]
        assert txid in coordinator.rpc('getblock', mined)['tx']
        sync(current)
        assert all(n.rpc('recovery', 'status')['consumed'] == 1 for n in current)
        record('reconnecting three signers yields eleven approvals and a propagated mined penalty')

        for node in isolated[3:]:
            node.rpc('setnetworkactive', True)
            node.connect(coordinator)
        sync(signers)
        for node in nodes:
            assert node.rpc('recovery', 'status')['consumed'] == 1
            assert node.rpc('protx', 'info', expected['target'])['state']['PoSePenalty'] == expected['penalty']
        record('all 15 signers converge after reconnection, including the competing branch')
    finally:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda n: n.stop(), nodes))
        for node in nodes:
            (node.data / 'yerbas.conf').write_text('regtest=1\nlisten=0\nconnect=0\n')
        (root / 'rc-network-results.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
