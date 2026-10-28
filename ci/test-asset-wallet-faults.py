#!/usr/bin/env python3
"""Linux-only disposable fixture test. Requires a separately built regtest-height-220
fixture with testcrashreservation/testcrashcommit SIGSTOP hooks. Never use that
fixture as a release binary. The second binary is the unmodified release candidate.
"""
import argparse
import concurrent.futures
import importlib.util
from pathlib import Path
import sys
spec = importlib.util.spec_from_file_location('restore', Path(__file__).with_name('test-wallet-asset-restore.py'))
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)

def run(fixture, candidate, root):
    args = ('-assetindex=1', '-minrewardheight=1', '-par=1', '-dbcache=128')
    a = r.Node(fixture, root/'guarded', args)
    b = r.Node(candidate, root/'unrestricted-producer', args)
    def connect():
        a.rpc('addnode', '127.0.0.1:'+str(b.ports[1]), 'onetry')
        r.wait_for(lambda: any(p['version'] for p in a.rpc('getpeerinfo')), 'handshake')
    def sync():
        r.wait_for(lambda: a.rpc('getbestblockhash') == b.rpc('getbestblockhash'), 'chain sync')
    def mine(n=1):
        blocks=[]
        for _ in range(n):
            now=a.rpc('getblockheader',a.rpc('getbestblockhash'))['time']+601
            for node in (a,b): node.rpc('setmocktime',now)
            blocks.extend(a.rpc('generate',1))
        sync()
        return blocks
    def confirm(tx):
        if isinstance(tx,list): tx=tx[0]
        r.wait_for(lambda: tx in a.rpc('getrawmempool'), 'transaction relay')
        mine()
    def locked(method,*params):
        before=set(a.rpc('getrawmempool'))
        try: a.rpc(method,*params)
        except r.RPCError as exc:
            assert exc.code == -4 and 'disabled until mainnet block' in str(exc), str(exc)
        else: raise AssertionError('Wallet guard bypass: '+method)
        assert before==set(a.rpc('getrawmempool'))
    try:
        a.start(); b.start(); connect()
        mine(215)
        aa,bb=a.rpc('getnewaddress'),b.rpc('getnewaddress')
        confirm(a.rpc('sendtoaddress',bb,100))
        confirm(b.rpc('issue','LEGACYASSET',100,bb))
        confirm(b.rpc('transfer','LEGACYASSET',10,aa))
        mine()
        assert a.rpc('getblockcount')==219
        assert a.rpc('listmyassets')['LEGACYASSET']==10
        for method,params in [('issue',('LOCKED',1)),('transfer',('LEGACYASSET',1,bb)),('reissue',('LEGACYASSET',1,aa))]: locked(method,*params)
        payment=a.rpc('sendtoaddress',bb,1)
        boundary=mine()[0]
        assert a.rpc('gettransaction',payment)['confirmations']==1
        assert a.rpc('getblockcount')==220
        confirm(a.rpc('issue','BOUNDARYASSET',100,aa))
        confirm(a.rpc('transfer','BOUNDARYASSET',10,bb))
        confirm(a.rpc('reissue','BOUNDARYASSET',5,aa))
        for node in (a,b): node.rpc('invalidateblock',boundary)
        assert a.rpc('getblockcount')==219
        locked('transfer','LEGACYASSET',1,bb)
        locked('issue','RELOCKED',1)
        locked('reissue','BOUNDARYASSET',1,aa)
        for node in (a,b): node.rpc('reconsiderblock',boundary)
        sync()
        confirm(a.rpc('transfer','BOUNDARYASSET',1,bb))
        a.stop(); a.start(); connect(); sync()
        confirm(a.rpc('transfer','BOUNDARYASSET',1,bb))
        print('PASS: pre-boundary rejection, unrestricted-producer receipt, YERB payment, exact boundary, issue/transfer/reissue, rollback relock, reconsider and restart',flush=True)
        for hook,expected in [('testcrashreservation',6),('testcrashcommit',2)]:
            snapshot=a.rpc('getblockcount')+1
            a.rpc('requestsnapshot','BOUNDARYASSET',snapshot)
            mine(2)
            assert not a.rpc('getrawmempool')
            a.stop(); a.extra_args=args+('-'+hook+'=1',); a.start(); connect()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                request=pool.submit(a.rpc,'distributereward','BOUNDARYASSET',snapshot,'YERB',10)
                def stopped():
                    assert a.process.poll() is None, 'Fixture exited before crash point'
                    return any(line.startswith('State:') and 'T' in line.split()[1] for line in Path('/proc/'+str(a.process.pid)+'/status').read_text().splitlines())
                r.wait_for(stopped,'exact crash point',timeout=30)
                a.process.kill(); a.process.wait(timeout=10)
                try: request.result(timeout=10)
                except (OSError,RuntimeError): pass
            a.log.close(); a.extra_args=args; a.start(); connect(); sync()
            if hook=='testcrashcommit':
                r.wait_for(lambda: len(a.rpc('getrawmempool'))==1,'single committed payment recovered')
                payment=next(iter(a.rpc('getrawmempool')))
            else:
                assert a.rpc('getrawmempool')==[]
            mine(3)
            status=a.rpc('getdistributestatus','BOUNDARYASSET',snapshot,'YERB',10)['Status']
            assert status==expected,(hook,status)
            assert a.rpc('getrawmempool')==[]
            if hook=='testcrashcommit': assert a.rpc('gettransaction',payment)['confirmations']>0
            a.stop(); a.start(); connect(); mine(2)
            assert a.rpc('getrawmempool')==[]
            assert a.rpc('getdistributestatus','BOUNDARYASSET',snapshot,'YERB',10)['Status']==expected
            print('PASS: SIGKILL at '+hook+', database recovery, no duplicate payout through restart and further blocks',flush=True)
    finally:
        for node in (a,b):
            try: node.stop()
            except Exception:
                if node.process and node.process.poll() is None: node.process.kill(); node.process.wait()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('fixture',type=Path); p.add_argument('candidate',type=Path); p.add_argument('--workdir',type=Path,required=True)
    a=p.parse_args(); a.workdir.mkdir(parents=True,exist_ok=False)
    run(a.fixture.resolve(),a.candidate.resolve(),a.workdir.resolve())
