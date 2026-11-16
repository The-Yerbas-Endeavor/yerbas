#!/usr/bin/env python3
"""Real three-member DKG under size-200/threshold-two LOW_LLMQ.

No synthetic commitments: operator nodes exchange contributions and signatures.
The small regtest quorum also runs; report all mined commitments when attributing
penalties. This does not establish security of a two-signer mainnet quorum.
"""
import json
from pathlib import Path

from test_framework.recovery_devnet import prepare_recovery_devnet, finish_recovery_devnet
from test_framework.messages import CTransaction, FromHex
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import assert_equal, connect_nodes, force_finish_mnsync, p2p_port, wait_until


class LowLLMQPoSeTest(BitcoinTestFramework):
    def set_test_params(self):
        self.num_nodes = 4
        self.setup_clean_chain = True
        self.extra_args = [["-llmqtestfixture", "-debug=llmq-dkg", "-debug=llmq"] for _ in range(4)]
        self.extra_args[0].append("-sporkkey=cP4EKFyJsHT39LDqgdcB43Y3YXjNyjb5Fuas1GQSeAtjnZWmZEQK")
        self.online = [0, 1, 2, 3]
        self.evidence = []

    def add_options(self, parser):
        parser.add_option('--chain-recovery', action='store_true', default=False)
        parser.add_option('--recovery-devnet', action='store_true', default=False)

    def setup_chain(self):
        self.recovery_start = 120
        self.recovery_end = 180
        self.collateral = 10
        if self.options.recovery_devnet:
            self.options.chain_recovery = True
            self.chain = 'devnet'
            self.recovery_start = 750
            self.recovery_end = 840
            self.collateral = 4000
        if self.options.chain_recovery:
            self.num_nodes = 5
            self.extra_args.append(['-llmqtestfixture'])
            for args in self.extra_args:
                args.append('-llmqrecoverytest')
        if self.options.recovery_devnet:
            authority, private = prepare_recovery_devnet(self)
        super().setup_chain()
        if self.options.recovery_devnet:
            finish_recovery_devnet(self, authority, private)

    def setup_network(self):
        self.setup_nodes()
        if self.options.chain_recovery:
            self.stop_node(4)
        for i in range(1, 4):
            connect_nodes(self.nodes[0], i)
        self.sync_blocks(self.nodes[:4], timeout=30)

    def mine(self, count):
        active = [self.nodes[i] for i in self.online]
        self.bump_mocktime(1, nodes=active)
        assert_equal(len(self.nodes[0].generate(count)), count)
        self.sync_blocks(active, timeout=30)

    def session(self, node):
        return node.quorum("dkgstatus", 2).get("session", {}).get("llmq_3_60" if self.options.chain_recovery else "llmq_3_200", {})

    def wait_phase(self, quorum_hash, phase, contributions=None):
        def ready():
            for i in self.online[1:]:
                status = self.session(self.nodes[i])
                if status.get("quorumHash") != quorum_hash or status.get("phase") != phase:
                    return False
                if contributions is not None and len(status.get("receivedContributions", [])) != contributions:
                    return False
            return True
        wait_until(ready, timeout=45)

    def dkg(self, contributors):
        self.mine(30 - self.nodes[0].getblockcount() % 30)
        quorum_hash = self.nodes[0].getbestblockhash()
        if self.options.chain_recovery and self.nodes[0].getblockcount() == self.recovery_end:
            assert not self.nodes[0].quorum('recoverystate')['active']
            for i in self.online[1:]:
                assert not self.nodes[i].quorum('sign', 1, '22' * 32, '33' * 32)
            self.log.info('Expired low quorums cannot sign before a normal replacement exists')
        self.wait_phase(quorum_hash, 1)
        self.mine(2)
        self.wait_phase(quorum_hash, 2, contributors)
        self.mine(2)
        self.wait_phase(quorum_hash, 3)
        self.mine(2)
        self.wait_phase(quorum_hash, 4)
        self.mine(2)
        self.wait_phase(quorum_hash, 5)
        wait_until(lambda: all(len(self.session(self.nodes[i]).get('receivedPrematureCommitments', []))
                               == contributors for i in self.online[1:]), timeout=45)
        self.mine(2)
        self.wait_phase(quorum_hash, 6)
        def has_commitment():
            qc = self.nodes[0].quorum("dkgstatus").get("minableCommitments", {}).get("llmq_3_60" if self.options.chain_recovery else "llmq_3_200", {})
            return qc.get("quorumHash") == quorum_hash and qc.get("signersCount", 0) >= 2
        wait_until(has_commitment, timeout=45)
        self.mine(1)
        info = self.nodes[0].quorum("info", 1, quorum_hash)
        block = self.nodes[0].getblock(info['minedBlock'], 2)
        self.evidence.append(dict(quorum=info, transactions=block['tx'],
                                  states=[self.nodes[0].protx('info', h)['state'] for h in self.registrations]))
        (Path(self.options.tmpdir) / 'pose-evidence.json').write_text(json.dumps(self.evidence, indent=2, default=str))
        return info

    def run_test(self):
        controller = self.nodes[0]
        controller.spork('SPORK_21_LOW_LLMQ_PARAMS', 0)  # deliberately remains ON through chain-derived expiry
        controller.spork('SPORK_17_QUORUM_DKG_ENABLED', 0)
        wait_until(lambda: all(n.spork('active')['SPORK_21_LOW_LLMQ_PARAMS'] and
                               n.spork('active')['SPORK_17_QUORUM_DKG_ENABLED'] for n in self.nodes[:4]))
        self.mine((self.recovery_start - 11 if self.options.chain_recovery else 110) - controller.getblockcount())
        if self.options.chain_recovery:
            record = controller.quorum('recoveryrequest', self.recovery_start, self.recovery_end)
            tx = FromHex(CTransaction(), controller.createrawtransaction([], {controller.getnewaddress(): 1}))
            tx.nVersion, tx.nType = 3, 10
            tx.vExtraPayload = bytes.fromhex(record['payload'])
            funded = controller.fundrawtransaction(tx.serialize().hex())['hex']
            signed = controller.signrawtransaction(funded)
            assert signed['complete']
            controller.sendrawtransaction(signed['hex'])
            self.mine(1)
        self.registrations = []
        keys = []
        for i in range(1, 4):
            key = controller.bls('generate')
            keys.append(key['secret'])
            funding = controller.getnewaddress()
            controller.sendtoaddress(funding, self.collateral + 1)
            self.mine(1)
            protx = controller.protx('register_fund', funding, self.collateral, '127.0.0.1:%d' % p2p_port(i),
                                     controller.getnewaddress(), key['public'], controller.getnewaddress(),
                                     0, controller.getnewaddress(), funding)
            self.registrations.append(protx)
            self.mine(2)
        for i in range(1, 4):
            self.restart_node(i, self.extra_args[i] + ['-smartnodeblsprivkey=' + keys[i-1]])
            self.nodes[i].setmocktime(self.mocktime)
            # Unsynced smartnodes reject inbound peers. Bootstrap outbound,
            # and require the intended peer (the generic helper permits none).
            connect_nodes(self.nodes[i], 0)
            wait_until(lambda: any('testnode0' in peer['subver'] and peer['version'] != 0
                                   for peer in self.nodes[i].getpeerinfo()), timeout=30)
        for node in self.nodes[:4]:
            force_finish_mnsync(node)
        self.sync_blocks(self.nodes[:4], timeout=30)
        self.log.info('Real LOW_LLMQ DKG with three online operators')
        healthy = self.dkg(3)
        assert_equal(len(healthy['members']), 3)
        assert all(member['valid'] for member in healthy['members'])
        for h in self.registrations:
            state = controller.protx('info', h)['state']
            assert_equal(state['PoSePenalty'], 0)
            assert_equal(state['PoSeBanHeight'], -1)
        if self.options.chain_recovery:
            self.mine(8)
            for i in (1, 2):
                assert self.nodes[i].quorum('sign', 1, '11' * 32, '44' * 32)
            wait_until(lambda: controller.quorum('hasrecsig', 1, '11' * 32, '44' * 32), timeout=45)
            assert_equal(controller.quorum('getrecsig', 1, '11' * 32, '44' * 32)['quorumHash'], healthy['quorumHash'])
            self.log.info('Real recovered signature produced under chain-authorized recovery')
        self.stop_node(3)
        self.online = [0, 1, 2]
        self.log.info('Real LOW_LLMQ DKG with two operators and one offline selected member')
        failed = self.dkg(2)
        target = next(member for member in failed['members'] if member['proTxHash'] == self.registrations[2])
        assert not target['valid']
        assert controller.protx('info', self.registrations[2])['state']['PoSePenalty'] > 0
        # Other quorum types may also punish this identity; record each block.
        for _ in range(3):
            if controller.protx('info', self.registrations[2])['state']['PoSeBanHeight'] != -1:
                break
            self.dkg(2)
        assert controller.protx('info', self.registrations[2])['state']['PoSeBanHeight'] != -1
        self.log.info('Selected offline identity received penalties and a PoSe ban')
        after_ban = self.dkg(2)
        assert_equal(len(after_ban['members']), 2)
        assert all(member['valid'] and member['proTxHash'] != self.registrations[2]
                   for member in after_ban['members'])
        if self.options.chain_recovery:
            assert_equal(after_ban['type'], 'llmq_3_60')
            self.mine(8)
            for i in (1, 2):
                assert self.nodes[i].quorum('sign', 1, '55' * 32, '66' * 32)
            wait_until(lambda: controller.quorum('hasrecsig', 1, '55' * 32, '66' * 32), timeout=45)
            assert_equal(controller.quorum('getrecsig', 1, '55' * 32, '66' * 32)['quorumHash'], after_ban['quorumHash'])
            self.log.info('Normal quorum excludes banned identity and restores signing after expiry')
            self.log.info('Fresh node replays real signed commitments and the PoSe ban after expiry')
            self.start_node(4)
            self.nodes[4].setmocktime(self.mocktime)
            connect_nodes(controller, 4)
            self.sync_blocks([self.nodes[i] for i in (0, 1, 2, 4)], timeout=60)
            for h in self.registrations:
                assert_equal(self.nodes[4].protx('info', h)['state'], controller.protx('info', h)['state'])
            for q in (healthy, failed, after_ban):
                assert_equal(self.nodes[4].quorum('info', 1, q['quorumHash'])['type'], q['type'])
            if self.options.recovery_devnet:
                for reindex in (False, True):
                    self.restart_node(4, self.extra_args[4] + (['-reindex'] if reindex else []))
                    self.nodes[4].setmocktime(self.mocktime)
                    connect_nodes(controller, 4)
                    self.sync_blocks([controller, self.nodes[4]], timeout=60)
                    assert_equal(self.nodes[4].quorum('recoverystate'), controller.quorum('recoverystate'))
                    for h in self.registrations:
                        assert_equal(self.nodes[4].protx('info', h)['state'], controller.protx('info', h)['state'])
                self.log.info('Isolated devnet restart and full reindex preserve recovery and PoSe state')
            signing = dict(
                during_recovery=controller.quorum('getrecsig', 1, '11' * 32, '44' * 32),
                after_expiry=controller.quorum('getrecsig', 1, '55' * 32, '66' * 32),
                expired_without_replacement_rejected=True,
                restart_and_reindex_checked=self.options.recovery_devnet,
                fresh_node_tip=self.nodes[4].getbestblockhash(),
                fresh_node_height=self.nodes[4].getblockcount())
            (Path(self.options.tmpdir) / 'recovery-signing-evidence.json').write_text(json.dumps(signing, indent=2))
        else:
            self.log.info('Next LOW_LLMQ excludes the banned identity and finalizes with two operators')


if __name__ == '__main__':
    LowLLMQPoSeTest().main()
