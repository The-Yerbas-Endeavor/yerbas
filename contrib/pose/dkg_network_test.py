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
from recovery_network_test import Node, free_port, wait_for, _allocated_ports

# Public regtest-only spork key already used by the functional test framework.
REGTEST_SPORK_KEY = 'cP4EKFyJsHT39LDqgdcB43Y3YXjNyjb5Fuas1GQSeAtjnZWmZEQK'


def disable_and_drain(nodes, diagnostics_path):
    """Close late outbound connections as well as the initial socket snapshot.

    OpenNetworkConnection checks network-active before ConnectNode; a connection
    already in flight can be inserted after SetNetworkActive closes its snapshot.
    Explicit disconnects here are a test-harness workaround, not a Core fix.
    """
    for node in nodes:
        node.rpc('setnetworkactive', False)
    observations = {}
    def drained():
        empty = True
        for node in nodes:
            assert not node.rpc('getnetworkinfo')['networkactive']
            peers = node.rpc('getpeerinfo')
            observations[node.data.name] = [p['id'] for p in peers]
            for peer in peers:
                empty = False
                try:
                    node.rpc('disconnectnode', '', peer['id'])
                except RuntimeError:
                    # The socket handler may have removed this peer meanwhile.
                    if any(p['id'] == peer['id'] for p in node.rpc('getpeerinfo')):
                        raise
            if node.rpc('getconnectioncount') != 0:
                empty = False
        return empty
    try:
        wait_for(drained, timeout=180)
    except Exception:
        diagnostics_path.write_text(json.dumps(observations, indent=2)+'\n')
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bin-dir', type=Path, required=True)
    parser.add_argument('--workdir', type=Path, required=True)
    parser.add_argument('--bootstrap-from', type=Path, help='Stopped local campaign with private resume-identities.json')
    parser.add_argument('--interrupt-recovery', action='store_true', help='Insert a real failed DKG between recovery successes')
    parser.add_argument('--resume-after-penalty', action='store_true', help='Reuse a completed local real-DKG campaign, rewound before session 1620')
    parser.add_argument('--remote-hosts', nargs=5, help='Coordinator then four 25-smartnode SSH hosts')
    parser.add_argument('--runtime', type=Path, help='Self-contained runtime archive for remote hosts')
    parser.add_argument('--max-seconds', type=int, default=43200, help='Remote hard limit, at most 12 hours')
    args = parser.parse_args()
    if args.remote_hosts and (not args.runtime or (args.bootstrap_from and not args.resume_after_penalty)):
        parser.error('Remote mode requires --runtime; bootstrap reuse requires --resume-after-penalty')
    if args.resume_after_penalty and not (args.bootstrap_from and args.interrupt_recovery):
        parser.error('--resume-after-penalty requires --bootstrap-from and --interrupt-recovery')
    root = args.workdir.resolve()
    root.mkdir(parents=True, exist_ok=False)
    root.chmod(0o700)
    if args.bootstrap_from:
        for identity in json.loads((args.bootstrap_from / 'resume-identities.json').read_text()):
            _allocated_ports.add(int(identity['service'].split(':')[1]))
    fleet = None
    if args.remote_hosts:
        from remote_fleet import RemoteFleet
        fleet = RemoteFleet(root, args.remote_hosts, args.runtime, args.max_seconds)
        try:
            fleet.prepare()
        except Exception:
            fleet.cleanup()
            raise
    binary = (args.bin_dir / 'yerbasd').resolve()
    # Intentional rewind retains a known longer discarded branch in the copied DB.
    # Bypass only its RPC safe-mode gate; synchronization and consensus still apply.
    resume_config = 'disablesafemode=1\n' if args.resume_after_penalty else ''
    coordinator = Node(root, 'coordinator', binary,
                       extra_config=f'sporkkey={REGTEST_SPORK_KEY}\n' + resume_config, maxconnections=160, wallet_broadcast=True, smartnode_connections=True)
    nodes = [coordinator]
    results = []
    active = nodes
    offline = []
    quorum_hash = None
    snapshots = []

    def record(case):
        results.append({'case': case, 'passed': True})
        print(case, flush=True)

    def sync():
        tip = coordinator.rpc('getbestblockhash')
        wait_for(lambda: all(n.rpc('getbestblockhash') == tip for n in active), timeout=180)

    def sessions():
        return [n.rpc('quorum', 'dkgstatus')['session'].get('llmq_100_67', {}) for n in active if n is not coordinator]

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
        print(f'DKG phase {number}: all {len(active)-1} online participants ready' + (f', {field}>={minimum}' if field else ''), flush=True)

    def mine_to(height):
        count = height - coordinator.rpc('getblockcount')
        assert count >= 0
        if count:
            coordinator.rpc('generatetoaddress', count, address)
            sync()

    def run_session(start, succeeds=True, split=False):
        nonlocal active, offline, quorum_hash
        mine_to(start - 1)
        mine_to(start)
        quorum_hash = coordinator.rpc('getbestblockhash')
        if split:
            roster = coordinator.rpc('recovery', 'status')
            assert roster['qualified'] == 100 and len(roster['members']) == 15
            members = {m['proTxHash'] for m in roster['members']}
            offline = [n for n in nodes[1:] if n.identity['proTxHash'] not in members][:21]
            assert len(offline) == 21
            disable_and_drain(offline, root / 'disconnect-diagnostics.json')
            active = [n for n in nodes if n not in offline]
            record('real participation history selects 15 RC members; 21 nonmembers isolated')
        phase(1)
        members = active[1].rpc('quorum', 'dkgstatus', 2)['session']['llmq_100_67']['allMembers']
        online_ids = {n.identity['proTxHash'] for n in active[1:]}
        assert online_ids <= set(members)
        missing_members = len(set(members) - online_ids)
        if not succeeds:
            # Other quorum types can PoSe-ban isolated nodes between sessions.
            # Such identities are absent from this session, not bad members of it.
            assert len(online_ids) < 80 and missing_members > 0
        print(f'Session {start}: selected={len(members)}, online={len(online_ids)}, missing={missing_members}', flush=True)
        required = {}
        for node in active[1:]:
            i = members.index(node.identity['proTxHash'])
            required[node] = {members[(i+gap) % len(members)] for gap in (1,2,4,8,16,32)} & online_ids
        def connected():
            return all(required[n] <= {p.get('verified_proregtx_hash') for p in n.rpc('getpeerinfo')} for n in active[1:])
        try:
            wait_for(connected, timeout=180)
        except Exception:
            diagnostics = []
            for node in active[1:]:
                peers = node.rpc('getpeerinfo')
                authenticated = {p.get('verified_proregtx_hash') for p in peers}
                diagnostics.append({'node': node.data.name,
                    'missing': sorted(required[node] - authenticated),
                    'peerCount': len(peers),
                    'authenticatedCount': len(authenticated - {None}),
                    'smartnodeStatus': node.rpc('smartnode', 'status'),
                    'syncStatus': node.rpc('mnsync', 'status')})
            (root / 'connection-diagnostics.json').write_text(json.dumps(diagnostics, indent=2)+'\n')
            raise
        print('Authenticated quorum connections ready', flush=True)
        for number, field, count in [(2, 'receivedContributions', len(active)-1),
                                      (3, 'receivedComplaints' if not succeeds else None, len(active)-1),
                                      (4, None, 0), (5, 'receivedPrematureCommitments' if succeeds else 'badMembers', 100 if succeeds else missing_members),
                                      (6, None, 0)]:
            coordinator.rpc('generatetoaddress', 2, address)
            sync()
            phase(number, field, count)
        if succeeds:
            def final_commitment_ready():
                qc = coordinator.rpc('quorum', 'dkgstatus')['minableCommitments'].get('llmq_100_67', {})
                return qc.get('quorumHash') == quorum_hash and qc.get('validMembersCount') == 100 and qc.get('signersCount') == 100
            wait_for(final_commitment_ready, timeout=240)
            coordinator.rpc('generatetoaddress', 1, address)
            sync()
            info = coordinator.rpc('quorum', 'info', 4, quorum_hash)
            assert len(info['members']) == 100 and sum(m['valid'] for m in info['members']) == 100
            assert all(quorum_hash in n.rpc('quorum', 'list').get('llmq_100_67', []) for n in active)
            (root / f'quorum-{start}.json').write_text(json.dumps(info, indent=2)+'\n')
        mine_to(start + 18)
        if not succeeds:
            assert all(quorum_hash not in n.rpc('quorum', 'list').get('llmq_100_67', []) for n in active)
        status = coordinator.rpc('recovery', 'status')
        snapshots.append({'session': start, 'succeeded': succeeds, 'status': status})
        print(f'Session {start}: success={succeeds}, RC={status["mode"]}, failures={status["failures"]}, successes={status["successes"]}', flush=True)
        return status

    def reconnect_and_revive():
        nonlocal active
        for node in offline:
            node.rpc('setnetworkactive', True)
            node.connect(coordinator)
        active = nodes
        sync()
        revived = []
        for node in offline:
            identity = node.identity
            info = coordinator.rpc('protx', 'info', identity['proTxHash'])
            if info['state']['PoSeBanHeight'] != -1:
                coordinator.rpc('protx', 'update_service', identity['proTxHash'],
                                identity['service'], identity['key'], '', address)
                revived.append(identity['proTxHash'])
        if revived:
            coordinator.rpc('generatetoaddress', 1, address)
            sync()
            assert all(coordinator.rpc('protx', 'info', i)['state']['PoSeBanHeight'] == -1 for i in revived)
            record(f'{len(revived)} isolated banned smartnodes revived through mined service updates')
        assert len(coordinator.rpc('protx', 'list', 'valid')) == 100
        for node in nodes:
            for _ in range(10):
                if node.rpc('mnsync', 'status')['IsSynced']: break
                node.rpc('mnsync', 'next')
            assert node.rpc('mnsync', 'status')['IsSynced']
        # Catch-up and revival may have happened after the first version/MNAUTH
        # exchange. Establish fresh handshakes only after identity and sync are ready.
        for node in offline:
            wait_for(lambda n=node: n.rpc('smartnode', 'status').get('proTxHash') == n.identity['proTxHash'])
        disable_and_drain(offline, root / 'disconnect-diagnostics.json')
        for node in offline:
            node.rpc('setnetworkactive', True)
            node.connect(coordinator)
        sync()

    try:
        if args.bootstrap_from:
            source = args.bootstrap_from.resolve()
            shutil.copytree(source / 'coordinator' / 'regtest', coordinator.data / 'regtest',
                            ignore=shutil.ignore_patterns('.cookie', '.lock', 'debug.log', 'db.log', '*.pid', 'peers.dat', 'mempool.dat'))
            coordinator.start()
            rewind = 1620 if args.resume_after_penalty else 1200
            if coordinator.rpc('getblockcount') >= rewind:
                coordinator.rpc('invalidateblock', coordinator.rpc('getblockhash', rewind))
            assert coordinator.rpc('getblockcount') == rewind - 1
            if args.resume_after_penalty:
                resumed = coordinator.rpc('recovery', 'status')
                assert resumed['mode'] == 'recovery' and resumed['consumed'] == 1 and resumed['successes'] == 0
            address = coordinator.rpc('getnewaddress')
            identities = json.loads((source / 'resume-identities.json').read_text())
            if fleet:
                assert len(identities) == 100
                assert all(identity['service'] == fleet.identity_service(i) for i, identity in enumerate(identities)), 'Resume identities must match the authorized fleet addresses'
            registered = coordinator.rpc('protx', 'list', 'valid', True)
            by_service = {entry['state']['service']: entry['proTxHash'] for entry in registered}
            for identity in identities:
                identity['proTxHash'] = by_service[identity['service']]
        else:
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
                service = fleet.identity_service(i) if fleet else f'127.0.0.1:{port}'
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
        bootstrap_chain = coordinator.data / 'regtest'
        if fleet:
            coordinator = fleet.node('remote-coordinator', binary, extra_config=f'sporkkey={REGTEST_SPORK_KEY}\n' + resume_config, maxconnections=160, wallet_broadcast=True, smartnode_connections=True)
            shutil.copytree(bootstrap_chain, coordinator.data / 'regtest', ignore=shutil.ignore_patterns('.cookie', '.lock', 'debug.log', 'db.log', '*.pid', 'peers.dat', 'mempool.dat'))
            nodes[0] = coordinator
        private_metadata = root / 'resume-identities.json'
        private_metadata.touch(mode=0o600)
        private_metadata.write_text(json.dumps(identities))
        for i, identity in enumerate(identities):
            node = (fleet.node(f'smartnode{i}', binary, identity, index=i, extra_config=resume_config, smartnode_connections=True) if fleet else
                    Node(root, f'smartnode{i}', binary, identity, extra_config=resume_config, smartnode_connections=True))
            nodes.append(node)
            shutil.copytree(coordinator.data / 'regtest', node.data / 'regtest',
                            ignore=shutil.ignore_patterns('wallet.dat', '.cookie', '.lock',
                                                         'debug.log', 'db.log', '*.pid', 'peers.dat', 'mempool.dat'))
        record('reused real-DKG chain and mined penalty, rewound before recovery sessions' if args.resume_after_penalty else '100 registrations created and confirmed from genesis without constructed commitments')
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
        if not args.resume_after_penalty:
            for height in (1200, 1260, 1320, 1380):
                run_session(height)
            record('four real successful DKG sessions establish consistent on-chain participation')
            for i, height in enumerate((1440, 1500, 1560), 1):
                state = run_session(height, succeeds=False, split=(i == 1))
                assert state['failures'] == i
                assert state['mode'] == ('recovery' if i == 3 else 'normal')
            assert state['canAuthorize'] and state['eligibleSigners'] == 15
            record('three real failed sessions activate the selected 11-of-15 RC')
            trigger = state['triggerHeight']
            mine_to(trigger + 21)
            candidates = [(n, coordinator.rpc('protx', 'info', n.identity['proTxHash'])) for n in offline]
            target = min(((n, info) for n, info in candidates if info['state']['PoSeBanHeight'] == -1),
                         key=lambda pair: pair[1]['state']['PoSePenalty'])[0]
            target_id = target.identity['proTxHash']
            request = coordinator.rpc('recovery', 'request', target_id, str(trigger+1), str(trigger+21))
            roster_ids = {m['proTxHash'] for m in state['members']}
            signers = [n for n in active[1:] if n.identity['proTxHash'] in roster_ids][:11]
            assert len(signers) == 11
            certificate = request
            for node in signers:
                certificate = coordinator.rpc('recovery', 'merge', certificate, node.rpc('recovery', 'sign', request))
            raw = coordinator.rpc('recovery', 'maketx', certificate)
            funded = coordinator.rpc('fundrawtransaction', raw)
            signed = coordinator.rpc('signrawtransaction', funded['hex'])
            assert signed['complete']
            old_penalty = coordinator.rpc('protx', 'info', target_id)['state']['PoSePenalty']
            txid = coordinator.rpc('sendrawtransaction', signed['hex'])
            block = coordinator.rpc('generatetoaddress', 1, address)[0]
            sync()
            assert txid in coordinator.rpc('getblock', block)['tx']
            assert all(n.rpc('recovery', 'status')['consumed'] == 1 for n in active)
            assert coordinator.rpc('protx', 'info', target_id)['state']['PoSePenalty'] > old_penalty
            record('11 selected active signers authorize a mined RC penalty after the real failures')
            reconnect_and_revive()
        state = run_session(1620)
        assert state['mode'] == 'recovery' and state['successes'] == 1
        if args.interrupt_recovery:
            state = run_session(1680, succeeds=False, split=True)
            assert state['mode'] == 'recovery' and state['successes'] == 0
            assert state['consumed'] == 1
            record('a real failed DKG between successes resets restoration progress and preserves the penalty')
            reconnect_and_revive()
            state = run_session(1740)
            assert state['mode'] == 'recovery' and state['successes'] == 1
            assert all(n.rpc('recovery', 'status')['mode'] == 'recovery' for n in nodes)
            record('the first fresh success after interruption does not restore normal mode')
            state = run_session(1800)
        else:
            state = run_session(1680)
        assert state['mode'] == 'normal'
        assert all(n.rpc('recovery', 'status')['mode'] == 'normal' for n in nodes)
        record('two real successful sessions restore normal operation on all 101 daemons')
    finally:
        stop_errors = []
        def stop_node(node):
            try:
                node.stop()
            except Exception as error:
                stop_errors.append({'node': node.data.name, 'error': str(error)})
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(stop_node, nodes))
        for node in nodes:
            (node.data / 'yerbas.conf').write_text('regtest=1\nlisten=0\nconnect=0\n')
        (root / 'rc-session-history.json').write_text(json.dumps(snapshots, indent=2)+'\n')
        (root / 'dkg-results.json').write_text(json.dumps(results, indent=2) + '\n')
        (root / 'stop-errors.json').write_text(json.dumps(stop_errors, indent=2) + '\n')
        if fleet:
            fleet.cleanup()
        elif stop_errors:
            raise RuntimeError('Some local daemons failed to stop; inspect stop-errors.json')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
