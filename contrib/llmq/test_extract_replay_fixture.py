#!/usr/bin/env python3
"""Tests for rejecting malformed/incorrectly anchored replay fixtures."""
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import extract_replay_fixture as extract
from test_framework.messages import CBlock, CTransaction, CTxIn, CTxOut, ser_compact_size


def block(previous=0):
    result = CBlock()
    result.nTime = 1
    result.nBits = 0x207fffff
    result.hashPrevBlock = previous
    tx = CTransaction()
    tx.vin = [CTxIn()]
    tx.vout = [CTxOut(1, b'\x51')]
    result.vtx = [tx]
    result.hashMerkleRoot = result.calc_merkle_root()
    return result


def framed(value):
    raw = value.serialize()
    return extract.MAGIC + struct.pack('<I', len(raw)) + raw


class ReplayFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'archive'
        self.source.mkdir()
        self.genesis = block()
        self.genesis_hash = extract.hash256(self.genesis.serialize()[:80])
        self.next = block(int.from_bytes(self.genesis_hash, 'little'))
        self.next_hash = extract.hash256(self.next.serialize()[:80])[::-1].hex()
        self.archive = self.source / 'blk00000.dat'
        self.archive.write_bytes(framed(self.genesis) + framed(self.next) + bytes(16))

    def run_extract(self, height=1):
        with patch.object(extract, 'GENESIS', self.genesis_hash[::-1].hex()):
            return extract.extract(self.source, self.next_hash, height, self.root / 'output')

    def test_anchored_fixture_and_no_source_mutation(self):
        before = self.archive.read_bytes()
        result = self.run_extract()
        self.assertEqual(result['block_count'], 2)
        self.assertEqual(self.archive.read_bytes(), before)
        self.assertEqual((self.root / 'output/blocks.dat').read_bytes(), before[:-16])
        manifest = json.loads((self.root / 'output/manifest.json').read_text())
        self.assertFalse(manifest['consensus_validated'])
        self.assertEqual(manifest['anchor_hash'], self.next_hash)

    def test_out_of_order_archive(self):
        self.archive.write_bytes(framed(self.next) + framed(self.genesis))
        self.assertEqual(self.run_extract()['block_count'], 2)
        self.assertEqual((self.root / 'output/blocks.dat').read_bytes(),
                         framed(self.genesis) + framed(self.next))

    def test_summary_only_verifies_without_copying_blocks(self):
        qc = CTransaction()
        qc.nVersion, qc.nType = 3, 6
        qc.vExtraPayload = (struct.pack('<HiHB', 1, 1, 1, 1) + bytes(32) +
                            ser_compact_size(200) + bytes(25) +
                            ser_compact_size(200) + bytes(25) + bytes(272))
        self.next.vtx.append(qc)
        self.next.hashMerkleRoot = self.next.calc_merkle_root()
        self.next_hash = extract.hash256(self.next.serialize()[:80])[::-1].hex()
        self.archive.write_bytes(framed(self.genesis) + framed(self.next))
        full = self.run_extract()
        with patch.object(extract, 'GENESIS', self.genesis_hash[::-1].hex()):
            summary = extract.extract(self.source, self.next_hash, 1, self.root / 'summary', True)
        self.assertEqual(full, summary)
        self.assertFalse((self.root / 'summary/blocks.dat').exists())
        manifest = json.loads((self.root / 'summary/manifest.json').read_text())
        self.assertFalse(manifest['fixture_written'])
        self.assertNotIn('blocks', manifest)
        self.assertEqual(manifest['commitment_count'], 1)
        self.assertEqual(manifest['size_transitions'][0]['signers_size'], 200)
        self.assertEqual(manifest['size_transitions'][0]['height'], 1)

    def test_wrong_checkpoint_height_rejected(self):
        with self.assertRaisesRegex(ValueError, 'height|Height'):
            self.run_extract(2)

    def test_missing_ancestor_rejected(self):
        self.archive.write_bytes(framed(self.next))
        with self.assertRaisesRegex(ValueError, 'Missing ancestor'):
            self.run_extract()

    def test_bad_merkle_rejected(self):
        self.next.vtx[0].vout[0].nValue = 2
        self.archive.write_bytes(framed(self.genesis) + framed(self.next))
        with self.assertRaisesRegex(ValueError, 'Merkle mismatch'):
            self.run_extract()

    def test_truncated_record_rejected(self):
        self.archive.write_bytes(framed(self.genesis) + framed(self.next)[:-1])
        with self.assertRaisesRegex(ValueError, 'Truncated record'):
            self.run_extract()

    def test_commitment_sizes_and_truncation(self):
        raw = struct.pack('<HiHB', 1, 70, 1, 1) + bytes(32)
        raw += ser_compact_size(200) + bytes(25)
        raw += ser_compact_size(200) + bytes(25) + bytes(272)
        summary = extract.commitment_summary(raw)
        self.assertEqual(summary['signers_size'], 200)
        self.assertTrue(summary['null'])
        with self.assertRaises(ValueError):
            extract.commitment_summary(raw[:-1])
        with self.assertRaises(ValueError):
            extract.commitment_summary(raw + b'\0')
        with self.assertRaisesRegex(ValueError, 'padding'):
            extract.bitset(io.BytesIO(b'\x03\x80'))


if __name__ == '__main__':
    unittest.main()
