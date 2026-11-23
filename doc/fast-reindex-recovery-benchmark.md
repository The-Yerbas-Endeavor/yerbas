# Fast Reindex and Recovery: measurement plan (Yerbas 4.0.1.6)

This branch adds **timing only**, not changes to consensus rules, transaction validation, existing index formats, wallet data, or default flags. Keep it separate from quorum recovery and pruning deployment.

## Operations are different

- `-reindex`: reconstruct block index and chainstate from available block files. Requires accessible archival history; do not invoke on a pruned live data directory expecting absent blocks to reappear.
- `-reindex-chainstate`: rebuild UTXO state using the existing block index and block data; does not recover missing pruned block files.
- `-rescan`: search locally accessible blocks for wallet transactions; not equivalent to chainstate reindex. A pruned node may not have sufficient historical data.
- Quorum mined-commitment index: a separate derived index; see experimental PR #62. It must not be conflated with `-reindex`.

## Instrumented log lines

- `Fast recovery timing: phase=block-file`: wall-clock milliseconds per block import file (when `-reindex` is active).
- `Fast recovery timing: phase=full-reindex`: total wall-clock time for block-file import and associated import phase.
- `Fast recovery timing: phase=activate-best-chain`: wall-clock time spent connecting/indexing the best chain after import, including chainstate rebuild work.
- `Fast recovery timing: phase=wallet-rescan`: elapsed time, number of blocks and transactions visited, and interruption status.

Log timing is *not* an indication of successful validation by itself. Existing error handling and block validation remain authoritative.

## Safe benchmarking

1. Record build SHA, CPU/RAM, storage type, `-dbcache`, indexed height, data-dir size and free disk space.
2. Use a **disposable, complete archival copy** with ample headroom; never test a new `-reindex` or `-reindex-chainstate` implementation on the only copy of a funded wallet, keys, or blockchain.
3. Benchmark full reindex, chainstate-only reconstruction, and wallet rescan separately using equivalent starting snapshots.
4. Compare the tip hash, chainwork, UTXO state, EvoDB/quorum verification and wallet transaction balances with an unchanged control binary. For wallet tests, use only test wallets or securely backed-up wallet files.
5. Force orderly interruption at several heights, restart, and validate no silent partial success.
6. Repeat with constrained (~1 GiB) and desktop-class (>=16 GiB) memory. Never infer a global performance speedup from a single host.

## Planned optimizations (not yet implemented)

- Profile disk reads, script validation, UTXO cache misses and EvoDB write amplification before modifying rebuild logic.
- Explore bounded cache sizing and read/write batching; preserve consensus and atomicity.
- Explore authenticated block filters or another *verified complete* wallet history index for rescans. Never skip a block based on an unvalidated negative filter, and account for historical wallet-key creation.
- Add restartable checkpoints only with explicit chain-tip binding, integrity validation, and rollback on reorg/interruption.
- Keep pruning-compatible index rebuild separate from missing full-block and wallet-history recovery.

No 24-to-36-hour speedup is claimed until comparative benchmarks pass.
