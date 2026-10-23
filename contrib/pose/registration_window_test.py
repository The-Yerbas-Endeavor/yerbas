#!/usr/bin/env python3
"""Regression: first registration inside a legacy quorum mining window."""
import argparse
import json
from pathlib import Path
from recovery_network_test import Node, free_port

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--bin-dir', type=Path, required=True)
p.add_argument('--workdir', type=Path, required=True)
a = p.parse_args()
root = a.workdir.resolve()
root.mkdir(parents=True, exist_ok=False)
node = Node(root, 'node', (a.bin_dir / 'yerbasd').resolve(), wallet_broadcast=True)
results = []
try:
    node.start()
    address = node.rpc('getnewaddress')
    node.rpc('generatetoaddress', 400, address)
    key = node.rpc('bls', 'generate')
    owner = node.rpc('getnewaddress')
    txid = node.rpc('protx', 'register_fund', node.rpc('getnewaddress'), 10,
                    f'127.0.0.1:{free_port()}', owner, key['public'], owner, 0, address, address)
    block = node.rpc('generatetoaddress', 1, address)[0]
    assert node.rpc('getblockcount') == 401
    assert txid in node.rpc('getblock', block)['tx']
    node.rpc('invalidateblock', block)
    node.rpc('reconsiderblock', block)
    assert node.rpc('getbestblockhash') == block
    node.stop()
    node.start()
    assert node.rpc('getbestblockhash') == block
    assert node.rpc('protx', 'info', txid)['state']['registeredHeight'] == 401
    results.append({'case': 'first registration at height 401 mines, reconnects and survives restart', 'passed': True})
finally:
    node.stop()
    (root / 'registration-window-results.json').write_text(json.dumps(results, indent=2)+'\n')
print(json.dumps(results, indent=2))
