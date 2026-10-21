# Wallet asset backups (4.0.0.1)

Asset-bearing transactions and keys already belong to the Berkeley DB wallet.
This change also stores wallet-specific asset metadata in that same `wallet.dat`:

- Received messages and their status, channel subscriptions, and seen addresses.
- The wallet's recorded tag and restriction events, including watch-only addresses.
- Reward snapshot schedules, captured ownership snapshots, payout plans, and payout
  transaction references.

Use `backupwallet` or the GUI wallet backup command after migration. A private-key
text export (`dumpwallet`) does not contain this metadata. Copying a live database
file directly is not a substitute for the wallet backup command. Restore the
backup with a version containing this implementation, then synchronize/rescan as
needed to discover transactions since the backup.

The node's shared asset index, restriction state, blocks, and chainstate remain
outside the wallet. They serve blockchain validation and can be rebuilt from the
chain; a wallet backup is not a copy of the blockchain. Balances and global asset
metadata still require synchronized chain state. Asset content referenced by IPFS
is not downloaded or embedded by this change.

## Migration and multiple wallets

On first opening an existing wallet, legacy records are imported from
`messages/messages`, `messages/channels`, `myrestricted`, and the three `rewards`
stores. All imported records and a completion marker are committed in one wallet
transaction. Failed validation/import leaves the marker absent and wallet loading
fails. The old stores are retained; this code does not delete them. Keep them until
all existing wallets have been opened and backed up successfully.

Legacy messages, channels, and reward stores have no wallet owner. Each existing
wallet receives a copy. Tagged/restricted address records are imported only when
the wallet owns or watches the address. Newly created wallets start empty. After
migration, changes apply only to the selected wallet, including message deletion,
unsubscription, snapshot cancellation/purging, and reward status. A repeated load
does not re-import deleted records from the old folders.

Legacy reward plans are imported with **PAUSED (10)** status, preserving their
payout transaction references and ownership snapshots. They never automatically
resume. Use `getdistributestatus` with the original distribution parameters to find
its `Distribution Hash`, then explicitly select the intended funding wallet:

```sh
yerbas-cli -rpcwallet=wallet.dat resumerewarddistribution DISTRIBUTION_HASH
```

The wallet must be unlocked and the ownership snapshot present. Resume only one
copy of a legacy plan; copies imported into other wallets must remain paused.
Resuming records the selected plan as processing; normal block processing attempts
payments when synchronized, unlocked, and `-assetindex` is enabled. Snapshot
scheduling and reward RPCs now use the selected wallet. `getsnapshot` and
`purgesnapshot` require wallet support.

An older backup naturally predates later payments and metadata changes. Reconcile
payout history before resuming an older backup; this migration cannot infer
payments absent from that backup. Do not run an old binary against the migrated
wallet: older versions ignore these records and continue updating legacy folders.

## Storage and corrected discrepancies

BDB keys are `("assetrecord", (section, serialized_key))`, with serialized values.
Sections are `messages`, `channels`, `restricted`, `snapshotrequests`, `snapshots`,
`distributions`, and a versioned `migration` marker. In-memory LevelDB views retain
the existing typed database APIs without creating per-wallet folders. Writes go
through to BDB before the view is updated. Wallet loading validates record types,
structure, status values, and relevant key/value identities; malformed records
are fatal rather than silently omitted.

This change also corrects:

- Message replacement retaining an older status through insert-only caching.
- Message/restriction operations using the first loaded wallet or global state.
- Berkeley DB transactions using the global environment instead of their own
  wallet database environment.
- `purgesnapshot` reading a nonexistent third argument instead of block height.
- Reward batches creating an extra empty batch at exact batch-size multiples.
- Reward creation reporting success when its database write failed.
- Snapshot schedule enumeration decoding string keys as integers.

Tag/restriction entries are recorded wallet events, not a replacement for the
node's authoritative restriction state. This change does not alter consensus rules,
asset transaction encoding, private-key encryption, or Berkeley DB 4.8 format.
Wallet metadata has the same confidentiality characteristics as other unencrypted
wallet metadata; wallet encryption protects private keys, not these records.

## Validation

The `asset_wallet_tests` suite uses real Berkeley DB files and covers backup/restore
without side folders, asset-bearing transactions, reward snapshots/references,
wallet isolation, message replacement, idempotent migration, rejected corrupt
imports/records, and paused legacy rewards. The tests are included in normal
wallet-enabled unit-test discovery and CI.

Focused tests and compilation are not a substitute for a complete application
build and full regression suite. Those results are reported separately.
