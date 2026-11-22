#!/usr/bin/env python3
"""Regression: migrate an existing archival txindex chain to prune mode without reindex."""
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import assert_equal, assert_raises_rpc_error, get_chain_folder
from pathlib import Path


class PruneMigrationTest(BitcoinTestFramework):
    def set_test_params(self):
        self.num_nodes = 1
        self.setup_clean_chain = True
        self.extra_args = [["-txindex=1", "-disablegovernance"]]

    def setup_network(self):
        # This is a single-node offline archive conversion. The inherited
        # setup_network invokes sync_all(), including a legacy RPC not exposed
        # by Yerbas 4.0.1.6; no peer/mempool synchronization is needed.
        self.setup_nodes()

    def run_test(self):
        node = self.nodes[0]
        node.generate(40)
        height = node.getblockcount()
        tip = node.getbestblockhash()
        historical = node.getblockhash(1)
        assert_equal(node.getblockchaininfo()["pruned"], False)

        self.log.info("Restart existing archival chain with txindex disabled and pruning enabled")
        self.stop_node(0)
        prune_args = ["-txindex=0", "-prune=256", "-disablegovernance"]
        with node.assert_debug_log(["Prune evidence migration complete at height 40"]):
            self.start_node(0, extra_args=prune_args)
        node = self.nodes[0]
        assert_equal(node.getblockcount(), height)
        assert_equal(node.getbestblockhash(), tip)
        assert_equal(node.getblockhash(1), historical)
        assert_equal(node.getblockchaininfo()["pruned"], True)

        self.log.info("Verify evidence completion marker skips repeat scanning on restart")
        log = Path(node.datadir) / get_chain_folder(node.datadir, node.chain) / "debug.log"
        count_before = log.read_text(encoding="utf-8").count("Prune evidence migration: scanning")
        self.stop_node(0)
        self.start_node(0, extra_args=prune_args)
        count_after = log.read_text(encoding="utf-8").count("Prune evidence migration: scanning")
        assert_equal(count_after, count_before)
        assert_equal(self.nodes[0].getbestblockhash(), tip)
        assert_equal(self.nodes[0].getblockchaininfo()["pruned"], True)

        self.log.info("Opt-in evidence compaction preserves chain tip and is restart-safe")
        self.stop_node(0)
        compact_args = prune_args + ["-compactprunedevidence=1"]
        with node.assert_debug_log(["Prune evidence compaction finished and database compacted"]):
            self.start_node(0, extra_args=compact_args)
        assert_equal(node.getbestblockhash(), tip)
        assert_equal(node.getblockchaininfo()["pruned"], True)
        self.stop_node(0)
        with node.assert_debug_log(["Prune evidence compaction finished and database compacted"]):
            self.start_node(0, extra_args=compact_args)
        assert_equal(node.getbestblockhash(), tip)
        assert_equal(node.getblockchaininfo()["pruned"], True)
        evidence = node.quorum("verifyprunedevidence")
        assert_equal(evidence["verified"], True)
        assert_equal(evidence["blocks_checked"], height)
        assert_equal(evidence["commitments_matched"], 0)

        self.log.info("Verify an interrupted rebuild leaves the original index unchanged")
        assert_raises_rpc_error(-1, "Injected quorum index rebuild interruption",
                                node.quorum, "testrebuildprunedindex", 20)
        after_abort = node.quorum("verifyprunedevidence")
        assert_equal(after_abort["verified"], True)
        assert_equal(after_abort["blocks_checked"], height)
        assert_equal(after_abort["commitments_matched"], evidence["commitments_matched"])
        assert_equal(node.getbestblockhash(), tip)

        self.log.info("Exercise the real mined-quorum index rebuild on pruned regtest")
        rebuilt = node.quorum("testrebuildprunedindex")
        assert_equal(rebuilt["rebuilt"], True)
        assert_equal(rebuilt["blocks_checked"], height)
        assert_equal(rebuilt["commitments_matched"], evidence["commitments_matched"])
        assert_equal(node.getbestblockhash(), tip)
        self.stop_node(0)
        self.start_node(0, extra_args=prune_args)
        assert_equal(node.getbestblockhash(), tip)
        assert_equal(node.getblockchaininfo()["pruned"], True)
        after_restart = node.quorum("verifyprunedevidence")
        assert_equal(after_restart["verified"], True)
        assert_equal(after_restart["blocks_checked"], height)
        assert_equal(after_restart["commitments_matched"], evidence["commitments_matched"])


if __name__ == "__main__":
    PruneMigrationTest().main()
