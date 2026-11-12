#!/usr/bin/env python3
"""Local regtest asset lifecycle, restrictions, and chain rollback acceptance tests.

Usage: python3 ci/test-asset-acceptance.py /path/to/yerbasd --workdir NEW_DIRECTORY
No real wallets, public peers or external services are used.
"""
import argparse
import importlib.util
from pathlib import Path
import tempfile
import sys

spec = importlib.util.spec_from_file_location('restore', Path(__file__).with_name('test-wallet-asset-restore.py'))
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)


def run(binary, root):
    a, b = [restore.Node(binary, root / name, ('-assetindex=1', '-minrewardheight=1'))
            for name in ('issuer', 'recipient')]
    def sync():
        restore.wait_for(lambda: a.rpc('getbestblockhash') == b.rpc('getbestblockhash'), 'chain sync')
    def mine(count):
        blocks = []
        for _ in range(count):
            timestamp = max(1417713337, a.rpc('getblockheader', a.rpc('getbestblockhash'))['time'] + 601)
            for node in (a, b):
                node.rpc('setmocktime', timestamp)
            blocks.extend(a.rpc('generate', 1))
        return blocks
    def confirm(tx, sender=a, wallet=None):
        if isinstance(tx, list):
            tx = tx[0]
        restore.wait_for(lambda: tx in a.rpc('getrawmempool'), 'transaction relay')
        block = mine(1)[0]
        sync()
        assert sender.rpc('gettransaction', tx, _wallet=wallet)['confirmations'] > 0
        return block
    def balance(node, name):
        return node.rpc('listmyassets', '*', False, 100, 0, 1).get(name, 0)
    def reject(node, method, *args, contains):
        before = set(node.rpc('getrawmempool'))
        try:
            node.rpc(method, *args)
        except restore.RPCError as exc:
            assert contains.lower() in str(exc).lower(), (method, exc.code, str(exc))
        else:
            raise AssertionError('Expected rejection: ' + method)
        assert set(node.rpc('getrawmempool')) == before
    try:
        a.start()
        b.start()
        b.rpc('addnode', '127.0.0.1:' + str(a.ports[1]), 'onetry')
        restore.wait_for(lambda: any(p['version'] for p in b.rpc('getpeerinfo')), 'peer handshake')
        mine(220)
        sync()
        aa, bb = a.rpc('getnewaddress'), b.rpc('getnewaddress')
        confirm(a.rpc('sendtoaddress', bb, 100))
        confirm(a.rpc('issue', 'ACCEPTANCE', 100, aa, '', 2, True))
        confirm(a.rpc('transfer', 'ACCEPTANCE', 12.34, bb))
        assert balance(a, 'ACCEPTANCE') == 87.66
        assert balance(b, 'ACCEPTANCE') == 12.34
        confirm(a.rpc('reissue', 'ACCEPTANCE', 25, aa))
        assert a.rpc('getassetdata', 'ACCEPTANCE')['amount'] == 125
        confirm(a.rpc('transfer', 'ACCEPTANCE!', 1, bb))
        reject(a, 'reissue', 'ACCEPTANCE', 1, aa, contains="doesn't have asset")
        confirm(b.rpc('reissue', 'ACCEPTANCE', 5, bb), b)
        assert a.rpc('getassetdata', 'ACCEPTANCE')['amount'] == 130
        assert balance(b, 'ACCEPTANCE') == 17.34
        print('PASS: issue, fractional transfer, reissue, ownership handover and permission enforcement', flush=True)

        confirm(a.rpc('issue', 'RESTRICTTEST', 1))
        confirm(a.rpc('issuequalifierasset', '#QUALTEST', 1))
        for address in (aa, bb):
            confirm(a.rpc('addtagtoaddress', '#QUALTEST', address))
        confirm(a.rpc('issuerestrictedasset', '$RESTRICTTEST', 100, '#QUALTEST', aa))
        def transfer(amount=10):
            return a.rpc('transfer', '$RESTRICTTEST', amount, bb, '', 0, '', aa)
        confirm(transfer())
        assert balance(b, '$RESTRICTTEST') == 10
        reject(a, 'transfer', '$RESTRICTTEST', 1, b.rpc('getnewaddress'), '', 0, '', aa, contains='verifier')
        freeze_block = confirm(a.rpc('freezerestrictedasset', '$RESTRICTTEST'))
        for node in (a, b):
            assert '$RESTRICTTEST' in node.rpc('listglobalrestrictions')
            node.rpc('invalidateblock', freeze_block)
            assert '$RESTRICTTEST' not in node.rpc('listglobalrestrictions')
        for node in (a, b):
            node.rpc('reconsiderblock', freeze_block)
        sync()
        reject(a, 'transfer', '$RESTRICTTEST', 1, bb, '', 0, '', aa, contains='frozen')
        confirm(a.rpc('unfreezerestrictedasset', '$RESTRICTTEST'))
        confirm(transfer())
        confirm(a.rpc('freezeaddress', '$RESTRICTTEST', bb))
        # Address freezing prevents spending that address's outputs. It does
        # not prohibit receiving more assets at the frozen address.
        assert b.rpc('checkaddressrestriction', bb, '$RESTRICTTEST')
        reject(b, 'transfer', '$RESTRICTTEST', 20, aa, contains="doesn't have asset")
        confirm(a.rpc('unfreezeaddress', '$RESTRICTTEST', bb))
        confirm(transfer())
        assert balance(b, '$RESTRICTTEST') == 30
        confirm(a.rpc('removetagfromaddress', '#QUALTEST', bb))
        reject(a, 'transfer', '$RESTRICTTEST', 1, bb, '', 0, '', aa, contains='verifier')
        confirm(a.rpc('addtagtoaddress', '#QUALTEST', bb))
        print('PASS: qualifier, verifier, global/address freeze and unfreeze enforcement', flush=True)

        confirm(a.rpc('reissuerestrictedasset', asset_name='$RESTRICTTEST', qty=5,
                      to_address=aa, change_verifier=False))
        assert a.rpc('getassetdata', '$RESTRICTTEST')['amount'] == 105
        print('PASS: restricted reissue with named RPC parameters', flush=True)

        # Both nodes disconnect the same tip, then reconnect it. This tests
        # consensus undo/redo and wallet accounting independently of rescan.
        block = confirm(b.rpc('reissue', 'ACCEPTANCE', 7, bb), b)
        assert a.rpc('getassetdata', 'ACCEPTANCE')['amount'] == 137
        for node in (a, b):
            node.rpc('invalidateblock', block)
            assert node.rpc('getassetdata', 'ACCEPTANCE')['amount'] == 130
        for node in (a, b):
            node.rpc('reconsiderblock', block)
        sync()
        assert balance(b, 'ACCEPTANCE') == 24.34
        assert a.rpc('getassetdata', 'ACCEPTANCE')['amount'] == 137
        b.stop()
        b.start(rescan=True)
        assert balance(b, 'ACCEPTANCE') == 24.34
        assert balance(b, '$RESTRICTTEST') == 30
        print('PASS: reissue disconnect/reconnect, restart and rescan', flush=True)

        b.rpc('addnode', '127.0.0.1:' + str(a.ports[1]), 'onetry')
        height = a.rpc('getblockcount') + 1
        assert a.rpc('requestsnapshot', 'ACCEPTANCE', height)['request_status'] == 'Added'
        mine(2)
        sync()
        snapshot = a.rpc('getsnapshot', 'ACCEPTANCE', height)
        from decimal import Decimal
        assert sum(Decimal(str(o['amount_owned'])) for o in snapshot['owners']) == Decimal('137')
        before = set(a.rpc('getrawmempool'))
        assert a.rpc('distributereward', 'ACCEPTANCE', height, 'YERB', 10) == 'Created reward distribution'
        pending = set(a.rpc('getrawmempool')) - before
        assert len(pending) == 1, pending
        txid = pending.pop()
        tx = a.rpc('gettransaction', txid)
        assert -Decimal(str(tx['amount'])) > 0
        expected_payments = {
            owner['address']: (Decimal(str(owner['amount_owned'])) * Decimal(10) / Decimal(137))
            .quantize(Decimal('0.00000001'), rounding='ROUND_DOWN')
            for owner in snapshot['owners']
        }
        decoded = a.rpc('decoderawtransaction', tx['hex'])
        paid = {}
        for output in decoded['vout']:
            for address in output['scriptPubKey'].get('addresses', []):
                if address in expected_payments:
                    paid[address] = paid.get(address, Decimal(0)) + Decimal(str(output['value']))
        assert paid == expected_payments, (paid, expected_payments)
        assert a.rpc('getdistributestatus', 'ACCEPTANCE', height, 'YERB', 10)['Status'] == 1
        # Restart before confirmation: the recorded payment must be reused.
        a.stop()
        a.start()
        a.rpc('addnode', '127.0.0.1:' + str(b.ports[1]), 'onetry')
        restore.wait_for(lambda: txid in a.rpc('getrawmempool'), 'pending reward restored')
        assert set(a.rpc('getrawmempool')) == {txid}
        confirm(txid)
        mine(2)
        sync()
        assert a.rpc('getrawmempool') == []
        assert a.rpc('getdistributestatus', 'ACCEPTANCE', height, 'YERB', 10)['Status'] == 2
        reject(a, 'distributereward', 'ACCEPTANCE', height, 'YERB', 10, contains='already')
        print('PASS: ownership snapshot, reward payment restart and duplicate-plan rejection', flush=True)

        a.stop()
        a.extra_args += ('-wallet=wallet.dat', '-wallet=secondary.dat')
        a.wallet = 'wallet.dat'
        a.start()
        assert a.rpc('getdistributestatus', 'ACCEPTANCE', height, 'YERB', 10)['Status'] == 2
        a.rpc('addnode', '127.0.0.1:' + str(b.ports[1]), 'onetry')
        secondary = a.rpc('getnewaddress', _wallet='secondary.dat')
        confirm(a.rpc('sendtoaddress', secondary, 40))
        confirm(b.rpc('transfer', 'ACCEPTANCE!', 1, secondary), b)
        assert balance(a, 'ACCEPTANCE!') == 0
        assert a.rpc('listmyassets', _wallet='secondary.dat')['ACCEPTANCE!'] == 1
        reject(a, 'reissue', 'ACCEPTANCE', 1, aa, contains="doesn't have asset")
        confirm(a.rpc('reissue', 'ACCEPTANCE', 2, secondary, _wallet='secondary.dat'), wallet='secondary.dat')
        assert a.rpc('listmyassets', _wallet='secondary.dat')['ACCEPTANCE'] == 2
        print('PASS: secondary wallet ownership authorization and balance isolation', flush=True)
    finally:
        original_error = sys.exc_info()[0] is not None
        cleanup_errors = []
        for node in (b, a):
            try:
                node.stop()
            except Exception as exc:
                cleanup_errors.append(str(exc))
            finally:
                if node.process is not None and node.process.poll() is None:
                    node.process.kill()
                    node.process.wait()
        if cleanup_errors and not original_error:
            raise RuntimeError('Test cleanup failed: ' + '; '.join(cleanup_errors))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--workdir', type=Path)
    args = parser.parse_args()
    if args.workdir:
        args.workdir.mkdir(parents=True, exist_ok=False)
        run(args.binary.resolve(), args.workdir.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix='yerbas-asset-acceptance-') as directory:
            run(args.binary.resolve(), Path(directory))
