#!/usr/bin/env python3
"""Exercise release-defined cutover routing, with regtest mining and authority.

This is the release policy path, not a mainnet fork or a public activation.
"""
from feature_llmq_recovery_cutover import RecoveryCutover
from test_framework.util import assert_equal, connect_nodes


class ReleaseCutover(RecoveryCutover):
    activation_height = 720

    def set_test_params(self):
        super().set_test_params()
        for args in self.extra_args:
            args.remove('-llmqrecoverytest')
            args.remove('-llmqrecoveryactivationheight=%d' % self.activation_height)
            args.append('-llmqrecoverycutoverheight=%d' % self.activation_height)

    def after_cutover(self):
        # Simulate a late upgrade: the old node has connected the boundary block
        # but has no recorded-state database. It must not silently initialize OFF.
        legacy_args = [arg for arg in self.extra_args[4] if not arg.startswith('-llmqrecoverycutoverheight=')]
        self.start_node(4, legacy_args)
        self.nodes[4].setmocktime(self.mocktime)
        connect_nodes(self.nodes[4], 0)
        self.sync_blocks([self.nodes[0], self.nodes[4]], timeout=60)
        self.stop_node(4)
        self.nodes[4].assert_start_raises_init_error(
            self.extra_args[4], 'Signed recovery history is missing.', partial_match=True)
        self.start_node(4, self.extra_args[4] + ['-reindex-chainstate'])
        self.nodes[4].setmocktime(self.mocktime)
        connect_nodes(self.nodes[4], 0)
        self.check(4)
        assert_equal(self.nodes[4].quorum('recovery', 'status')['status'], 'off')
        self.stop_node(4)
        self.log.info('Late upgrade refused missing recovery state; reindex-chainstate reconstructed it')

    def run_test(self):
        assert_equal(self.nodes[0].quorum('recovery', 'status')['activation_height'], 720)
        super().run_test()


if __name__ == '__main__':
    ReleaseCutover().main()
