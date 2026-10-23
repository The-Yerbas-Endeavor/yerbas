#!/usr/bin/env python3
"""Collect public, read-only evidence from one local testnet daemon.

Run on each host through SSH; do not expose RPC to the Internet. This does not
sign, mine, change peers, or declare the deployment safe to release.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess


def collect(binary, datadir, label):
    def rpc(*command):
        result = subprocess.run([str(binary / 'yerbas-cli'), '-testnet',
                                 '-datadir=' + str(datadir), *command],
                                capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise RuntimeError('Read-only RPC failed: ' + command[0])
        return json.loads(result.stdout)

    for _ in range(3):
        chain = rpc('getblockchaininfo')
        if chain['chain'] != 'test':
            raise RuntimeError('Expected testnet')
        network = rpc('getnetworkinfo')
        pose = rpc('pose', 'status')
        recovery = rpc('recovery', 'status')
        registrations = rpc('protx', 'list', 'valid')
        quorums = rpc('quorum', 'list')
        end = rpc('getblockchaininfo')
        if chain['bestblockhash'] == end['bestblockhash']:
            break
    else:
        raise RuntimeError('Tip changed during all three collection attempts; retry')
    if (pose['activationHeight'], recovery['activationHeight'],
            recovery['committeeSize'], recovery['threshold']) != (4320, 8640, 15, 11):
        raise RuntimeError('Unexpected testnet activation or RC parameters')
    # Explicit allowlists exclude wallet state, configuration, cookies and peers.
    evidence = {
        'schema': 1, 'label': label,
        'collectedAt': datetime.now(timezone.utc).isoformat(),
        'chain': {k: chain[k] for k in ('chain', 'blocks', 'headers', 'bestblockhash')},
        'network': {k: network[k] for k in ('version', 'subversion', 'protocolversion', 'connections')},
        'pose': {k: pose[k] for k in ('active', 'quorumType', 'activationHeight')},
        'recovery': {k: recovery[k] for k in ('enabled', 'activationHeight', 'mode',
            'failures', 'successes', 'triggerHeight', 'epoch', 'budget', 'consumed',
            'committeeHash', 'committeeSize', 'threshold', 'qualified',
            'selectionHeight', 'snapshotHeight', 'eligibleSigners', 'canAuthorize', 'members')},
        'validRegistrations': len(registrations),
        'recent100_67Quorums': quorums.get('llmq_100_67', []),
        'limitations': 'One local observation; not proof of operator independence, reachability, or release readiness.',
    }
    with (binary / 'yerbasd').open('rb') as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    evidence['localDaemonFileSha256'] = digest.hexdigest()
    evidence['binaryNote'] = 'Hash of the local file, not an attestation of the running process or source commit.'
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bin-dir', type=Path, required=True)
    parser.add_argument('--datadir', type=Path, required=True)
    parser.add_argument('--label', required=True, help='Non-sensitive campaign node label')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    evidence = collect(args.bin_dir.resolve(), args.datadir.resolve(), args.label)
    with args.output.open('x') as output:
        json.dump(evidence, output, indent=2)
        output.write('\n')
    print('Saved testnet evidence to ' + str(args.output))


if __name__ == '__main__':
    main()
