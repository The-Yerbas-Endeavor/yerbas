#!/usr/bin/env python3
"""The first signed ON, rather than a release height, selects the cutover."""
from feature_llmq_manual_recovery import ManualRecovery
from test_framework.util import assert_equal, assert_raises_rpc_error, connect_nodes


class RecordCutover(ManualRecovery):
    def set_test_params(self):
        super().set_test_params()
        for args in self.extra_args:
            args.remove('-llmqrecoverytest')
            args.append('-llmqrecoverybyrecord')

    def run_test(self):
        self.registrations = []
        c = self.nodes[0]
        self.mine(110)
        status = c.quorum('recovery', 'status')
        assert status['activation_by_record']
        assert_equal(status['cutover_height'], 0)
        assert not status['active']
        # Existing databases must rebuild history instead of assuming no record.
        legacy_args = [a for a in self.extra_args[4] if a != '-llmqrecoverybyrecord']
        self.start_node(4, legacy_args)
        self.nodes[4].setmocktime(self.mocktime)
        connect_nodes(self.nodes[4], 0)
        self.sync_blocks([c, self.nodes[4]])
        self.stop_node(4)
        self.nodes[4].assert_start_raises_init_error(
            self.extra_args[4], 'Signed recovery history is missing', partial_match=True)
        self.start_node(4, self.extra_args[4] + ['-reindex-chainstate'])
        self.nodes[4].setmocktime(self.mocktime)
        connect_nodes(self.nodes[4], 0)
        self.check(4)
        self.stop_node(4)
        assert_raises_rpc_error(-8, 'recovery-first-cutover', c.quorum, 'recoveryrequest', 150, 0, 2)
        first_block, on = self.record(True)
        assert_equal(on, 720)
        assert_equal(c.quorum('recoverystate')['cutoverHeight'], on)
        self.mine(on - c.getblockcount() - 1)
        assert not c.quorum('recoverystate')['active']
        self.mine(1)
        assert c.quorum('recoverystate')['active']
        assert not any(c.quorum('list').values())
        self.log.info('First paid ON selected cutover 720 without a configured activation height or quorum')
        _, off = self.record(False)
        self.mine(off - c.getblockcount())
        assert not c.quorum('recoverystate')['active']
        assert_equal(c.quorum('recoverystate')['cutoverHeight'], on)
        self.observer(5)
        self.restart_node(5, self.extra_args[5] + ['-reindex'])
        self.nodes[5].setmocktime(self.mocktime)
        connect_nodes(self.nodes[5], 0)
        self.check(5)
        assert_equal(self.nodes[5].quorum('recoverystate')['cutoverHeight'], on)
        assert not self.nodes[5].quorum('recoverystate')['active']
        self.nodes[5].setnetworkactive(False)
        self.nodes[5].invalidateblock(first_block)
        assert_equal(self.nodes[5].getblockcount(), 110)
        assert_equal(self.nodes[5].quorum('recoverystate')['cutoverHeight'], 0)
        self.nodes[5].reconsiderblock(first_block)
        self.check(5)
        _, again = self.record(True)
        assert again - c.getblockcount() <= 60
        self.mine(again - c.getblockcount())
        assert_equal(c.quorum('recoverystate')['cutoverHeight'], on)
        assert c.quorum('recoverystate')['active']
        self.log.info('OFF retains cutover; fresh sync/reindex and first-record rollback agree; later ON uses 30-block schedule')


if __name__ == '__main__':
    RecordCutover().main()
