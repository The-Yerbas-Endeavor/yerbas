# Private reduced-collateral testnet profile

Build the `4.0.0.3` branch with Qt enabled using the platform build instructions.
No special configure option is required. This profile is selected at runtime:

```ini
testnet=1
testnetfastcollateral=1
```

Use a dedicated data directory and explicit lab peers. For the current lab:

```ini
connect=149.248.35.59:15500
dnsseed=0
```

The flag changes testnet smartnode collateral from 4,000 to **4 YERB**, coinbase
maturity from 100 to **10 blocks**, and P2P message magic to `7b796572`.
The 60-second difficulty target, retargeting, proof of work, block rewards,
founder payments, LOW_LLMQ logic and authorized testnet spork address are unchanged.
Mainnet and ordinary testnet rules remain unchanged without the flag; using the
flag outside testnet is rejected. All participating nodes need a matching build
and the flag. Ordinary testnet peers cannot connect to this private profile.

Launch with a new dedicated data directory, for example:

```sh
mkdir -p /path/to/private-testnet
./src/qt/yerbas-qt -testnet -testnetfastcollateral \
  -datadir=/path/to/private-testnet -connect=149.248.35.59:15500 -dnsseed=0
```

After synchronization, `setgenerate true 1` in the Qt console enables one native
CPU mining worker. The 60-second target is not a guaranteed block interval.
110 registrations need 440 YERB plus fees; mining rewards in different wallets
remain separately owned. The signing key belongs only in the operator's local
configuration. Configuring `sporkkey=` does not itself activate any spork.

## Existing wallets and data

Do not switch an existing standard-testnet data directory in place merely by
adding the flag. Peer, spork and other derived caches embed network magic, as do
block-file framing headers; old files need a deliberate migration. Prefer a fresh
private-profile data directory and synchronization. If retaining a test wallet,
close it cleanly, back it up, and copy its wallet into the new directory before
starting the new build. Keep the original directory untouched. Never run two
instances against the same wallet directory. The new profile's short-maturity
spends and 4-YERB registrations are incompatible with standard testnet.

The controlled server migration preserves wallets and block payloads, backs up
network-tagged caches, and rewrites only block/undo framing magic. It is a lab
administration procedure, not an automatic wallet upgrade included here.

## Validation

Native coverage checks rejection one block before coinbase maturity and acceptance
at the boundary on mainnet, ordinary testnet and this private profile. It also
checks unchanged ordinary collateral, profile guards, P2P separation, shared
genesis and the unchanged difficulty target. Wallet balance/UI maturity and
mempool reorg handling use the same selected maturity as transaction validation.
