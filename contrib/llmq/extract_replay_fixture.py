#!/usr/bin/env python3
"""Extract checkpoint-anchored blocks from a local archive without opening its DBs.

The manifest describes serialized commitments, not inferred consensus settings.
Extraction verifies ancestry and transaction Merkle roots, not PoW or signatures;
run the daemon offline against the fixture for consensus validation.
"""
import argparse
from contextlib import nullcontext
import hashlib
import io
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'test' / 'functional'))
from test_framework.messages import CBlock, deser_compact_size

GENESIS = 'eff0bbe5c1bbe1ef8da54822a18f528d6dc58232990bdb86e0a77ab2814ed12c'
MAGIC = b'yerb'


def hash256(data):
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def read_exact(stream, size):
    data = stream.read(size)
    if len(data) != size:
        raise ValueError('Truncated record')
    return data


def bitset(stream):
    size = deser_compact_size(stream)
    if size > 10000:
        raise ValueError('Unreasonable commitment vector size')
    raw = read_exact(stream, (size + 7) // 8)
    if size % 8 and raw[-1] >> (size % 8):
        raise ValueError('Nonzero bitset padding')
    return size, sum(value.bit_count() for value in raw)


def commitment_summary(payload):
    stream = io.BytesIO(payload)
    version, height, qc_version, kind = struct.unpack('<HiHB', read_exact(stream, 9))
    quorum_hash = read_exact(stream, 32)[::-1].hex()
    signers_size, signers = bitset(stream)
    members_size, members = bitset(stream)
    # Public key (48), vvec hash (32), quorum/member signatures (96 each).
    tail = read_exact(stream, 272)
    if stream.read(1):
        raise ValueError('Unexpected commitment payload suffix')
    return dict(payload_version=version, height=height, version=qc_version,
                type=kind, quorum_hash=quorum_hash, signers_size=signers_size,
                members_size=members_size, signers=signers, valid_members=members,
                null=not (signers or members or any(tail)))


def extract(blocks_dir, anchor_hash, anchor_height, output_dir, summary_only=False):
    index = {}
    anchor = bytes.fromhex(anchor_hash)[::-1]
    for path in sorted(blocks_dir.glob('blk[0-9][0-9][0-9][0-9][0-9].dat')):
        with path.open('rb') as source:
            while True:
                offset = source.tell()
                framing = source.read(8)
                if not framing or framing == bytes(8):
                    break  # preallocated tail
                if len(framing) != 8 or framing[:4] != MAGIC:
                    raise ValueError(f'Unexpected framing: {path}:{offset}')
                size = struct.unpack('<I', framing[4:])[0]
                if not 81 <= size <= 4000000:
                    raise ValueError(f'Unexpected block size: {size}')
                header = read_exact(source, 80)
                block_hash = hash256(header)
                index[block_hash] = (path, offset, size, header[4:36])
                source.seek(size - 80, 1)
        # Disk records need not be in chain order. A checkpoint can precede
        # some ancestors, so only stop after the complete ancestry is indexed.
        current = anchor
        seen = set()
        while current in index and current not in seen:
            seen.add(current)
            current = index[current][3]
        if current == bytes(32):
            break
    if anchor not in index:
        raise ValueError('Requested checkpoint not found')
    chain = []
    current = anchor
    while current != bytes(32):
        if current not in index:
            raise ValueError('Missing ancestor')
        chain.append((current, index[current]))
        current = index[current][3]
        if len(chain) > anchor_height + 1:
            raise ValueError('Checkpoint height/ancestry mismatch')
    chain.reverse()
    if len(chain) != anchor_height + 1 or chain[0][0][::-1].hex() != GENESIS:
        raise ValueError('Wrong height or genesis')
    output_dir.mkdir(parents=True, exist_ok=False)
    commitments = []
    transitions = []
    previous_sizes = {}
    commitment_count = 0
    rows = []
    digest = hashlib.sha256()
    with (nullcontext(None) if summary_only else (output_dir / 'blocks.dat').open('wb')) as fixture:
        for height, (block_hash, (path, offset, size, _)) in enumerate(chain):
            with path.open('rb') as source:
                source.seek(offset)
                record = read_exact(source, size + 8)
            block = CBlock()
            stream = io.BytesIO(record[8:])
            block.deserialize(stream)
            if stream.read(1) or hash256(record[8:88]) != block_hash:
                raise ValueError('Block changed or invalid serialization')
            if block.calc_merkle_root() != block.hashMerkleRoot:
                raise ValueError(f'Merkle mismatch at height {height}')
            if block.vtx[0].nType == 5:
                declared_height = struct.unpack('<i', block.vtx[0].vExtraPayload[2:6])[0]
                if declared_height != height:
                    raise ValueError('Coinbase height mismatch')
            for tx in block.vtx:
                if tx.nType == 6:
                    summary = commitment_summary(tx.vExtraPayload)
                    if summary['height'] != height:
                        raise ValueError('Commitment height mismatch')
                    summary['block_hash'] = block_hash[::-1].hex()
                    commitment_count += 1
                    sizes = (summary['signers_size'], summary['members_size'])
                    if previous_sizes.get(summary['type']) != sizes:
                        transitions.append(summary)
                        previous_sizes[summary['type']] = sizes
                    if not summary_only:
                        commitments.append(summary)
            if fixture is not None:
                fixture.write(record)
            digest.update(record)
            if not summary_only:
                rows.append(dict(height=height, hash=block_hash[::-1].hex(),
                                 source_file=path.name, source_offset=offset, size=size))
    manifest = dict(anchor_hash=anchor_hash, anchor_height=anchor_height,
                    block_count=len(chain), fixture_sha256=digest.hexdigest(),
                    consensus_validated=False, fixture_written=not summary_only,
                    commitment_count=commitment_count, size_transitions=transitions)
    if not summary_only:
        manifest.update(blocks=rows, commitments=commitments)
    (output_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return dict(block_count=len(chain), commitments=commitment_count,
                fixture_sha256=digest.hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blocks-dir', type=Path, required=True)
    parser.add_argument('--anchor-hash', required=True)
    parser.add_argument('--anchor-height', type=int, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--summary-only', action='store_true',
                        help='Verify the archive and report size transitions without copying blocks')
    args = parser.parse_args()
    print(json.dumps(extract(args.blocks_dir, args.anchor_hash,
                             args.anchor_height, args.output_dir, args.summary_only)))


if __name__ == '__main__':
    main()
