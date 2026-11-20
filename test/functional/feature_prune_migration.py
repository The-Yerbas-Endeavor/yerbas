#!/usr/bin/env python3
"""Regression: migrate an existing archival txindex chain to prune mode without reindex."""
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import assert_equal


class PruneMigrationTest(BitcoinTestFramework):
    def set_test_params(self):
        self.num_nodes = 1
        self.setup_clean_chain = True
        self.extra_args = [["-txindex=1", "-disablegovernance"]]

    def run_test(self):
        node = self.nodes[0]
        node.generate(25)
        height = node.getblockcount()
        tip = node.getbestblockhash()
        historical = node.getblockhash(1)
        assert_equal(node.getblockchaininfo()["pruned"], False)

        self.log.info("Restart existing archival chain with txindex disabled and pruning enabled")
        self.stop_node(0)
        prune_args = ["-txindex=0", "-prune=550", "-disablegovernance"]
        self.start_node(0, extra_args=prune_args)
        node = self.nodes[0]
        assert_equal(node.getblockcount(), height)
        assert_equal(node.getbestblockhash(), tip)
        assert_equal(node.getblockhash(1), historical)
        assert_equal(node.getblockchaininfo()["pruned"], True)

        self.log.info("Verify retained evidence survives a second prune-mode restart")
        self.stop_node(0)
        self.start_node(0, extra_args=prune_args)
        assert_equal(self.nodes[0].getbestblockhash(), tip)
        assert_equal(self.nodes[0].getblockchaininfo()["pruned"], True)


if __name__ == "__main__":
    PruneMigrationTest().main()
