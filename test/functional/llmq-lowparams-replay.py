#!/usr/bin/env python3
"""Opt-in LOW_LLMQ replay reproducer; no mainnet access or smartnodes.

This checks null-commitment replay only. It does not establish DKG/PoSe safety.
Run directly; deliberately not registered in the passing regression suite until
historical parameter selection is repaired.
"""
from io import BytesIO
import json
from pathlib import Path

from test_framework.messages import CBlock, CFinalCommitment, FromHex
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import assert_equal, connect_nodes, disconnect_nodes, wait_until


class LowLLMQReplayTest(BitcoinTestFramework):
    def set_test_params(self):
        self.num_nodes = 4
        self.setup_clean_chain = True
        self.extra_args = [["-sporkkey=cP4EKFyJsHT39LDqgdcB43Y3YXjNyjb5Fuas1GQSeAtjnZWmZEQK"], [], [], []]

    def add_options(self, parser):
        parser.add_option("--scenario", type="choice", choices=["fresh-active", "restart", "fresh-inactive", "rewind", "fork"], default="fresh-active")

    def setup_network(self):
        self.setup_nodes()
        if self.options.scenario != "fork":
            self.stop_node(2)
        self.stop_node(3)
        connect_nodes(self.nodes[0], 1)
        if self.options.scenario == "fork":
            connect_nodes(self.nodes[0], 2)

    def set_low(self, active):
        self.nodes[0].spork("SPORK_21_LOW_LLMQ_PARAMS", 0 if active else 4070908800)
        wait_until(lambda: self.nodes[1].spork("active")["SPORK_21_LOW_LLMQ_PARAMS"] == active)

    def mine(self, count, miner=0):
        initial_height = self.nodes[miner].getblockcount()
        for _ in range(count):
            # Space blocks normally: this branch's DGW still retargets regtest.
            self.bump_mocktime(150, nodes=self.nodes[:3] if self.options.scenario == "fork" else self.nodes[:2])
            assert_equal(len(self.nodes[miner].generate(1)), 1)
        assert_equal(self.nodes[miner].getblockcount(), initial_height + count)

    def run_test(self):
        try:
            self.run_scenario()
        finally:
            # Preserve the original assertions and failure status. This evidence
            # records public chain/spork state only, never wallet/key material.
            evidence = {'scenario': self.options.scenario, 'nodes': [], 'reference_commitments': []}
            reference = self.nodes[0]
            for height in (10, 40, 70, 100, 130, 160):
                if height > reference.getblockcount():
                    continue
                block_hash = reference.getblockhash(height)
                block = FromHex(CBlock(), reference.getblock(block_hash, False))
                for tx in block.vtx:
                    if tx.nType != 6:
                        continue
                    commitment = CFinalCommitment()
                    commitment.deserialize(BytesIO(tx.vExtraPayload[6:]))
                    if commitment.llmqType == 1:
                        evidence['reference_commitments'].append({'height': height, 'block_hash': block_hash,
                            'signer_slots': len(commitment.signers), 'member_slots': len(commitment.validMembers)})
            for i, node in enumerate(self.nodes):
                if not node.running:
                    continue
                info = node.getblockchaininfo()
                entry = {'node': i, 'height': info['blocks'], 'bestblockhash': info['bestblockhash'],
                         'low_llmq_active': node.spork('active')['SPORK_21_LOW_LLMQ_PARAMS']}
                entry['block_hashes'] = {str(h): node.getblockhash(h) for h in (9, 10, 39, 40, 60, 69, 70, 120)
                                         if h <= info['blocks']}
                log = Path(node.datadir) / self.chain / 'debug.log'
                entry['commitment_rejections'] = [line for line in log.read_text(errors='replace').splitlines()
                    if 'CFinalCommitment::VerifySizes' in line or 'bad-qc-invalid-null' in line][-12:]
                evidence['nodes'].append(entry)
            (Path(self.options.tmpdir) / 'replay-evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')

    def run_scenario(self):
        live = self.nodes[:2]
        self.log.info("Normal LLMQ: build 60-block baseline")
        self.mine(60)
        self.sync_blocks(live, timeout=30)
        if self.options.scenario == "fork":
            self.sync_blocks(self.nodes[:3], timeout=30)
            disconnect_nodes(self.nodes[0], 2)
        self.set_low(True)
        self.log.info("LOW_LLMQ: continuously running peers")
        self.mine(60)
        self.sync_blocks(live, timeout=30)
        if self.options.scenario == "fork":
            self.log.info("Competing fork: isolated peer mines normal parameters from height 60")
            assert not self.nodes[2].spork("active")["SPORK_21_LOW_LLMQ_PARAMS"]
            self.mine(90, miner=2)
            assert int(self.nodes[2].getblockchaininfo()["chainwork"], 16) > int(self.nodes[0].getblockchaininfo()["chainwork"], 16)
            connect_nodes(self.nodes[0], 2)
            self.sync_blocks(self.nodes[:3], timeout=30)
        elif self.options.scenario == "fresh-active":
            self.log.info("LOW_LLMQ: fresh node replay from genesis")
            self.start_node(2, self.extra_args[0])
            self.nodes[2].setmocktime(self.mocktime)
            self.nodes[2].spork("SPORK_21_LOW_LLMQ_PARAMS", 0)
            assert self.nodes[2].spork("active")["SPORK_21_LOW_LLMQ_PARAMS"]
            connect_nodes(self.nodes[0], 2)
            self.sync_blocks(self.nodes[:3], timeout=30)
        elif self.options.scenario == "restart":
            self.log.info("LOW_LLMQ: restart existing node and extend chain")
            self.restart_node(1)
            self.nodes[1].setmocktime(self.mocktime)
            connect_nodes(self.nodes[0], 1)
            self.mine(30)
            self.sync_blocks(live, timeout=30)
        elif self.options.scenario == "rewind":
            self.log.info("LOW_LLMQ: invalidate/reconsider across activation (not a competing fork)")
            boundary = self.nodes[1].getblockhash(40)
            self.nodes[1].invalidateblock(boundary)
            self.nodes[1].reconsiderblock(boundary)
            self.sync_blocks(live, timeout=30)
        else:
            # Ensure distinct spork signing timestamps on the live nodes.
            self.bump_mocktime(2, nodes=live)
            self.set_low(False)
            self.mine(60)
            self.sync_blocks(live, timeout=30)
            self.log.info("Normal LLMQ: fresh node after deactivation")
            self.start_node(3)
            self.nodes[3].setmocktime(self.mocktime)
            connect_nodes(self.nodes[0], 3)
            self.sync_blocks([*live, self.nodes[3]], timeout=30)


if __name__ == '__main__':
    LowLLMQReplayTest().main()
