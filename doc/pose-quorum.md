# Quorum-approved PoSe monitoring

This implementation targets the `dev` development branch. Mainnet LLMQ_100_67 activates
at block **1,212,840**; the rotating 11-of-15 RC activates at **1,214,280** after
a 1,440-block participation warm-up. RC activation projects to January 25, 2027
(Pacific); block heights, not calendar dates, govern consensus. Testnet uses blocks 4,320 and 8,640 respectively; see pose-testnet.md. The `-poseactivationheight` override is regtest-only.

## Authority and availability

Official monitoring nodes submit BLS-signed reports. Reports never directly
ban a smartnode, change its penalty, or trigger automatic quorum signing.
Quorum members approve a request with `pose approve` after independently
investigating the failure. Approval can be manual or performed by the optional
validator helper after its own three failed probes. Receiving official reports
alone never starts signing.

The production profile is `LLMQ_100_67` (type 4): 100 selected members, at least
80 valid members at formation, and 67 shares to recover a signature. DKG runs
every 60 blocks (about two hours at Yerbas's target spacing). Twelve quorums
remain signing-active. Existing small-network parameter switching never reduces
this profile. Existing ChainLocks and InstantSend type selections are preserved.

Regtest uses a separate `LLMQ_POSE_TEST` (101), with three members, a formation
minimum of three and a signing threshold of two. This is not a production fallback.

If no eligible quorum exists, reports remain pending until they expire. If fewer
than 67 valid production members sign, no certificate is produced. Applying
penalties also requires a subsequent successful DKG commitment. This ordinary quorum path
cannot bootstrap a network that lacks enough available smartnodes. Operators
must restore participation before using it.

## Evidence collection

Use independent observers on different networks. Generate a separate BLS key
for each observer (the existing `bls generate` RPC can generate keys). Never
reuse a smartnode operator key. Each participating node's `yerbas.conf` lists
trusted evidence keys, one per line:

```
posemonitorpubkey=<observer-1-public-key>
posemonitorpubkey=<observer-2-public-key>
posemonitorpubkey=<observer-3-public-key>
```

Only an observer's local configuration contains its evidence signing key:

```
posemonitorprivkey=<this-observer-private-key>
```

Keep RPC local and use cookie authentication. Observers do not need RPC access
to quorum members. This branch does not provide per-method RPC authorization;
do not give an untrusted observer the RPC credentials of a signing smartnode.

Run one collector per target, redirecting JSON output to your monitoring logs:

```
python3 contrib/pose/monitor.py <proTxHash> --cli /path/to/yerbas-cli
```

The helper uses the local node's outbound connections and authenticated
`MNAUTH` identity as exposed by `getpeerinfo`. It requires fresh received traffic
from the expected registered endpoint and identity. A mere successful TCP
connection is insufficient. It requires at least three established outbound
peers before and after a failed probe, and refuses observations during initial
block download. It checks at heights ending in 10, 20, and 0 of a 30-block window;
all three probes must time out before it signs and submits a report. Missing a
probe, RPC failure, any response, service change, or changed chain reference
invalidates the window. An existing authenticated inbound connection makes
the probe inconclusive because Core rejects duplicate authenticated connections.
This is a reachability test, not a proof that the target
serves every smartnode function correctly.

A monitor can lie about observations. Its signature identifies the reporter;
it does not cryptographically prove absence of a response. Three distinct
trusted reports are required for approval, and independent quorum review is
still necessary. Common network outages and partitions need operator judgment.

## Approval and enforcement

```
yerbas-cli pose status
yerbas-cli pose approve <request-id>
```

For automatic approval on a quorum member, run a separate local helper:

```
python3 contrib/pose/monitor.py <proTxHash> --role validator --cli /path/to/yerbas-cli
```

Validator mode requires its own complete failed-probe window, then requests a
share only after the Core manager has received three distinct trusted reports.
It retries while matching evidence is pending, for at most 120 blocks. Changed
service identity or chain references, local sync/connectivity problems, and a
fresh authenticated response cancel pending approval. This mode must run on a
quorum member's own host; an official observer must never control that host's
RPC. The default observer role only reports and never calls `pose approve`.

Only members of the deterministically selected PoSe quorum can sign. Each
member approves on its own node. The signing quorum is selected at the report's
fixed reference height, so later approval does not accidentally select a
different quorum as the chain advances. Existing one-vote-per-request tracking
still applies. The separately gated rotating 11-of-15 recovery committee is described in pose-recovery.md. It selects registered smartnodes from on-chain participation history with the mainnet schedule above.

Once enough shares recover a signature, a certificate is broadcast and stored
in the local LLMQ database. Nodes that verify it mark that target bad when
preparing subsequent DKG complaints. The existing mined quorum commitment
applies PoSe penalties; the monitoring manager never mutates the deterministic
smartnode list directly. A certificate is not an immediate on-chain ban.

The bounded `posereport` and `posecert` P2P messages relay accepted reports and
certificates. An evidence relay must trust the reporting key; certificates are
verified against the PoSe quorum and do not require monitor keys on the receiving
node. Use directly connected upgraded monitors/quorum nodes. Old clients do not
relay these messages. For a node that missed the original announcement:

```
yerbas-cli pose getcertificate <proTxHash>
yerbas-cli pose submitcertificate <certificate-hex>
```

Certificates persist across restarts. Pending observations are intentionally
in-memory and can be resubmitted with `pose submitreport <report-hex>` from the
observer's JSON logs after a restart. There is no automatic historical P2P
inventory synchronization for these new messages yet.

## Replay protection and limits

Requests bind the chain genesis, reference block, target registration hash,
endpoint, operator key, registration height, and revival height. Reports cover
three probes over 20 blocks and expire 120 blocks after the reference height.
Certificates expire after 1,440 blocks. A service/operator change or revival
invalidates old requests. Chain ancestry and quorum selection are rechecked
before a certificate influences DKG, including after restart or reorganization.

There are at most 256 pending requests and 16 observers per request. Duplicate
observer reports do not add votes. P2P payloads are bounded to 512 bytes, with
per-peer processing limits. Malformed reports do not cause smartnode bans.

## Validation and release requirements

Run the Python collector policy tests:

```
python3 -m unittest discover -s contrib/pose -v
python3 contrib/pose/rpc_smoke.py --bin-dir src --workdir /tmp/yerbas-pose-smoke
```

Build and run `pose_tests`, `chainparams_tests`, and
`pose_certificate_lifecycle` in the native test binary. Tests cover the 67-share
threshold, wrong types and altered messages, observation windows, activation,
service-state binding, and the provider/certificate/penalty/revival lifecycle.
The lifecycle fixture creates signed commitments directly; it does not run a
live 100-node DKG or measure network behavior under a partition.

Before public activation, run a multi-node testnet exercise covering actual
DKG/signature-share transport, delayed and lost report/certificate propagation,
network partitions, synchronized outages, restart/reorg behavior, and observer
key rotation. Select ordinary PoSe monitor keys through the release process. This patch supplies
mainnet activation heights but no ordinary monitor keys; RC uses selected smartnode keys.

## Local validation of this patch

On the implementation host, a headless build with wallet support and native
tests enabled passed. The selected native tests (`pose_tests`,
`chainparams_tests`, `pose_certificate_lifecycle`, `bls_tests`,
`evo_dip3_activation_tests`, and `miner_tests`) passed: 14 test cases in total.
Seven Python helper tests and three isolated localhost RPC smoke scenarios also
passed. RPC checks confirmed default-disabled regtest, activation at block 30,
continued block production through the first commitment window, and rejection
of a mainnet activation override. Public networks were not contacted or modified
by these tests. A wallet-disabled build encountered the pre-existing miner
reference to `EnsureWalletIsAvailable`; the wallet-enabled build succeeded.
