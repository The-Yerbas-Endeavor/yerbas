#!/usr/bin/env python3
"""Recover assets from a pre-receipt wallet.dat backup in a fresh regtest node.

Usage: python3 ci/test-wallet-asset-restore.py /path/to/yerbasd
Only temporary data directories and loopback peers are used.
"""
import argparse
import base64
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
import urllib.error


def wait_for(check, description, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.2)
    raise RuntimeError('Timed out: ' + description)


class Node:
    def __init__(self, binary, directory):
        self.binary = binary
        self.directory = directory
        self.directory.mkdir(parents=True)
        self.ports = []
        for _ in range(2):
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                self.ports.append(sock.getsockname()[1])
        self.process = None

    def rpc(self, method, *params):
        body = json.dumps(dict(jsonrpc='1.0', id='restore-test', method=method, params=params)).encode()
        request = urllib.request.Request('http://127.0.0.1:' + str(self.ports[0]), body)
        request.add_header('Authorization', 'Basic ' + base64.b64encode(b'restore-test:isolated-test-only').decode())
        # Ignore desktop HTTP proxy settings for these loopback-only requests.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            response = opener.open(request, timeout=600 if method == 'generate' else 30)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            result = json.load(response)
        if result['error']:
            raise RuntimeError(str(result['error']))
        return result['result']

    def start(self, rescan=False):
        self.log = (self.directory / 'process.log').open('a')
        args = [str(self.binary), '-regtest', '-server', '-datadir=' + str(self.directory),
                '-rpcuser=restore-test', '-rpcpassword=isolated-test-only',
                '-rpcport=' + str(self.ports[0]), '-port=' + str(self.ports[1]),
                '-mocktime=1417713337', '-bind=127.0.0.1', '-connect=0', '-dnsseed=0', '-discover=0', '-upnp=0']
        if rescan:
            args.append('-rescan')
        self.process = subprocess.Popen(args, stdout=self.log, stderr=self.log)
        def ready():
            if self.process.poll() is not None:
                raise RuntimeError('Node exited: ' + str(self.directory))
            try:
                self.rpc('getblockcount')
                return True
            except (OSError, RuntimeError):
                return False
        wait_for(ready, 'RPC ready')

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.rpc('stop')
            self.process.wait(timeout=30)
        if hasattr(self, 'log'):
            self.log.close()


def run(binary, root, encrypted=False, source_binary=None):
    issuer = Node(binary, root / 'issuer')
    recipient = Node(source_binary or binary, root / 'recipient')
    nodes = [issuer, recipient]
    asset, nft = 'RESTORETEST', 'RESTORETEST#ART001'
    cid = 'QmTqu3Lk3gmTsQVtjU7rYYM37EAW4xNmbuEAp2Mjr4AV7E'
    def connect(node):
        node.rpc('addnode', '127.0.0.1:' + str(issuer.ports[1]), 'onetry')
        issuer.rpc('addnode', '127.0.0.1:' + str(node.ports[1]), 'onetry')
        wait_for(lambda: any(p['version'] for p in node.rpc('getpeerinfo')), 'peer handshake')
    def sync(node):
        wait_for(lambda: node.rpc('getbestblockhash') == issuer.rpc('getbestblockhash'), 'chain synchronization')
    def confirm(txid):
        issuer.rpc('generate', 1)
        sync(nodes[-1])
        assert issuer.rpc('gettransaction', txid)['confirmations'] > 0
    def balances(node):
        return node.rpc('listmyassets', '*', False, 100, 0, 1)
    try:
        issuer.start()
        recipient.start()
        if encrypted:
            recipient.rpc('encryptwallet', 'public-regtest-passphrase')
            recipient.process.wait(timeout=30)
            recipient.log.close()
            recipient.start()
            recipient.rpc('walletpassphrase', 'public-regtest-passphrase', 600)
        # Mature enough rewards for two root issuance fees and a restricted issuance.
        issuer.rpc('generate', 170)
        connect(recipient)
        sync(recipient)
        addresses = [recipient.rpc('getnewaddress') for _ in range(4)]
        backup = root / 'wallet-backup.dat'
        recipient.rpc('backupwallet', str(backup))
        assert backup.is_file()
        if encrypted:
            recipient.rpc('walletlock')
        print('Backed up keys before receiving any coins or assets.', flush=True)
        confirm(issuer.rpc('sendtoaddress', addresses[0], 2))
        confirm(issuer.rpc('issue', asset, 100, '', '', 2, True)[0])
        confirm(issuer.rpc('issue', nft, 1, '', '', 0, False, True, cid)[0])
        confirm(issuer.rpc('transfer', asset, 12.34, addresses[1])[0])
        confirm(issuer.rpc('transfer', nft, 1, addresses[2])[0])
        confirm(issuer.rpc('transfer', asset + '!', 1, addresses[3])[0])
        # Restricted ownership must survive wallet-only recovery while frozen.
        confirm(issuer.rpc('issue', 'LOCKTEST', 1)[0])
        confirm(issuer.rpc('issuerestrictedasset', '$LOCKTEST', 5, 'true', addresses[1])[0])
        confirm(issuer.rpc('freezeaddress', '$LOCKTEST', addresses[1])[0])
        assert recipient.rpc('checkaddressrestriction', addresses[1], '$LOCKTEST')
        expected = {asset: 12.34, nft: 1, asset + '!': 1}
        assert balances(recipient) == expected
        recipient.stop()
        restored = Node(binary, root / 'restored')
        nodes.append(restored)
        wallet_dir = restored.directory / 'regtest'
        wallet_dir.mkdir()
        shutil.copy2(backup, wallet_dir / 'wallet.dat')
        assert list(wallet_dir.iterdir()) == [wallet_dir / 'wallet.dat']
        # No blocks, chainstate, assets database, or original wallet records copied.
        restored.start(rescan=True)
        connect(restored)
        sync(restored)
        wait_for(lambda: balances(restored) == expected, 'restored asset balances')
        assert restored.rpc('getassetdata', nft)['ipfs_hash'] == cid
        assert restored.rpc('getbalance') == 2
        print('Fresh node recovered coins, fractional assets, NFT metadata, and owner token.', flush=True)
        restored.stop()
        restored.start(rescan=True)
        connect(restored)
        assert balances(restored) == expected
        if encrypted:
            assert restored.rpc('getwalletinfo')['unlocked_until'] == 0
            try:
                restored.rpc('walletpassphrase', 'wrong-passphrase', 60)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Incorrect passphrase accepted')
            restored.rpc('walletpassphrase', 'public-regtest-passphrase', 600)
        assert restored.rpc('checkaddressrestriction', addresses[1], '$LOCKTEST')
        try:
            restored.rpc('transfer', '$LOCKTEST', 5, issuer.rpc('getnewaddress'))
        except RuntimeError:
            pass
        else:
            raise AssertionError('Frozen restricted asset was spendable')
        confirm(issuer.rpc('unfreezeaddress', '$LOCKTEST', addresses[1])[0])
        wait_for(lambda: balances(restored).get('$LOCKTEST') == 5, 'unfrozen restored balance')
        for name, amount in [(asset, 12.34), (nft, 1), (asset + '!', 1), ('$LOCKTEST', 5)]:
            txid = restored.rpc('transfer', name, amount, issuer.rpc('getnewaddress'))[0]
            wait_for(lambda: txid in issuer.rpc('getrawmempool'), 'restored transfer relay')
            issuer.rpc('generate', 1)
            sync(restored)
            assert restored.rpc('gettransaction', txid)['confirmations'] > 0
        assert not balances(restored)
        assert balances(issuer) == {asset: 100, nft: 1, asset + '!': 1, 'LOCKTEST': 1, 'LOCKTEST!': 1, '$LOCKTEST': 5}
        print('PASS: wallet.dat-only recovery and rescan; all recovered asset types transferred successfully.', flush=True)
    finally:
        shutdown_errors = []
        for node in reversed(nodes):
            try:
                node.stop()
            except Exception as exc:
                shutdown_errors.append(str(exc))
                if node.process is not None and node.process.poll() is None:
                    node.process.kill()
                    node.process.wait()
        if shutdown_errors:
            raise RuntimeError('Test node cleanup failed: ' + '; '.join(shutdown_errors))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--workdir', type=Path, help='New directory in which to retain test logs')
    parser.add_argument('--encrypted', action='store_true', help='Back up and restore an encrypted wallet')
    parser.add_argument('--source-binary', type=Path, help='Older daemon used to create the source wallet (upgrade regression)')
    args = parser.parse_args()
    if args.workdir:
        args.workdir.mkdir(parents=True, exist_ok=False)
        run(args.binary.resolve(), args.workdir.resolve(), args.encrypted, args.source_binary.resolve() if args.source_binary else None)
    else:
        with tempfile.TemporaryDirectory(prefix='yerbas-asset-restore-') as directory:
            run(args.binary.resolve(), Path(directory), args.encrypted, args.source_binary.resolve() if args.source_binary else None)
