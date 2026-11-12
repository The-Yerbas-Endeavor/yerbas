#!/usr/bin/env python3
"""Experimental signed recovery-record replay, expiry, and real-fork rollback.

This verifies on-chain authorization and null-commitment replay across recovery.
Real DKG, PoSe and signing-authority retirement have a separate operator test.
"""
from io import BytesIO
import json
import os

from test_framework.test_framework import BitcoinTestFramework
from test_framework.recovery_devnet import prepare_recovery_devnet, finish_recovery_devnet
from test_framework.messages import CBlock, CFinalCommitment, CTransaction, FromHex
from test_framework.util import assert_equal, assert_raises_rpc_error, connect_nodes, disconnect_nodes, wait_until


class RecoveryRecordTest(BitcoinTestFramework):
    def set_test_params(self):
        self.num_nodes = 6
        self.setup_clean_chain = True
        self.extra_args = [['-llmqtestfixture', '-llmqrecoverytest'] for _ in range(5)] + [['-llmqtestfixture']]
        self.extra_args[0].append('-sporkkey=cP4EKFyJsHT39LDqgdcB43Y3YXjNyjb5Fuas1GQSeAtjnZWmZEQK')
        self.online = [0, 1, 3, 5]

    def add_options(self, parser):
        parser.add_option('--recovery-devnet', action='store_true', default=False)

    def setup_chain(self):
        if self.options.recovery_devnet:
            self.num_nodes = 5
            self.online = [0, 1, 3]
            authority, private = prepare_recovery_devnet(self)
        super().setup_chain()
        if self.options.recovery_devnet:
            finish_recovery_devnet(self, authority, private)

    def setup_network(self):
        self.setup_nodes()
        for i in (2, 4):
            self.stop_node(i)
        for i in self.online[1:]:
            connect_nodes(self.nodes[0], i)
        self.sync_blocks([self.nodes[i] for i in self.online])

    def mine(self, count, miner=0):
        active = [self.nodes[i] for i in self.online]
        self.bump_mocktime(150, nodes=active)
        assert_equal(len(self.nodes[miner].generate(count)), count)
        if miner == 0:
            self.sync_blocks(active, timeout=30)

    def state(self, node=0):
        return self.nodes[node].quorum('recoverystate')

    def commitment_size(self, height):
        block = FromHex(CBlock(), self.nodes[0].getblock(self.nodes[0].getblockhash(height), False))
        for tx in block.vtx:
            if tx.nType == 6:
                qc = CFinalCommitment()
                qc.deserialize(BytesIO(tx.vExtraPayload[6:]))
                if qc.llmqType == 1:
                    return len(qc.signers)
        raise AssertionError('No type-1 commitment at height {}'.format(height))

    def funded_record(self, payload):
        node = self.nodes[0]
        tx = FromHex(CTransaction(), node.createrawtransaction([], {node.getnewaddress(): 1}))
        tx.nVersion, tx.nType = 3, 10
        tx.vExtraPayload = bytes.fromhex(payload)
        funded = node.fundrawtransaction(tx.serialize().hex())['hex']
        signed = node.signrawtransaction(funded)
        assert signed['complete']
        return signed['hex']

    def run_test(self):
        evidence = {}
        self.mine(110 - self.nodes[0].getblockcount())
        disconnect_nodes(self.nodes[0], 3)
        self.nodes[3].setnetworkactive(False)
        self.online = [0, 1] if self.options.recovery_devnet else [0, 1, 5]
        self.log.info('Authenticate a future recovery window; reject altered signature')
        assert_raises_rpc_error(-8, 'recovery-window', self.nodes[0].quorum, 'recoveryrequest', 120, 240)
        record = self.nodes[0].quorum('recoveryrequest', 120, 180)
        signed = self.funded_record(record['payload'])
        if not self.options.recovery_devnet:
            assert_raises_rpc_error(-26, 'bad-txns-type', self.nodes[5].sendrawtransaction, signed)
            self.stop_node(5)
            self.online.remove(5)
        bad = bytearray.fromhex(record['payload'])
        bad[-1] ^= 1
        assert_raises_rpc_error(-26, 'recovery-signature', self.nodes[0].sendrawtransaction,
                                self.funded_record(bad.hex()))
        self.nodes[0].sendrawtransaction(signed)
        # Today's wall-clock spork deliberately disagrees with both pre-window
        # history and post-expiry state. It must not select consensus parameters.
        self.nodes[0].spork('SPORK_21_LOW_LLMQ_PARAMS', 0)
        self.mine(1)
        boundary = self.nodes[0].getbestblockhash()
        assert_equal(self.state()['authorization'], record['authorization'])
        assert not self.state()['active']
        self.mine(9)
        assert self.state()['active']
        self.mine(11)  # include a LOW commitment before starting the fresh node
        evidence['active'] = self.state()
        self.restart_node(1)
        self.nodes[1].setmocktime(self.mocktime)
        connect_nodes(self.nodes[0], 1)
        self.sync_blocks(self.nodes[:2])
        assert_equal(self.state(1), self.state())
        self.log.info('Fresh node reconstructs active window from blocks')
        self.start_node(2)
        self.nodes[2].setmocktime(self.mocktime)
        connect_nodes(self.nodes[0], 2)
        self.online.append(2)
        self.sync_blocks([self.nodes[i] for i in self.online])
        assert_equal(self.state(2), self.state())
        self.mine(49)
        assert_equal(self.commitment_size(130), 200)
        assert_equal(self.commitment_size(160), 200)
        assert_equal(self.commitment_size(100), 3)
        assert not self.state()['active']
        self.log.info('Fresh node reconstructs expired window without an off message')
        self.start_node(4)
        self.nodes[4].setmocktime(self.mocktime)
        connect_nodes(self.nodes[0], 4)
        self.online.append(4)
        self.sync_blocks([self.nodes[i] for i in self.online])
        assert_equal(self.state(4), self.state())
        self.mine(11)
        assert_equal(self.commitment_size(190), 3)
        evidence['commitment_sizes'] = {'100': 3, '130': 200, '160': 200, '190': 3}
        evidence['expired'] = self.state()
        self.log.info('Reindex rebuilds expired authorization from blocks')
        expected = self.state()
        self.restart_node(4, self.extra_args[4] + ['-reindex'])
        self.nodes[4].setmocktime(self.mocktime)
        wait_until(lambda: self.nodes[4].getblockcount() == expected['height'], timeout=60)
        assert_equal(self.state(4), expected)
        evidence['reindexed'] = self.state(4)
        connect_nodes(self.nodes[0], 4)
        self.log.info('Invalidate/reconsider removes and restores recorded authorization')
        self.nodes[1].invalidateblock(boundary)
        assert_equal(self.state(1)['authorization'], '0' * 64)
        self.nodes[1].reconsiderblock(boundary)
        self.sync_blocks([self.nodes[i] for i in self.online])
        assert_equal(self.state(1), self.state())
        self.log.info('Higher-work branch without the record removes recovery state')
        self.nodes[3].setmocktime(self.mocktime)
        assert_equal(self.nodes[3].getblockcount(), 110)
        # Stay below the independent founder-payment boundary at height 200.
        # Legacy CheckBlock uses the active tip height when checking side branches.
        self.mine(89, miner=3)
        assert int(self.nodes[3].getblockchaininfo()['chainwork'], 16) > int(self.nodes[0].getblockchaininfo()['chainwork'], 16)
        self.nodes[3].setnetworkactive(True)
        connect_nodes(self.nodes[0], 3)
        self.online.append(3)
        self.sync_blocks([self.nodes[i] for i in self.online], timeout=60)
        for i in self.online:
            assert_equal(self.state(i)['authorization'], '0' * 64)
            assert not self.state(i)['active']
        self.restart_node(1)
        self.nodes[1].setmocktime(self.mocktime)
        connect_nodes(self.nodes[0], 1)
        self.sync_blocks([self.nodes[i] for i in self.online])
        assert_equal(self.state(1), self.state())
        evidence['winning_fork'] = self.state()
        evidence['network'] = self.chain
        evidence['fork_commitment_sizes'] = {str(h): self.commitment_size(h) for h in (130, 160, 190)}
        assert all(size == 3 for size in evidence['fork_commitment_sizes'].values())
        evidence['scope'] = 'Chain-derived null commitment replay; real DKG and signing are tested separately.'
        with open(os.path.join(self.options.tmpdir, 'recovery-evidence.json'), 'w') as output:
            json.dump(evidence, output, indent=2)
            output.write('\n')
        self.log.info('Recovery authorization replay, expiry, restart and fork rollback passed')


if __name__ == '__main__':
    RecoveryRecordTest().main()
