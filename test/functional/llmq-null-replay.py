#!/usr/bin/env python3
"""Replay null commitments after LOW_LLMQ switches, without importing chainstate."""
import io
import hashlib
import os
from pathlib import Path
from test_framework.key import CECKey
from test_framework.messages import CFinalCommitment, CTransaction, FromHex
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import assert_equal, connect_nodes

class NullCommitmentReplayTest(BitcoinTestFramework):
    def set_test_params(self):
        self.num_nodes = 3
        self.setup_clean_chain = True
        self.extra_args = [['-llmqtestfixture'] for _ in range(3)]

    def setup_chain(self):
        super().setup_chain()
        # A fresh regtest authority per run; no private key is embedded in source.
        secret = os.urandom(32)
        key = CECKey()
        key.set_secretbytes(secret)

        def base58(payload):
            data = payload + hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
            number, text = int.from_bytes(data, 'big'), ''
            alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
            while number:
                number, remainder = divmod(number, 58)
                text = alphabet[remainder] + text
            return '1' * (len(data) - len(data.lstrip(b'\0'))) + text

        authority = base58(bytes([140]) + hashlib.new('ripemd160', hashlib.sha256(key.get_pubkey()).digest()).digest())
        private = base58(bytes([239]) + secret)
        for i in range(self.num_nodes):
            config = Path(self.options.tmpdir) / ('node%d' % i) / 'yerbas.conf'
            config.chmod(0o600)
            with config.open('a') as output:
                output.write('sporkaddr=' + authority + '\nsporkkey=' + private + '\n')

    def setup_network(self):
        self.setup_nodes()
        self.stop_node(1)
        self.stop_node(2)

    def type_one_sizes(self, block_hashes):
        sizes = set()
        for h in block_hashes:
            for tx in self.nodes[0].getblock(h, 2)['tx']:
                if 'qcTx' not in tx:
                    continue
                raw = FromHex(CTransaction(), tx['hex'])
                # Payload: uint16 version, uint32 height, then commitment.
                qc = CFinalCommitment()
                qc.deserialize(io.BytesIO(raw.vExtraPayload[6:]))
                if qc.llmqType == 1:
                    assert not any(qc.signers) and not any(qc.validMembers)
                    sizes.add(len(qc.signers))
        return sizes

    def run_test(self):
        controller = self.nodes[0]
        self.bump_mocktime(1, nodes=[controller])
        normal = controller.generate(60)
        assert_equal(self.type_one_sizes(normal), {3})
        self.bump_mocktime(1, nodes=[controller])
        controller.spork('SPORK_21_LOW_LLMQ_PARAMS', 0)
        low = controller.generate(60)
        assert_equal(self.type_one_sizes(low), {200})

        for i, value in ((1, 0), (2, 4070908800)):
            self.start_node(i)
            self.nodes[i].setmocktime(self.mocktime)
            # Set the current spork before downloading even the first block.
            self.nodes[i].spork('SPORK_21_LOW_LLMQ_PARAMS', value)
            # For the OFF case, make the controller advertise the same state.
            if i == 2:
                self.bump_mocktime(1, nodes=[controller, self.nodes[i]])
                controller.spork('SPORK_21_LOW_LLMQ_PARAMS', value)
            connect_nodes(self.nodes[i], 0)
            self.sync_blocks([controller, self.nodes[i]], timeout=45)
            assert_equal(self.nodes[i].getbestblockhash(), controller.getbestblockhash())
            self.restart_node(i, self.extra_args[i] + ['-reindex'])
            self.nodes[i].setmocktime(self.mocktime)
            connect_nodes(self.nodes[i], 0)
            self.sync_blocks([controller, self.nodes[i]], timeout=45)
            assert_equal(self.nodes[i].getbestblockhash(), controller.getbestblockhash())
            self.log.info('Fresh sync and full reindex passed with LOW_LLMQ %s', 'ON' if value == 0 else 'OFF')
            self.stop_node(i)

if __name__ == '__main__':
    NullCommitmentReplayTest().main()
