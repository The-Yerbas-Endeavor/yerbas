# Local asset acceptance tests

Use a wallet-enabled build with tests enabled. These commands use disposable
regtest data and loopback connections; they do not use your normal wallet or
connect to testnet/mainnet. Python 3 needs no third-party modules.

```sh
python3 ci/run-unit-tests.py src/test/test_yerbas \
  --suite assetdb_tests --suite asset_wallet_tests --output asset-unit-results
python3 ci/test-wallet-asset-restore.py src/yerbasd --workdir asset-restore-results
python3 ci/test-asset-acceptance.py src/yerbasd --workdir asset-acceptance-results
```

Each functional test's `--workdir` must name a new directory. Omit it to use an
automatically cleaned temporary directory. Retained directories contain test
wallets and debug logs, not production wallets. Do not run Python with `-O`,
which disables the tests' assertions.

Coverage:

- Asset database filtering/pagination and wallet balance resets.
- Wallet-owned message, restriction and reward storage; backup/restore,
  legacy migration, corruption handling, wallet isolation and reward arithmetic.
- Restore coins, fractional assets, a unique asset and its metadata, and the
  administrator token from a wallet.dat backup made before receipt; rescan,
  restart and spend the recovered assets.
- Issue, fractional transfer, reissue and administrator-token handover;
  rejection of reissue without ownership.
- Qualifier assignment/removal, verifier rejection, address and global
  freeze/unfreeze, and global restriction disconnect/reconnect.
- Restricted reissue using named RPC arguments.
- Reissue disconnect/reconnect, restart and rescan.
- Ownership snapshot, a pending reward payout across restart, confirmed
  completion and duplicate distribution rejection.
- Authorization and balance isolation when the administrator token belongs to
  a secondary loaded wallet.

The functional tests advance regtest mock time to avoid making their mining
workload depend on an unrealistic frozen clock. Their low reward confirmation
setting is confined to the disposable test nodes.

These are headless local tests. They do not establish Qt GUI usability,
large multi-batch payout behavior, crash safety at every database-write boundary,
or public-network upgrade compatibility.
