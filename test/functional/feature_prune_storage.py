#!/usr/bin/env python3
"""Exercise real automatic file deletion at 256 MiB, evidence and restart.

Uses roughly 1.5 GiB of disposable data including the archival backup.
No peers, operator keys or quorums.
Unlike the small migration test, this crosses both the height and size limits.
"""
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from shutil import copytree

from test_framework.messages import CTransaction, CTxOut
from test_framework.script import CScript, OP_RETURN
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import assert_equal, assert_raises_rpc_error, get_chain_folder


class PruneStorageTest(BitcoinTestFramework):
    def set_test_params(self):
        self.num_nodes = 1
        self.setup_clean_chain = True
        self.common_args = ["-disablegovernance", "-blockmaxsize=999000",
                            "-dip3params=10000:10000", "-dip8params=10000"]
        self.extra_args = [self.common_args + ["-txindex=1"]]

    def setup_network(self):
        self.add_nodes(self.num_nodes, self.extra_args, timewait=180)
        self.start_nodes()

    def mine(self, count):
        # Space regtest blocks so DGW does not turn a storage test into a
        # progressively harder proof-of-work benchmark.
        for _ in range(count):
            self.bump_mocktime(150)
            assert_equal(len(self.nodes[0].generate(1)), 1)

    def disk_usage(self, label):
        # Avoid counting blocks/index twice. Report actual allocated disk bytes
        # as well as logical lengths (block files may be preallocated).
        result = {}
        for path in self.data.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(self.data)
            group = "blocks/index" if relative.parts[:2] == ("blocks", "index") else relative.parts[0]
            apparent, allocated = result.get(group, (0, 0))
            stat = path.stat()
            result[group] = (apparent + stat.st_size, allocated + stat.st_blocks * 512)
        self.log.info("Storage %s (apparent, allocated bytes): %s", label, result)
        return result

    def run_test(self):
        node = self.nodes[0]
        self.data = Path(node.datadir) / get_chain_folder(node.datadir, node.chain)
        self.mine(700)
        historical = node.getblockhash(1)
        address = node.getnewaddress()
        script = CScript([OP_RETURN, b"\x01" * 512])
        utxos = []
        self.log.info("Building >256 MiB of archival block data")
        for block_number in range(300):
            if len(utxos) < 14:
                utxos = node.listunspent()
            for _ in range(14):
                coin = utxos.pop()
                raw = node.createrawtransaction(
                    [{"txid": coin["txid"], "vout": coin["vout"]}],
                    {address: coin["amount"] - Decimal("0.01")})
                tx = CTransaction()
                tx.deserialize(BytesIO(bytes.fromhex(raw)))
                tx.vout.extend(CTxOut(0, script) for _ in range(128))
                signed = node.signrawtransaction(tx.serialize().hex())
                assert_equal(signed["complete"], True)
                node.sendrawtransaction(signed["hex"], True)
            self.mine(1)
            assert_equal(node.getrawmempool(), [])
            if (block_number + 1) % 50 == 0:
                self.log.info("Mined %d/300 large blocks", block_number + 1)
        # Age the large blocks out of the protected 288-block window.
        self.mine(300)
        height, tip = node.getblockcount(), node.getbestblockhash()
        retained = [node.getblockhash(h) for h in range(height - 287, height + 1)]
        utxo_before = node.gettxoutsetinfo()
        self.stop_node(0)
        before = self.disk_usage("archival")
        files_before = set((self.data / "blocks").glob("blk*.dat"))
        assert before["blocks"][0] > 256 * 1024 * 1024
        assert len(files_before) >= 3

        copytree(self.data, Path(self.options.tmpdir) / "archival-backup")

        self.log.info("Convert archive: automatic pruning must actually delete files")
        args = self.common_args + ["-txindex=0", "-prune=256"]
        self.start_node(0, extra_args=args)
        assert_equal(node.getblockcount(), height)
        assert_equal(node.getbestblockhash(), tip)
        assert_equal(node.getblockchaininfo()["pruned"], True)
        assert node.getblockchaininfo()["pruneheight"] > 1
        assert files_before - set((self.data / "blocks").glob("blk*.dat"))
        assert_raises_rpc_error(-1, "pruned data", node.getblock, historical)
        for blockhash in retained:
            assert_equal(node.getblock(blockhash)["hash"], blockhash)
        assert_equal(node.gettxoutsetinfo()["hash_serialized_2"], utxo_before["hash_serialized_2"])
        evidence = node.quorum("verifyprunedevidence")
        assert_equal(evidence["verified"], True)
        assert_equal(evidence["blocks_checked"], height)
        # No quorum members exist in this isolated fixture; do not claim DKG coverage.
        assert_equal(evidence["commitments_matched"], 0)
        rebuilt = node.quorum("testrebuildprunedindex")
        assert_equal(rebuilt["rebuilt"], True)
        self.stop_node(0)
        after = self.disk_usage("pruned")
        assert after["blocks"][0] < before["blocks"][0]
        assert after["blocks"][1] < before["blocks"][1]
        # This fixture ages its large blocks beyond the retention window.
        # The target is not a hard cap for arbitrary workloads.
        assert after["blocks"][0] < 256 * 1024 * 1024

        self.start_node(0, extra_args=args)
        assert_equal(node.getbestblockhash(), tip)
        assert_raises_rpc_error(-1, "pruned data", node.getblock, historical)
        assert_equal(node.quorum("verifyprunedevidence")["verified"], True)
        self.mine(10)
        assert_equal(node.getblockcount(), height + 10)
        assert_equal(node.quorum("verifyprunedevidence")["blocks_checked"], height + 10)


if __name__ == "__main__":
    PruneStorageTest().main()
