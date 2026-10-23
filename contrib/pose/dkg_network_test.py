#!/usr/bin/env python3
"""Fresh 100-smartnode localhost DKG campaign, with no constructed commitments.

Uses regtest collateral/difficulty overrides, preserving production 100/80/67.
Creates generated test secrets in private datadirs; never publish those datadirs.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import time
from recovery_network_test import Node, free_port, wait_for

# Public regtest-only spork key already used by the functional test framework.
REGTEST_SPORK_KEY = 'cP4EKFyJsHT39LDqgdcB43Y3YXjNyjb5Fuas1GQSeAtjnZWmZEQK'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bin-dir', type=Path, required=True)
    parser.add_argument('--workdir', type=Path, required=True)
    args = parser.parse_args()
    root = args.workdir.resolve()
    root.mkdir(parents=True, exist_ok=False)
    root.chmod(0o700)
    binary = (args.bin_dir / 'yerbasd').resolve()
    coordinator = Node(root, 'coordinator', binary,
                       extra_config=f'sporkkey={REGTEST_SPORK_KEY}\n', maxconnections=160, wallet_broadcast=True, smartnode_connections=True)
    nodes = [coordinator]
    results = []

    def record(case):
        results.append({'case': case, 'passed': True})
        print(case, flush=True)

    def sync():
        tip = coordinator.rpc('getbestblockhash')
        wait_for(lambda: all(n.rpc('getbestblockhash') == tip for n in nodes), timeout=180)

    def sessions():
        return [n.rpc('quorum', 'dkgstatus')['session'].get('llmq_100_67', {}) for n in nodes[1:]]

    def phase(number, field=None, minimum=0):
        def ready():
            states = sessions()
            return all(s.get('phase') == number and s.get('quorumHash') == quorum_hash
                       and (field is None or s.get(field, 0) >= minimum) for s in states)
        try:
            wait_for(ready, timeout=240)
        except Exception:
            (root / 'dkg-phase-diagnostics.json').write_text(json.dumps(sessions(), indent=2))
            raise
        print(f'DKG phase {number}: all 100 participants ready' + (f', {field}>={minimum}' if field else ''), flush=True)

    try:
        coordinator.start()
        address = coordinator.rpc('getnewaddress')
        coordinator.rpc('generatetoaddress', 420, address)
        funding = [coordinator.rpc('getnewaddress') for _ in range(100)]
        coordinator.rpc('sendmany', '', {a: 11 for a in funding})
        coordinator.rpc('generatetoaddress', 1, address)
        identities = []
        ports = set()
        for i in range(100):
            port = free_port()
            while port in ports or port == coordinator.port:
                port = free_port()
            ports.add(port)
            key = coordinator.rpc('bls', 'generate')
            owner = coordinator.rpc('getnewaddress')
            collateral = coordinator.rpc('getnewaddress')
            service = f'127.0.0.1:{port}'
            protx = coordinator.rpc('protx', 'register_fund', collateral, 10, service,
                                    owner, key['public'], owner, 0, address, funding[i])
            identities.append({'proTxHash': protx, 'key': key['secret'], 'service': service})
            if (i + 1) % 20 == 0:
                print(f'Registered {i + 1}/100 smartnodes through RPC', flush=True)
        # Register in one block outside legacy quorum commitment windows.
        coordinator.rpc('generatetoaddress', 1, address)
        coordinator.rpc('generatetoaddress', 1199 - coordinator.rpc('getblockcount'), address)
        assert len(coordinator.rpc('protx', 'list', 'valid')) == 100
        assert coordinator.rpc('quorum', 'list').get('llmq_100_67', []) == []
        assert coordinator.rpc('spork', 'SPORK_17_QUORUM_DKG_ENABLED', 0) == 'success'
        coordinator.stop()
        for i, identity in enumerate(identities):
            node = Node(root, f'smartnode{i}', binary, identity, smartnode_connections=True)
            nodes.append(node)
            shutil.copytree(coordinator.data / 'regtest', node.data / 'regtest',
                            ignore=shutil.ignore_patterns('wallet.dat', '.cookie', '.lock',
                                                         'debug.log', 'db.log', '*.pid', 'peers.dat', 'mempool.dat'))
        record('100 registrations created and confirmed from genesis without constructed commitments')
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda n: n.start(), nodes))
        for node in nodes:
            for _ in range(10):
                if node.rpc('mnsync', 'status')['IsSynced']:
                    break
                node.rpc('mnsync', 'next')
            assert node.rpc('mnsync', 'status')['IsSynced']
        for node in nodes[1:]:
            node.connect(coordinator)
        wait_for(lambda: all(n.rpc('getconnectioncount') > 0 for n in nodes[1:]), timeout=180)
        sync()
        assert all(n.rpc('spork', 'show')['SPORK_17_QUORUM_DKG_ENABLED'] == 0 for n in nodes)
        record('100 active smartnodes connected and DKG enabled')
        coordinator.rpc('generatetoaddress', 1, address)
        sync()
        quorum_hash = coordinator.rpc('getbestblockhash')
        phase(1)
        for number, field, count in [(2, 'receivedContributions', 100),
                                      (3, None, 0), (4, None, 0),
                                      (5, 'receivedPrematureCommitments', 100), (6, None, 0)]:
            coordinator.rpc('generatetoaddress', 2, address)
            sync()
            phase(number, field, count)
        wait_for(lambda: 'llmq_100_67' in coordinator.rpc('quorum', 'dkgstatus')['minableCommitments'], timeout=180)
        coordinator.rpc('generatetoaddress', 1, address)
        sync()
        info = coordinator.rpc('quorum', 'info', 4, quorum_hash)
        assert len(info['members']) == 100 and sum(m['valid'] for m in info['members']) >= 80
        assert all(quorum_hash in n.rpc('quorum', 'list').get('llmq_100_67', []) for n in nodes)
        record('real type-4 DKG commitment mined and accepted across all 101 daemons')
        (root / 'quorum-info.json').write_text(json.dumps(info, indent=2) + '\n')
    finally:
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda n: n.stop(), nodes))
        for node in nodes:
            (node.data / 'yerbas.conf').write_text('regtest=1\nlisten=0\nconnect=0\n')
        (root / 'dkg-results.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
