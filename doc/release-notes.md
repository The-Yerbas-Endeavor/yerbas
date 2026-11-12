# Yerbas Core 4.0.1.3

This release targets coordinated mainnet upgrades from 3.2.0.21 and earlier v4
builds. Download the archive for your platform from the
[Yerbas releases page](https://github.com/The-Yerbas-Endeavor/yerbas/releases).
Release status and operator announcements are maintained there.

## Upgrade

1. Back up every wallet using the wallet backup function. Shut down the old node
   cleanly, then retain your data directory and configuration backup.
2. Download the matching platform archive and verify it against `SHA256SUMS`.
3. Extract the complete `yerbas-build/` folder into a new application location.
   Keep its supporting libraries/plugins. Do not replace your data directory
   with application files.
4. Start the new wallet or daemon with the same mainnet data directory and
   configuration. Never run two processes against one data directory.
5. Allow history indexing/synchronization to finish. Confirm version 4.0.1.3,
   balances, peers, and operator/service status.

Eligible unpruned upgrades automatically index pre-record recovery history without
rebuilding chainstate. Routine upgrades do not require reindexing. If recorded
transitions already exist and their index is missing, use `-reindex-chainstate`
or `-reindex`. Missing or pruned historical blocks may require a resync. See the
[operator guide](signed-spork-release-checklist.txt) for migration and rollback rules.

## Changes since 3.2.0.21

- Qt 6 wallet with **Asset Manager / My Assets**, asset search, balances,
  metadata, selected-asset sending, history, and backup guidance.
- Wallet asset/reward records persisted in `wallet.dat`; wallet isolation,
  reward allocation, and interrupted-payout handling improvements.
- Authority-signed, fee-paying `quorum recovery on|off|status` transactions
  record LOW_LLMQ transitions for historical replay. ON has no automatic expiry.
  The first cutover uses a 720-block boundary; later transitions use 30-block
  boundaries. Confirmation and effective activation are separate events.
- Existing PoSe cleanup and hard-coded legacy history retained, with automatic
  recovery-history migration and DKG queue resizing.
- Protocol 70224 advertised without automatic exclusion of older peers.
- Founder-payment validation corrected to use the block's own height.
- Opt-in isolated fast-collateral testnet profile; mainnet collateral unchanged.

Miners, pools, smartnodes and other validators must upgrade before the first
recovery transaction is mined. Older validators can reject that transaction.
OFF does not undo cutover or make downgrade to 3.2.0.21 safe. Ghost cleanup and
restoration of all quorum services are separate milestones. Read the
[operator guide](signed-spork-release-checklist.txt) before recovery coordination.

## Asset wallet activation

V4 mainnet asset creation, sending, reissuance, ownership transfers, and asset
reward payouts unlock at tip height **1,195,400**. The estimate was January 1,
2027, 00:00 UTC; the height, not the date, controls activation. A rollback below
that height relocks these operations. Receiving/viewing assets and ordinary YERB
payments remain available. Testnet/regtest are unaffected. This is wallet policy,
not a consensus prohibition on older wallets or raw transaction tools.

Back up the complete wallet: private keys alone do not preserve every local
reward/job record. See [asset storage and recovery](wallet-asset-storage.md) and
[Asset Manager](asset-manager.md). This release adds no smart contracts.

## New in 4.0.1.3

- Mainnet checkpoint **1,152,420**:
  `53c34a2a736776ec3ff6ca11bcaa05c6fe3e4b52853352ab76608b3ff80428fa`.
  Minimum chainwork and default assume-valid updated to that block.
- Fixed seeds retain 31 prior unique addresses and add `199.247.25.194`,
  `64.177.51.95`, `45.77.211.113`, `45.63.84.9`, and `45.63.87.84` on port
  15420: 36 unique addresses. DNS/testnet seeds unchanged.
- Platform archives extract into `yerbas-build/`, without a `bin/` level.
  Linux commands/Windows executables are at the root; macOS includes
  `Yerbas-Qt.app`, `yerbasd`, and `yerbas-cli`.

Bundled Linux Qt packages use the root `yerbas-qt` launcher to start
`libexec/yerbas-qt`; keep `lib/` and `plugins/` together. Ubuntu 26 uses system Qt:
`sudo apt-get install libqt6widgets6 libqt6network6 libqt6core5compat6 qt6-qpa-plugins`.
Windows requires its packaged DLLs/plugins. macOS ships an Intel app in a tar.gz.

## Dependencies and builds

Depends recipes: Qt 6.12.0, Boost 1.92.0, OpenSSL 3.5.9, MiniUPnPc 2.3.3,
libevent 2.1.13-stable, ZeroMQ 4.3.5; Berkeley DB 4.8.30 retained. Native/system
versions can differ by platform. Modern compiler compatibility, library packaging,
Berkeley DB integration and transaction-utility fixes accompany these updates.

CI targets Ubuntu 22/24/26 x86-64, Ubuntu 24 ARM64, Windows x86-64, and macOS 15
Intel. Release filenames labelled `x86` are 64-bit x86 builds. Checksums and
`BUILD-PROVENANCE.json` identify the attached archives and source commit.
For exact build commands, see [the workflow](../.github/workflows/build.yaml).

## Help

- `yerbasd -help`, `yerbas-cli -help`, `yerbas-qt -help`: startup options.
- `yerbas-cli help`: RPC list from the connected node.
- `yerbas-cli help quorum recovery`: recorded recovery help.
- `yerbas-cli help issue`, `yerbas-cli help transfer`: asset RPC help.
- In the Qt console, omit the `yerbas-cli` prefix.

Historical recovery investigation/design documents are preserved as development
records, not deployment instructions. Current operator behavior is described in
[signed-spork-release-checklist.txt](signed-spork-release-checklist.txt).
