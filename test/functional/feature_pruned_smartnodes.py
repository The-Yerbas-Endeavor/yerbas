#!/usr/bin/env python3
"""Real DKG, signatures and ChainLocks after deleting pruned Smartnode blocks.

Four isolated regtest nodes: archival miner, two pruned operators, one archival
operator. Uses the existing small-quorum fixture, not mainnet quorum parameters.
Allow several GiB for disposable chains, synthetic wallets and stopped backups.
"""
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from shutil import copytree

from feature_llmq_manual_recovery import ManualRecovery
from test_framework.messages import CTransaction, CTxOut
from test_framework.script import CScript, OP_RETURN
from test_framework.util import assert_equal, assert_raises_rpc_error, connect_nodes, force_finish_mnsync, get_chain_folder, wait_until


class PrunedSmartnodesTest(ManualRecovery):
    def set_test_params(self):
        super().set_test_params()
        self.num_nodes = 4
        self.extra_args = [["-llmqtestfixture", "-blockmaxsize=999000", "-debug=llmq"] for _ in range(4)]
        for i in (1, 2):
            self.extra_args[i] += ["-prune=256", "-txindex=0"]

    def setup_network(self):
        # Select the ordinary three-member quorum in the existing DKG helpers.
        # No recovery records, cutover overrides or LOW_LLMQ sporks are used.
        self.options.chain_recovery = True
        self.add_nodes(self.num_nodes, self.extra_args, timewait=180)
        self.start_nodes()
        for i in (1, 2, 3):
            connect_nodes(self.nodes[0], i)
        self.sync_blocks(self.nodes)

    def set_spork(self, name, active):
        self.bump_mocktime(2)
        self.nodes[0].spork(name, 0 if active else 4070908800)
        wait_until(lambda: all(n.spork('active')[name] == active for n in self.nodes), timeout=30)

    def restart_operator(self, i, backup=False):
        self.stop_node(i)
        if backup:
            copytree(self.nodes[i].datadir, Path(self.options.tmpdir) / ('archive-backup-%d' % i))
        self.start_node(i, extra_args=self.extra_args[i])
        self.nodes[i].setmocktime(self.mocktime)
        connect_nodes(self.nodes[i], 0)
        for n in self.nodes:
            force_finish_mnsync(n)
        self.sync_blocks(self.nodes)
        for j in (1, 2, 3):
            if i != j:
                connect_nodes(self.nodes[i], j)
        wait_until(lambda: self.nodes[i].smartnode('status')['state'] == 'READY', timeout=30)

    def verify_operators(self):
        for i in (1, 2, 3):
            node = self.nodes[i]
            status = node.smartnode('status')
            assert_equal(status['state'], 'READY')
            assert_equal(status['needToUpgrade'], False)
            assert_equal(status['proTxHash'], self.registrations[i - 1])
            assert_equal(node.getbestblockhash(), self.nodes[0].getbestblockhash())
            for registration in self.registrations:
                assert_equal(node.protx('info', registration)['state'],
                             self.nodes[0].protx('info', registration)['state'])

    def recovered_signature(self, byte):
        request, message = byte * 64, 'f' * 64
        # Only the two pruned operators submit signing requests.
        for i in (1, 2):
            assert self.nodes[i].quorum('sign', 1, request, message)
        wait_until(lambda: all(n.quorum('hasrecsig', 1, request, message) for n in self.nodes), timeout=45)
        recovered = self.nodes[0].quorum('getrecsig', 1, request, message)
        for n in self.nodes[1:]:
            assert_equal(n.quorum('getrecsig', 1, request, message), recovered)

    def chainlock(self):
        self.mine(1)
        blockhash = self.nodes[0].getbestblockhash()
        wait_until(lambda: all(n.getblock(blockhash).get('chainlock') is True for n in self.nodes), timeout=60)
        for n in self.nodes:
            lock = n.getbestchainlock()
            assert_equal(lock['blockhash'], blockhash)
            assert_equal(lock['known_block'], True)

    def run_test(self):
        controller = self.nodes[0]
        self.mine(110)
        self.register_operators()
        # Preserve the test-generated operator identity through later restarts.
        for i in (1, 2, 3):
            self.extra_args[i] += [a for a in self.nodes[i].process.args if a.startswith('-smartnodeblsprivkey=')]
        self.verify_operators()
        self.set_spork('SPORK_17_QUORUM_DKG_ENABLED', True)
        original = self.dkg(3)
        assert all(member['valid'] for member in original['members'])
        self.mine(8)
        self.recovered_signature('1')
        self.set_spork('SPORK_17_QUORUM_DKG_ENABLED', False)

        self.log.info('Build enough real block data to delete the original mined commitment block')
        collateral = {(n.smartnode('status')['collateralHash'], n.smartnode('status')['collateralIndex']) for n in self.nodes[1:]}
        utxos, address = [], controller.getnewaddress()
        script = CScript([OP_RETURN, b'\x01' * 512])
        for count in range(300):
            if len(utxos) < 14:
                utxos = [u for u in controller.listunspent() if (u['txid'], u['vout']) not in collateral]
            for _ in range(14):
                coin = utxos.pop()
                raw = controller.createrawtransaction([{'txid': coin['txid'], 'vout': coin['vout']}],
                                                     {address: coin['amount'] - Decimal('0.01')})
                tx = CTransaction()
                tx.deserialize(BytesIO(bytes.fromhex(raw)))
                tx.vout.extend(CTxOut(0, script) for _ in range(128))
                signed = controller.signrawtransaction(tx.serialize().hex())
                assert signed['complete']
                controller.sendrawtransaction(signed['hex'], True)
            self.mine(1)
            assert_equal(controller.getrawmempool(), [])
            if (count + 1) % 50 == 0:
                self.log.info('Mined %d/300 large blocks', count + 1)
        self.mine(1100 - controller.getblockcount())
        for i in (1, 2):
            self.restart_operator(i, backup=True)
            node = self.nodes[i]
            assert node.getblockchaininfo()['pruned']
            assert node.getblockchaininfo()['pruneheight'] > 1
            assert_raises_rpc_error(-1, 'pruned data', node.getblock, original['minedBlock'])
            evidence = node.quorum('verifyprunedevidence')
            assert evidence['verified'] and evidence['commitments_matched'] > 0
            assert_equal(node.quorum('info', 1, original['quorumHash'])['minedBlock'], original['minedBlock'])
            data = Path(node.datadir) / get_chain_folder(node.datadir, node.chain)
            self.log.info('Pruned operator %d block files: %s', i,
                          {p.name: p.stat().st_size for p in (data / 'blocks').glob('*.dat')})
        assert controller.getblock(original['minedBlock'])
        assert self.nodes[3].getblock(original['minedBlock'])
        self.verify_operators()

        self.log.info('Real DKG and signing after physical block deletion')
        self.set_spork('SPORK_17_QUORUM_DKG_ENABLED', True)
        for _ in range(4):
            quorum = self.dkg(3)
            assert all(m['valid'] for m in quorum['members'])
        self.mine(8)
        self.recovered_signature('2')
        self.set_spork('SPORK_19_CHAINLOCKS_ENABLED', True)
        self.chainlock()
        self.verify_operators()

        self.log.info('Restart pruned operators and require fresh signing and ChainLocks')
        for i in (1, 2):
            self.restart_operator(i)
            assert self.nodes[i].quorum('verifyprunedevidence')['verified']
        # Quorum connections are restored by UpdatedBlockTip after blockchain
        # sync completes. Advance the chain as the live network would do.
        self.mine(1)
        wait_until(lambda: all(sum(bool(p.get('verified_proregtx_hash'))
                                   for p in self.nodes[i].getpeerinfo()) >= 2
                               for i in (1, 2, 3)), timeout=45)
        self.recovered_signature('3')
        self.chainlock()
        self.verify_operators()


if __name__ == '__main__':
    PrunedSmartnodesTest().main()
