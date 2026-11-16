#!/usr/bin/env python3
"""Founder payments use branch height, including duplicate P2P delivery."""
from test_framework.blocktools import network_thread_start
from test_framework import messages
from test_framework.messages import CBlock, FromHex, msg_block, msg_ping
from test_framework.mininode import P2PInterface
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import assert_equal, wait_until


class FounderPaymentContextTest(BitcoinTestFramework):
    def set_test_params(self):
        self.num_nodes = 2
        self.setup_clean_chain = True
        self.extra_args = [['-llmqtestfixture', '-connect=0'] for _ in range(2)]

    def setup_network(self):
        self.setup_nodes()  # Deliberately independent branches.

    def run_test(self):
        node, fork = self.nodes
        self.bump_mocktime(150, nodes=self.nodes)
        node.generate(230)
        original_tip = node.getbestblockhash()
        # This legacy harness defaults to a protocol version the daemon rejects.
        messages.MY_VERSION = node.getnetworkinfo()['protocolversion']
        peer = node.add_p2p_connection(P2PInterface())
        network_thread_start()
        peer.wait_for_verack()
        self.log.info('Re-deliver pre-founder block while active tip requires payments')
        block = FromHex(CBlock(), node.getblock(node.getblockhash(200), False))
        peer.send_message(msg_block(block))
        peer.send_message(msg_ping(123))
        wait_until(lambda: 'reject' in peer.last_message or not peer.is_connected or
                   ('pong' in peer.last_message and peer.last_message['pong'].nonce == 123), timeout=10)
        assert 'reject' not in peer.last_message
        assert peer.is_connected
        assert_equal(node.getbestblockhash(), original_tip)

        self.log.info('Accept a lower-height side branch across payment activation')
        self.bump_mocktime(300, nodes=[fork])
        fork.generate(205)
        for h in range(1, 206):
            fork_hash = fork.getblockhash(h)
            result = node.submitblock(fork.getblock(fork_hash, False))
            # An accepted side branch has no BlockChecked activation callback.
            assert result in (None, 'inconclusive'), result
            assert_equal(node.getblock(fork_hash)['height'], h)
        assert_equal(node.getbestblockhash(), original_tip)

        self.log.info('Still reject a fresh block with its required founder output removed')
        self.bump_mocktime(150, nodes=[node])
        valid_hash = node.generate(1)[0]
        bad = FromHex(CBlock(), node.getblock(valid_hash, False))
        node.invalidateblock(valid_hash)
        assert len(bad.vtx[0].vout) > 1
        # Mining puts the founder output last for this no-smartnode fixture.
        bad.vtx[0].vout.pop()
        bad.vtx[0].rehash()
        bad.hashMerkleRoot = bad.calc_merkle_root()
        # Ask the real daemon to check Yerbas PoW; the legacy Python solve()
        # helper implements Dash's hash instead of Yerbas' HashGR.
        for nonce in range(256):
            bad.nNonce = nonce
            result = node.submitblock(bad.serialize().hex())
            if result != 'high-hash':
                break
        assert_equal(result, 'bad-cb-founder-payment-not-found')
        node.reconsiderblock(valid_hash)
        assert_equal(node.getbestblockhash(), valid_hash)
        self.restart_node(0, self.extra_args[0] + ['-reindex'])
        wait_until(lambda: self.nodes[0].getbestblockhash() == valid_hash, timeout=60)
        assert self.nodes[0].verifychain(4, 0)
        self.log.info('Duplicate, side-branch, invalid-payment and reindex checks passed')


if __name__ == '__main__':
    FounderPaymentContextTest().main()
