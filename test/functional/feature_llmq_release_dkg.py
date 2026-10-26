#!/usr/bin/env python3
"""Real legacy quorum retirement and recorded ON/OFF across release cutover."""
from feature_llmq_manual_recovery import ManualRecovery
from test_framework.util import assert_equal, connect_nodes, wait_until


class ReleaseDKG(ManualRecovery):
    def set_test_params(self):
        super().set_test_params()
        for args in self.extra_args:
            args.remove('-llmqrecoverytest')
            args.append('-llmqrecoverycutoverheight=720')

    def enable_dkg(self, enabled):
        self.bump_mocktime(2, nodes=self.nodes[:4])
        self.nodes[0].spork('SPORK_17_QUORUM_DKG_ENABLED', 0 if enabled else 4070908800)
        wait_until(lambda: all(n.spork('active')['SPORK_17_QUORUM_DKG_ENABLED'] == enabled for n in self.nodes[:4]), timeout=20)

    def run_test(self):
        c = self.nodes[0]
        self.mine(110)
        self.register_operators()
        self.mine(689 - c.getblockcount())
        self.enable_dkg(True)
        legacy = self.dkg(3)
        assert_equal(len(c.quorum('list')['llmq_3_60']), 1)
        self.mine(8)
        for i in (1, 2):
            assert self.nodes[i].quorum('sign', 1, '11' * 32, '44' * 32)
        wait_until(lambda: c.quorum('hasrecsig', 1, '11' * 32, '44' * 32), timeout=30)
        assert_equal(c.quorum('getrecsig', 1, '11' * 32, '44' * 32)['quorumHash'], legacy['quorumHash'])
        self.mine(719 - c.getblockcount())
        before = [c.protx('info', h)['state'] for h in self.registrations]
        self.mine(1)
        cutover = c.getbestblockhash()
        assert_equal(c.quorum('recovery', 'status')['status'], 'off')
        for i in (1, 2):
            assert not self.nodes[i].quorum('sign', 1, '22' * 32, '33' * 32)
        for h, state in zip(self.registrations, before):
            now = c.protx('info', h)['state']
            for field in ('ownerAddress', 'pubKeyOperator', 'PoSePenalty', 'PoSeBanHeight'):
                assert_equal(now[field], state[field])
        self.log.info('Legacy quorum signed before cutover and cannot sign afterward; registrations retained')
        self.enable_dkg(False)
        _, on = self.record(True)
        self.mine(on - c.getblockcount() - 1)
        self.enable_dkg(True)
        low = self.dkg(3)
        assert c.quorum('recoverystate')['active']
        self.mine(8)
        for i in (1, 2):
            assert self.nodes[i].quorum('sign', 1, '55' * 32, '66' * 32)
        wait_until(lambda: c.quorum('hasrecsig', 1, '55' * 32, '66' * 32), timeout=30)
        assert_equal(c.quorum('getrecsig', 1, '55' * 32, '66' * 32)['quorumHash'], low['quorumHash'])
        self.enable_dkg(False)
        _, off = self.record(False)
        self.mine(off - c.getblockcount())
        assert not c.quorum('recoverystate')['active']
        for i in (1, 2):
            assert not self.nodes[i].quorum('sign', 1, '77' * 32, '88' * 32)
        self.enable_dkg(True)
        normal = self.dkg(3)
        assert all(m['valid'] for m in normal['members'])
        self.observer(5)
        self.restart_node(5, self.extra_args[5] + ['-reindex'])
        self.nodes[5].setmocktime(self.mocktime)
        connect_nodes(self.nodes[5], 0)
        self.check(5)
        assert_equal(self.nodes[5].quorum('list'), c.quorum('list'))
        self.nodes[5].setnetworkactive(False)
        self.nodes[5].invalidateblock(cutover)
        assert_equal(self.nodes[5].getblockcount(), 719)
        assert_equal(self.nodes[5].quorum('recovery', 'status')['status'], 'not_activated')
        self.nodes[5].reconsiderblock(cutover)
        self.check(5)
        self.log.info('Release cutover: real legacy/LOW/normal commitments, fresh sync, reindex and rollback passed')


if __name__ == '__main__':
    ReleaseDKG().main()
