#!/usr/bin/env python3
"""Historical proposal votes and real superblock payout on a pruned smartnode."""
import json
from decimal import Decimal
from feature_pruned_smartnode import PrunedSmartnode
from test_framework.util import connect_nodes, force_finish_mnsync, wait_until, assert_equal

class PrunedGovernance(PrunedSmartnode):
    def set_test_params(self):
        super().set_test_params()
        for args in self.extra_args:args.append('-budgetparams=1:100:1100')

    def run_test(self):
        super().run_test()
        c=self.nodes[0];p=self.nodes[1]
        self.restart_node(3,self.saved_args[3]);self.nodes[3].setmocktime(self.mocktime)
        for i in (0,1,2):connect_nodes(self.nodes[3],i)
        force_finish_mnsync(self.nodes[3])
        proposal=self.result['archival_old_governance_hash']
        vote=c.gobject('vote-many',proposal,'funding','yes')
        assert 'failed 0' in vote['overall'], vote
        wait_until(lambda:p.gobject('list','all')[proposal]['YesCount']==3,timeout=60)
        self.result['historical_proposal_three_funding_votes']=True
        self.restart_node(1,self.saved_args[1]);p=self.nodes[1];p.setmocktime(self.mocktime)
        connect_nodes(p,0);connect_nodes(p,2);connect_nodes(p,3);force_finish_mnsync(p)
        assert_equal(p.gobject('list','all')[proposal]['YesCount'],3)
        self.result['historical_votes_survive_restart']=True
        destination=c.getnewaddress();height=(c.getblockcount()//10+3)*10
        trigger=dict(type=2,event_block_height=height,payment_addresses=destination,payment_amounts='1')
        trigger_hash=p.gobject('submit','0','1',str(self.mocktime),json.dumps(trigger).encode().hex(),'0'*64)
        wait_until(lambda:all(trigger_hash in n.gobject('list','all') for n in self.nodes[:4]),timeout=60)
        for n in self.nodes[1:4]:
            result=n.gobject('vote-conf',trigger_hash,'funding','yes')
            assert 'failed 0' in result['overall'],result
        wait_until(lambda:all(n.gobject('list','all')[trigger_hash]['YesCount']==3 for n in self.nodes[:4]),timeout=60)
        self.bump_mocktime(2,nodes=self.nodes[:4]);c.spork('SPORK_9_SUPERBLOCKS_ENABLED',0)
        self.wait_with_clock(lambda:all(n.spork('active')['SPORK_9_SUPERBLOCKS_ENABLED'] for n in self.nodes[:4]),self.nodes[:4])
        self.mine(height-c.getblockcount())
        blockhash=p.getblockhash(height);block=p.getblock(blockhash,2)
        payouts=[v for v in block['tx'][0]['vout'] if destination in v['scriptPubKey'].get('addresses',[])]
        assert_equal(len(payouts),1);assert_equal(payouts[0]['value'],Decimal('1'))
        assert_equal(c.getblockhash(height),blockhash)
        self.result['pruned_smartnode_signed_trigger_and_validated_superblock_payout']=True
        self.mine(7)
        self.restart_node(1,self.saved_args[1]);p=self.nodes[1];p.setmocktime(self.mocktime)
        assert_equal(p.getblockhash(height),blockhash)
        self.result['superblock_payout_survives_restart']=True
        self.result['final_height']=p.getblockcount();self.save_result()
        self.log.info('Pruned governance payout checks passed')

if __name__=='__main__':PrunedGovernance().main()
