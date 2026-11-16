#!/usr/bin/env python3
"""Actual 128-MiB block-file deletion on a registered regtest smartnode.
Records working features and historical-data limitations; does not enable production pruning.
"""
import json
from io import BytesIO
from test_framework.messages import CBlock
from pathlib import Path
from feature_llmq_manual_recovery import ManualRecovery
from test_framework.util import connect_nodes, force_finish_mnsync, wait_until, assert_equal, gen_return_txouts, create_lots_of_big_transactions
from test_framework.authproxy import JSONRPCException

class PrunedSmartnode(ManualRecovery):
    def add_options(self, parser):
        super().add_options(parser)
        parser.add_option("--automatic-pruning", action="store_true", default=False)

    def set_test_params(self):
        super().set_test_params()
        self.extra_args[1] += ['-prune=1', '-txindex=0']
        for args in self.extra_args:
            args += ['-maxreceivebuffer=20000', '-blockmaxsize=999000']
        self.saved_args = {}
        self.result = {'network':'isolated_regtest','production_pruning_enabled':False}

    def setup_network(self):
        if self.options.automatic_pruning:
            self.extra_args[1] = ["-prune=550" if x == "-prune=1" else x for x in self.extra_args[1]]
        super().setup_network()

    def restart_node(self, i, extra_args=None, *args, **kwargs):
        if extra_args is not None:self.saved_args[i]=list(extra_args)
        return super().restart_node(i, extra_args, *args, **kwargs)

    def sporks_same(self):
        wait_until(lambda:all(n.spork("active")==self.nodes[0].spork("active") for n in self.nodes[1:4]),timeout=30)

    def wait_with_clock(self, predicate, nodes, timeout=90):
        # Peer/signature retries use adjusted time; a frozen mock clock can
        # strand a valid signature share after an intentional disconnection.
        def tick():
            self.bump_mocktime(1,nodes=nodes)
            return predicate()
        wait_until(tick,timeout=timeout,sleep=0.5)

    def save_result(self):
        Path(self.options.tmpdir,'pruned-smartnode-result.json').write_text(json.dumps(self.result,indent=2,default=str))

    def proposal(self,name):
        c=self.nodes[0];now=self.mocktime
        data=dict(type=1,name=name,start_epoch=now,end_epoch=now+86400*30,payment_amount=1,payment_address=c.getnewaddress(),url='https://example.com/pruning')
        raw=json.dumps(data).encode().hex()
        fee=c.gobject('prepare','0'*64,'1',str(now),raw)
        self.mine(6)
        return ['0'*64,'1',str(now),raw,fee]

    def signing(self, tag):
        self.mine(8)
        for i in (1,2):assert self.nodes[i].quorum('sign',1,tag*32,'44'*32)
        wait_until(lambda:self.nodes[0].quorum('hasrecsig',1,tag*32,'44'*32),timeout=45)

    def run_test(self):
        c=self.nodes[0];p=self.nodes[1]
        self.mine(110);self.register_operators()
        c.spork('SPORK_19_CHAINLOCKS_ENABLED',4070908800)
        c.spork('SPORK_2_INSTANTSEND_ENABLED',4070908800)
        c.spork('SPORK_3_INSTANTSEND_BLOCK_FILTERING',4070908800)
        c.spork('SPORK_17_QUORUM_DKG_ENABLED',0)
        self.sporks_same()
        before=self.dkg(3);self.signing('11')
        self.result['quorum_before_pruning']=before['quorumHash']
        c.spork('SPORK_17_QUORUM_DKG_ENABLED',4070908800)
        self.sporks_same()
        oldgov=self.proposal('prune-old')
        address=c.getnewaddress();payment=c.sendtoaddress(address,1);self.mine(6)
        tx=c.getrawtransaction(payment,True);oldhash=tx['blockhash'];oldheight=c.getblock(oldhash)['height'];oldproof=c.gettxoutproof([payment],oldhash)
        oldout=next(v['n'] for v in tx['vout'] if address in v['scriptPubKey'].get('addresses',[]))
        c.lockunspent(False,[dict(txid=payment,vout=oldout)])
        expected_list_proof=c.protx('diff','0'*64,oldhash)
        spent_address=c.getnewaddress();spent_parent=c.sendtoaddress(spent_address,1);self.mine(6)
        spent_tx=c.getrawtransaction(spent_parent,True)
        spent_out=next(v['n'] for v in spent_tx['vout'] if spent_address in v['scriptPubKey'].get('addresses',[]))
        c.lockunspent(False,[dict(txid=spent_parent,vout=spent_out)])
        oldraw=c.getrawtransaction(payment)
        blocks=Path(p.datadir)/self.chain/'blocks';original=blocks/'blk00000.dat'
        assert original.exists()
        # Use normal production-sized block files, not manual unlink or a smaller test limit.
        class SigningAdapter:
            def signrawtransactionwithwallet(self,raw,prev,kind):return c.signrawtransaction(raw,prev,None,kind)
            def __getattr__(self,name):return getattr(c,name)
        adapter=SigningAdapter();outputs=gen_return_txouts();utxos=[]
        for n in range(850 if self.options.automatic_pruning else 180):
            if len(utxos)<14:utxos=c.listunspent()
            create_lots_of_big_transactions(adapter,outputs,utxos,14,100*c.getnetworkinfo()['relayfee'])
            self.mine(1)
            if n%20==0:self.log.info('Large block %d; actual block files %s',n+1,[x.name for x in blocks.glob('blk*.dat')])
            if self.options.automatic_pruning:
                if not original.exists():break
            elif (blocks/'blk00001.dat').exists():break
        assert self.options.automatic_pruning or (blocks/'blk00001.dat').exists(), 'Must actually rotate the 128-MiB block file'
        self.mine(max(0,1100-c.getblockcount()))
        self.sync_blocks(self.nodes[:4],timeout=90)
        self.result['before_prune_bytes']=sum(x.stat().st_size for x in blocks.glob('*.dat'))
        if not self.options.automatic_pruning:p.pruneblockchain(c.getblockcount()-288)
        self.result["pruning_mode"]="automatic_550_MiB" if self.options.automatic_pruning else "manual"
        wait_until(lambda:not original.exists(),timeout=30)
        self.result['block_file_deleted']=True
        self.result['after_prune_bytes']=sum(x.stat().st_size for x in blocks.glob('*.dat'))
        self.result['pruneheight']=p.getblockchaininfo()['pruneheight']
        assert oldheight<self.result['pruneheight']
        try:p.getblock(oldhash,2);raise AssertionError('Old block unexpectedly retained')
        except JSONRPCException as e:self.result['old_block_error']=e.error
        assert_equal(p.getblockhash(oldheight),oldhash)
        assert_equal(p.verifytxoutproof(oldproof),[payment])
        assert_equal(p.decoderawtransaction(oldraw)['txid'],payment)
        self.result['archived_payment_merkle_proof_verified']=True
        self.save_result()
        self.restart_node(1,self.saved_args[1]);p=self.nodes[1];p.setmocktime(self.mocktime);connect_nodes(p,0);force_finish_mnsync(p)
        self.sync_blocks(self.nodes[:4],timeout=90)
        assert_equal(p.protx('diff','0'*64,oldhash),expected_list_proof)
        self.result['historical_smartnode_list_proof_after_pruning_restart']=True
        old_quorums=p.quorum('list');before_registry=[p.protx('info',h)['state'] for h in self.registrations]
        normal_args=list(self.saved_args[1])
        self.restart_node(1,normal_args+['-llmqtestrebuildindex']);p=self.nodes[1];p.setmocktime(self.mocktime)
        self.saved_args[1]=normal_args
        assert_equal(p.quorum('list'),old_quorums)
        assert_equal([p.protx('info',h)['state'] for h in self.registrations],before_registry)
        assert_equal(p.protx('diff','0'*64,oldhash),expected_list_proof)
        connect_nodes(p,0);force_finish_mnsync(p)
        self.result['quorum_index_rebuilt_after_pruning_registry_preserved']=True
        # Cold late submission: no cached governance object exists before deletion.
        try:
            p.gobject('submit',*oldgov);self.result['old_governance_collateral_supported']=True
        except JSONRPCException as e:
            self.result['old_governance_collateral_supported']=False;self.result['old_governance_error']=e.error
        assert self.result['old_governance_collateral_supported'], 'Retained collateral must survive pruning and restart'
        self.result['archival_old_governance_hash']=c.gobject('submit',*oldgov)
        altered=list(oldgov);body=json.loads(bytes.fromhex(altered[3]));body['name']='wrong-burn';altered[3]=json.dumps(body).encode().hex()
        try:p.gobject('submit',*altered);raise AssertionError('Retained collateral bound to another proposal was accepted')
        except JSONRPCException:pass
        self.result['retained_collateral_wrong_proposal_refused']=True
        self.save_result()

        currentgov=self.proposal('prune-recent')
        self.result['recent_governance_hash']=p.gobject('submit',*currentgov)
        tip=c.getbestblockhash()
        self.restart_node(1,self.saved_args[1]);p=self.nodes[1];p.setmocktime(self.mocktime);connect_nodes(p,0);force_finish_mnsync(p)
        self.sync_blocks(self.nodes[:4],timeout=90);assert_equal(p.getbestblockhash(),tip);assert not original.exists()
        for protx in self.registrations:assert_equal(p.protx('info',protx)['state'],c.protx('info',protx)['state'])
        self.result['restart_and_registry_passed']=True
        # Reconnect authenticated smartnode peers and run fresh real DKG after deletion/restart.
        for i in (2,3):connect_nodes(p,i)
        c.spork('SPORK_17_QUORUM_DKG_ENABLED',0);self.sporks_same()
        after=self.dkg(3);self.signing('22')
        self.result['quorum_after_pruning']=after['quorumHash'];self.result['quorum_signing_after_restart']=True
        c.spork('SPORK_17_QUORUM_DKG_ENABLED',4070908800);self.sporks_same()
        c.spork('SPORK_2_INSTANTSEND_ENABLED',0);self.sporks_same()
        # With one archival signer offline, the pruned signer is required for 2-of-3.
        self.stop_node(3)
        # Mine the child before the pruned signer sees it: its input has left UTXO.
        p.setnetworkactive(False)
        childraw=c.createrawtransaction([dict(txid=spent_parent,vout=spent_out)],{c.getnewaddress():0.999})
        childsigned=c.signrawtransaction(childraw);assert childsigned['complete']
        child=c.sendrawtransaction(childsigned['hex'])
        # Spend the child too: completion cannot rediscover it through an unspent output.
        grandraw=c.createrawtransaction([dict(txid=child,vout=0)],{c.getnewaddress():0.998})
        grandsigned=c.signrawtransaction(grandraw);assert grandsigned['complete']
        grandchild=c.sendrawtransaction(grandsigned['hex'])
        self.bump_mocktime(2,nodes=self.nodes[:3]);c.generate(1)
        p.setnetworkactive(True);connect_nodes(p,0);connect_nodes(p,2);force_finish_mnsync(p)
        self.sync_blocks(self.nodes[:3],timeout=60)
        assert p.gettxout(spent_parent,spent_out,False) is None
        assert p.gettxout(child,0,False) is None
        self.wait_with_clock(lambda:c.getrawtransaction(child,True)['instantlock_internal'],self.nodes[:3])
        self.result['spent_input_instantsend_pruned_parent_required_signer']=True
        self.wait_with_clock(lambda:c.getrawtransaction(grandchild,True)['instantlock_internal'],self.nodes[:3])
        self.result['fully_spent_child_and_descendant_instantsend_passed']=True
        raw=c.createrawtransaction([dict(txid=payment,vout=oldout)],{c.getnewaddress():0.999})
        signed=c.signrawtransaction(raw);assert signed['complete']
        spend=c.sendrawtransaction(signed['hex'])
        wait_until(lambda:spend in p.getrawmempool() and p.getrawtransaction(spend,True)['instantlock_internal'],timeout=60)
        self.result['instantsend_pruned_parent_required_signer']=True
        self.save_result()
        self.restart_node(3,self.saved_args[3]);self.nodes[3].setmocktime(self.mocktime);connect_nodes(self.nodes[3],0);force_finish_mnsync(self.nodes[3])
        # Confirm all three locks while InstantSend processing is still enabled.
        self.mine(7)
        self.bump_mocktime(2,nodes=self.nodes[:4])
        c.spork('SPORK_2_INSTANTSEND_ENABLED',4070908800);self.sporks_same()
        recent=c.sendtoaddress(c.getnewaddress(),1);self.mine(6)
        recenthash=c.getrawtransaction(recent,True)['blockhash'];recentheight=c.getblock(recenthash)['height'];proof=c.gettxoutproof([recent],recenthash)
        assert_equal(p.verifytxoutproof(proof),[recent]);assert any(t['txid']==recent for t in p.getblock(recenthash,2)['tx'])
        self.result['recent_payment_verified']=True
        # A longer alternate chain replaces the six-confirmation payment anchor.
        c.setnetworkactive(False);c.invalidateblock(recenthash)
        self.bump_mocktime(10,nodes=self.nodes[:4]);c.generate(8);c.setnetworkactive(True);connect_nodes(p,0)
        self.sync_blocks(self.nodes[:4],timeout=90)
        assert p.getblockhash(recentheight)!=recenthash
        try:
            value=p.verifytxoutproof(proof);assert_equal(value,[])
        except JSONRPCException as e:
            assert 'Block not found in chain' in e.error['message']
        self.result['six_block_reorg_and_stale_payment_proof_refused']=True
        log=(Path(p.datadir)/self.chain/'debug.log').read_text()
        for txid in (child,grandchild,spend):
            assert any(txid in line and 'removed islock as it got fully confirmed' in line for line in log.splitlines())
        self.result['mined_instantsend_locks_retired_after_confirmation']=True
        # Refuse a deep rollback before disconnecting even one block.
        before_tip=p.getbestblockhash()
        try:p.invalidateblock(p.getblockhash(self.result['pruneheight']-1));raise AssertionError('Missing rollback data accepted')
        except JSONRPCException as e:assert 'Pruned rollback requires' in e.error['message']
        assert_equal(p.getbestblockhash(),before_tip)
        self.restart_node(1,self.saved_args[1]);p=self.nodes[1];p.setmocktime(self.mocktime)
        assert_equal(p.getbestblockhash(),before_tip)
        self.result['deep_rollback_refused_without_tip_change_and_restart_passed']=True
        # Exercise actual ChainLock signing with the pruned node required.
        connect_nodes(p,0);connect_nodes(p,2);force_finish_mnsync(p)
        self.stop_node(3)
        self.bump_mocktime(2,nodes=self.nodes[:3])
        c.spork('SPORK_19_CHAINLOCKS_ENABLED',0)
        wait_until(lambda:all(n.spork('active')['SPORK_19_CHAINLOCKS_ENABLED'] for n in self.nodes[:3]),timeout=30)
        locked=c.generate(1)[0]
        self.sync_blocks(self.nodes[:3],timeout=60)
        self.wait_with_clock(lambda:all(n.getblock(locked)['chainlock'] for n in self.nodes[:3]),self.nodes[:3])
        self.result['chainlock_after_pruning_required_signer']=True
        self.restart_node(1,self.saved_args[1]);p=self.nodes[1];p.setmocktime(self.mocktime)
        connect_nodes(p,0);connect_nodes(p,2);force_finish_mnsync(p)
        self.bump_mocktime(2,nodes=self.nodes[:3]);locked=c.generate(1)[0]
        self.sync_blocks(self.nodes[:3],timeout=60)
        self.wait_with_clock(lambda:all(n.getblock(locked)['chainlock'] for n in self.nodes[:3]),self.nodes[:3])
        self.result['chainlock_after_second_restart']=True
        conflict=CBlock();conflict.deserialize(BytesIO(bytes.fromhex(c.getblock(locked,0))))
        # Let the native node check GhostRider PoW. Legacy Python solve()
        # uses Dash hashing and is not valid for Yerbas headers.
        for _ in range(1024):
            conflict.nNonce+=1
            refusal=p.submitblock(conflict.serialize().hex())
            if refusal!='high-hash':break
        assert_equal(refusal,'bad-chainlock')
        assert_equal(p.getbestblockhash(),locked)
        self.result['chainlock_conflicting_block_refused']=True
        self.result['final_height']=p.getblockcount();self.save_result()
        self.log.info('Pruning characterization complete: %s',json.dumps(self.result,default=str))

if __name__=='__main__':PrunedSmartnode().main()
