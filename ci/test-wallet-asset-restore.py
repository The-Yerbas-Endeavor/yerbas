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
import urllib.parse


class RPCError(RuntimeError):
    def __init__(self, error):
        self.code = error['code']
        super().__init__(error['message'])


def wait_for(check, description, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.2)
    raise RuntimeError('Timed out: ' + description)


class Node:
    def __init__(self, binary, directory, extra_args=()):
        self.binary = binary
        self.directory = directory
        self.directory.mkdir(parents=True)
        self.ports = []
        for _ in range(2):
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                self.ports.append(sock.getsockname()[1])
        self.process = None
        self.extra_args = extra_args
        self.wallet = None
        self.mock_time = 1417713337

    def rpc(self, method, *params, _wallet=None, **named):
        if params and named:
            raise ValueError('Use positional or named RPC parameters, not both')
        body = json.dumps(dict(jsonrpc='1.0', id='restore-test', method=method, params=named or params)).encode()
        url = 'http://127.0.0.1:' + str(self.ports[0])
        wallet = self.wallet if _wallet is None else _wallet
        if wallet is not None:
            url += '/wallet/' + urllib.parse.quote(wallet, safe='')
        request = urllib.request.Request(url, body)
        request.add_header('Authorization', 'Basic ' + base64.b64encode(b'restore-test:isolated-test-only').decode())
        # Ignore desktop HTTP proxy settings for these loopback-only requests.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            response = opener.open(request, timeout=180 if method == 'generate' else 60)
        except urllib.error.HTTPError as exc:
            # JSON-RPC errors use HTTP 500; retain their code and message so
            # negative acceptance checks cannot mistake transport failure for rejection.
            response = exc
        with response:
            result = json.load(response)
        if result['error']:
            raise RPCError(result['error'])
        if method == 'setmocktime':
            self.mock_time = params[0]
        return result['result']

    def start(self, rescan=False):
        self.log = (self.directory / 'process.log').open('a')
        args = [str(self.binary), '-regtest', '-server', '-datadir=' + str(self.directory),
                '-rpcuser=restore-test', '-rpcpassword=isolated-test-only',
                '-rpcport=' + str(self.ports[0]), '-port=' + str(self.ports[1]),
                '-mocktime=' + str(self.mock_time), '-bind=127.0.0.1', '-connect=0', '-dnsseed=0', '-discover=0', '-upnp=0']
        if rescan:
            args.append('-rescan')
        args.extend(self.extra_args)
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


def run(binary, root):
    issuer = Node(binary, root / 'issuer')
    recipient = Node(binary, root / 'recipient')
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
        issuer.rpc('generate', 130)
        connect(recipient)
        sync(recipient)
        addresses = [recipient.rpc('getnewaddress') for _ in range(4)]
        backup = root / 'wallet-backup.dat'
        recipient.rpc('backupwallet', str(backup))
        assert backup.is_file()
        print('Backed up keys before receiving any coins or assets.', flush=True)
        confirm(issuer.rpc('sendtoaddress', addresses[0], 2))
        confirm(issuer.rpc('issue', asset, 100, '', '', 2, True)[0])
        confirm(issuer.rpc('issue', nft, 1, '', '', 0, False, True, cid)[0])
        confirm(issuer.rpc('transfer', asset, 12.34, addresses[1])[0])
        confirm(issuer.rpc('transfer', nft, 1, addresses[2])[0])
        confirm(issuer.rpc('transfer', asset + '!', 1, addresses[3])[0])
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
        for name, amount in [(asset, 12.34), (nft, 1), (asset + '!', 1)]:
            txid = restored.rpc('transfer', name, amount, issuer.rpc('getnewaddress'))[0]
            wait_for(lambda: txid in issuer.rpc('getrawmempool'), 'restored transfer relay')
            issuer.rpc('generate', 1)
            sync(restored)
            assert restored.rpc('gettransaction', txid)['confirmations'] > 0
        assert not balances(restored)
        assert balances(issuer) == {asset: 100, nft: 1, asset + '!': 1}
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
    args = parser.parse_args()
    if args.workdir:
        args.workdir.mkdir(parents=True, exist_ok=False)
        run(args.binary.resolve(), args.workdir.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix='yerbas-asset-restore-') as directory:
            run(args.binary.resolve(), Path(directory))
