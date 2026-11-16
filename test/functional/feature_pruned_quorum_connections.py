#!/usr/bin/env python3
"""Pruned operators form DKG over automatic authenticated quorum links."""
from feature_llmq_manual_recovery import ManualRecovery
from test_framework.util import connect_nodes,wait_until,force_finish_mnsync,p2p_port,assert_equal
class PrunedQuorumConnections(ManualRecovery):
    def set_test_params(self):
        super().set_test_params()
        for i in (1,2,3):self.extra_args[i] += ['-prune=550','-txindex=0']
    def register_operators(self):
        c = self.nodes[0]
        self.registrations = []
        keys = []
        for i in range(1, 4):
            k = c.bls('generate')
            keys.append(k['secret'])
            f = c.getnewaddress()
            c.sendtoaddress(f, 11)
            self.mine(1)
            self.registrations.append(c.protx('register_fund', f, 10, '127.0.0.1:%d' % p2p_port(i), c.getnewaddress(), k['public'], c.getnewaddress(), 0, c.getnewaddress(), f))
            self.mine(2)
        for i in range(1, 4):
            self.restart_node(i, self.extra_args[i] + ['-smartnodeblsprivkey=' + keys[i - 1]])
            self.nodes[i].setmocktime(self.mocktime)
            connect_nodes(self.nodes[i], 0)
            wait_until(lambda: any(('testnode0' in peer['subver'] and peer['version'] != 0 for peer in self.nodes[i].getpeerinfo())), timeout=30)
        for n in self.nodes[:4]:
            force_finish_mnsync(n)
        self.sync_blocks(self.nodes[:4], timeout=30)

    def run_test(self):
        c=self.nodes[0]
        self.mine(110)
        self.register_operators()
        for i in (1,2,3):
            assert self.nodes[i].getblockchaininfo()['pruned']
            assert int(self.nodes[i].getnetworkinfo()['localservices'],16)&1 == 0
            assert not any(p.get('verified_proregtx_hash') for p in self.nodes[i].getpeerinfo())
        c.spork('SPORK_17_QUORUM_DKG_ENABLED',0)
        wait_until(lambda:all(n.spork('active')['SPORK_17_QUORUM_DKG_ENABLED'] for n in self.nodes[:4]))
        q=self.dkg(3)
        assert all(m['valid'] for m in q['members'])
        for i in (1,2,3):
            assert any(p.get('verified_proregtx_hash') for p in self.nodes[i].getpeerinfo())
        peers=[p for i in (1,2,3) for p in self.nodes[i].getpeerinfo()
               if p.get('verified_proregtx_hash')]
        assert any(not p['inbound'] and not (int(p['services'],16)&1) for p in peers)
        self.mine(8)
        for i in (1,2,3):assert self.nodes[i].quorum('sign',1,'ab'*32,'cd'*32)
        wait_until(lambda:c.quorum('hasrecsig',1,'ab'*32,'cd'*32),timeout=45)
        self.log.info('Pruned automatic quorum connections, DKG and recovered signature passed')
if __name__=='__main__':PrunedQuorumConnections().main()
