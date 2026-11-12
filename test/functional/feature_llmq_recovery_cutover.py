#!/usr/bin/env python3
"""Deferred recovery activation with a stalled quorum and retained registration.

This uses a deterministic normal regtest prefix, not unrecorded mainnet history.
"""
from feature_llmq_manual_recovery import ManualRecovery
from test_framework.util import assert_equal, assert_raises_rpc_error, connect_nodes, p2p_port, wait_until


class RecoveryCutover(ManualRecovery):
    activation_height = 150
    def set_test_params(self):
        super().set_test_params()
        for args in self.extra_args:
            args.append('-llmqrecoveryactivationheight=%d' % self.activation_height)

    def record(self, active):
        block_hash, effective = super().record(active)
        block = self.nodes[0].getblock(block_hash, 2)
        records = [tx for tx in block['tx'] if tx['type'] == 10]
        assert_equal(len(records), 1)
        tx = records[0]
        wallet_tx = self.nodes[0].gettransaction(tx['txid'])
        assert_equal(wallet_tx['blockhash'], block_hash)
        assert wallet_tx['confirmations'] > 0
        assert wallet_tx['fee'] < 0
        self.log.info('Mined %s record: height=%d txid=%s effective=%d',
                      'ON' if active else 'OFF', block['height'], tx['txid'], effective)
        return block_hash, effective

    def after_cutover(self):
        pass

    def run_test(self):
        c = self.nodes[0]
        assert_equal(c.quorum('recovery', 'status')['status'], 'not_activated')
        assert_raises_rpc_error(-8, 'has not activated', c.quorum, 'recovery', 'on')
        c.spork('SPORK_17_QUORUM_DKG_ENABLED', 0)
        self.mine(110)
        key = c.bls('generate')
        funding = c.getnewaddress()
        c.sendtoaddress(funding, 11)
        self.mine(1)
        registration = c.protx('register_fund', funding, 10,
                               '127.0.0.1:%d' % p2p_port(1), c.getnewaddress(),
                               key['public'], c.getnewaddress(), 0, c.getnewaddress(), funding)
        self.registrations = [registration]
        self.mine(self.activation_height - 1 - c.getblockcount())
        assert_equal(c.getblockcount(), self.activation_height - 1)
        before = c.protx('info', registration)
        assert_equal(c.quorum('recovery', 'status')['status'], 'not_activated')
        assert_raises_rpc_error(-8, 'has not activated', c.quorum, 'recovery', 'on')
        self.mine(1)
        activation_block = c.getbestblockhash()
        assert_equal(c.quorum('recovery', 'status')['status'], 'off')
        after = c.protx('info', registration)
        for field in ('collateralHash', 'collateralIndex'):
            assert_equal(after[field], before[field])
        for field in ('ownerAddress', 'pubKeyOperator', 'PoSePenalty', 'PoSeBanHeight'):
            assert_equal(after['state'][field], before['state'][field])
        self.after_cutover()
        assert not any(c.quorum('list').values())
        assert_raises_rpc_error(-8, 'recovery-version', c.quorum, 'recoveryrequest', self.activation_height + 30, self.activation_height + 60, 1)
        _, on = self.record(True)
        self.mine(on - c.getblockcount() - 1)
        assert not c.quorum('recoverystate')['active']
        self.mine(1)
        assert c.quorum('recoverystate')['active']
        assert not any(c.quorum('list').values())
        self.log.info('Cutover and paid ON succeeded without any formed quorum; registration preserved')
        self.observer(4)
        self.stop_node(4)
        _, off = self.record(False)
        self.mine(off - c.getblockcount() - 1)
        assert c.quorum('recoverystate')['active']
        self.mine(1)
        assert not c.quorum('recoverystate')['active']
        # Reconstruct ON then OFF before testing a subsequent ON. The old gossip
        # spork deliberately says ON, so it cannot explain the recovered OFF state.
        self.bump_mocktime(2, nodes=self.nodes[:4])
        c.spork('SPORK_21_LOW_LLMQ_PARAMS', 0)
        self.observer(5)
        self.bump_mocktime(2, nodes=self.nodes[:4] + [self.nodes[5]])
        c.spork('SPORK_21_LOW_LLMQ_PARAMS', 0)
        wait_until(lambda: self.nodes[5].spork('active')['SPORK_21_LOW_LLMQ_PARAMS'], timeout=20)
        self.restart_node(5, self.extra_args[5] + ['-reindex'])
        self.nodes[5].setmocktime(self.mocktime)
        connect_nodes(self.nodes[5], 0)
        self.check(5)
        wait_until(lambda: self.nodes[5].spork('active')['SPORK_21_LOW_LLMQ_PARAMS'], timeout=20)
        assert not self.nodes[5].quorum('recoverystate')['active']
        assert_equal(self.nodes[5].quorum('recovery', 'status')['status'], 'off')
        self.log.info('ON then OFF reconstructed by fresh sync and reindex while gossip LOW spork is ON')
        self.stop_node(5)
        _, second_on = self.record(True)
        self.mine(second_on - c.getblockcount())
        assert c.quorum('recoverystate')['active']
        self.observer(5)
        self.restart_node(5, self.extra_args[5] + ['-reindex'])
        self.nodes[5].setmocktime(self.mocktime)
        connect_nodes(self.nodes[5], 0)
        self.check(5)
        self.nodes[5].setnetworkactive(False)
        self.nodes[5].invalidateblock(activation_block)
        assert_equal(self.nodes[5].getblockcount(), self.activation_height - 1)
        assert_equal(self.nodes[5].quorum('recovery', 'status')['status'], 'not_activated')
        self.nodes[5].reconsiderblock(activation_block)
        self.check(5)
        self.log.info('Fresh replay, reindex, second ON, and rollback through cutover passed')


if __name__ == '__main__':
    RecoveryCutover().main()
