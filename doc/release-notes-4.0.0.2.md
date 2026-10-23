# Yerbas Core 4.0.0.2

This release improves asset visibility, wallet recovery, and release testing.

- Release packages include `yerbas-tx`. CI runs all 60 transaction utility fixtures and argument/signing checks, including on Windows.
- Asset balances show owned quantities, with available, pending, restricted, and locked or otherwise unavailable amounts. Frozen holdings remain visible. Incremental updates preserve selection.
- File → Restore wallet backup copies a backup to a new wallet file, retains the current file, and restarts for a rescan. Existing synchronization and rescan progress remain visible. Backup messages explain what recovery needs.
- Asset image previews can be exported as PNG. The dialog explains that external media is not included in wallet backups. Preview loading remains explicit, bounded, and subject to the configured proxy.
- Recovery regression tests cover encrypted wallets, incorrect passphrases, fractional assets, NFTs, owner tokens, and frozen restricted assets. Windows CI runs the recovery test. The test accepts `--source-binary` for upgrade checks using an older daemon.
- CI builds `dev`, `main`, the literal `4.X` branch, and branches matching `4.*`.

## Wallet recovery

Keep the original `wallet.dat` backup and its encryption passphrase. Recovery requires the keys for the receiving addresses and blockchain synchronization/rescan. Make a fresh backup after importing keys or changing encryption. A pruned node may need to download historical blocks again. Images and other external content require separate preservation; loss of an image does not remove on-chain ownership.

A backup is validated when the wallet opens after restart. An unreadable or invalid backup must not replace the original wallet. The restore menu creates a separate `restored-<unique identifier>.dat` file in the selected network's data directory.
