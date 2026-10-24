# Recovery Committee (RC): technical configuration and applications

## Implementation and publication status

This reference documents the implementation published in
[PR #53](https://github.com/The-Yerbas-Endeavor/yerbas/pull/53), source commit
[`87d19d498280f1600932d3cccb9981be5b2b5cc0`](https://github.com/The-Yerbas-Endeavor/yerbas/tree/87d19d498280f1600932d3cccb9981be5b2b5cc0).
At publication of this reference, that implementation is a draft and has not been
merged into `dev`. Adding this document to the branch does not install RC,
activate its consensus rules, or add its RPC commands to existing binaries.
Run the commands below only with a build containing the referenced implementation.

The rotating RC replaces the earlier appointed 5-of-7 prototype. Its protocol and
storage version is 2. Old prototype certificates and chains containing version-1
recovery penalties are not compatible. Use fresh test datadirs for evaluation.

## Purpose and applications

The RC provides bounded PoSe enforcement when ordinary `LLMQ_100_67` quorum
formation fails repeatedly. It consists of active registered smartnode identities
selected from consistent participation recorded on-chain. Membership is temporary;
there are no hard-coded operator public keys, official permanent seats, separate
RC registration transactions, or membership derived from `nodes_main.txt`.

| Application | RC behavior | Limit |
| --- | --- | --- |
| Three consecutive failed quorum formations | Enables a temporary recovery epoch | A complete roster and 11 valid selected signers are still required |
| Repeated reachability failures observed by selected signers | Signers may authorize a target-specific PoSe penalty | Reachability assessment is explicit; the daemon does not automatically scan targets |
| Return of healthy quorum formation | Two consecutive successful sessions rearm normal operation | A successful session alone does not end recovery |
| Persistent outage | Authority expires and becomes locked | Repeated failures cannot renew authority |
| Testnet outage and recovery exercises | Uses the same 100/80/67 quorum and 11/15 RC thresholds | Two full nodes alone cannot exercise distributed DKG or RC signing |

RC signatures authorize a bounded penalty; they are not an objectively verifiable
proof that a target was offline. A validator verifies identities, signatures,
chain/epoch binding and limits, not the underlying network observations. Operators
must account for partitions, routing failures and asymmetric reachability before
signing. The RC cannot restore a broken network connection, create missing
participants, confiscate collateral, or guarantee quorum recovery.

One operator may control several registrations. This is an unavoidable possible
side effect, not an intended objective. Distinct registrations and operator keys
do not establish distinct human ownership. Consistent participation is not an
honesty or trustworthiness score.

## Fixed consensus configuration

These values are defined by source code. They are not per-operator configuration
knobs and must agree across validators on a given network.

| Parameter | Value | Meaning |
| --- | ---: | --- |
| `LLMQ_100_67` type | 4 | Dedicated PoSe approval quorum type |
| Selected quorum size | 100 | Up to 100 selected from the registered smartnode pool |
| Formation minimum | 80 | Valid members within the selected quorum; not merely 80 somewhere in the pool |
| Signing threshold | 67 | Quorum signature shares required |
| DKG interval | 60 blocks | Session start heights are multiples of 60 |
| DKG phase length | 2 blocks | Phase duration |
| Commitment mining window | Offsets 10–18 | Formation success/failure determined when the window closes |
| DKG bad-vote threshold | 80 | Configured threshold for bad-member votes |
| RC selected size | 15 | `RECOVERY_SIZE` |
| RC approval threshold | 11 | `RECOVERY_THRESHOLD`; may carry 11–15 distinct signatures |
| Scheduled roster rotation | 360 blocks | `RECOVERY_ROTATION`, plus first RC activation block |
| Participation history | 1,440 blocks | `RECOVERY_HISTORY`, a rolling window, not permanent credit |
| Minimum registration/revival age | 720 blocks | `RECOVERY_AGE` measured at the eligibility snapshot |
| Eligibility snapshot lag | 60 blocks | Snapshot at selection height minus 60 |
| Randomness seed block lag | 30 blocks | Later than snapshot, earlier than selection |
| Minimum credited sessions | 3 | Distinct session start heights |
| Minimum credited span | 120 blocks | Latest credited start minus earliest credited start |
| Credit freshness | At most 360 blocks | Snapshot height minus latest credited session start |
| Required participation rate | At least 80% | Credited starts / recorded selection opportunities |
| Recovery trigger | 3 consecutive failures | Completed `100_67` sessions starting at/after RC activation |
| Return to normal | 2 consecutive successes | Applies in recovery and locked states |
| Authority duration | 6 DKG intervals | Deadline is trigger height + 360 |
| Observation span | At least 20 blocks | `end - start >= 20`; observation begins after trigger |
| Certificate lifetime | Up to 30 blocks after end | Also capped by the epoch deadline |
| Target allowance | Once per epoch | Same target cannot receive a second RC penalty that epoch |
| Per-block allowance | 1 recovery transaction | Includes transactions against different targets |
| Epoch target budget | `min(10, floor(V / 10))` | `V` is valid smartnodes at the trigger |
| Penalty amount | `CalcPenalty(66)` | Integer 66% of the existing dynamic maximum |
| Transaction version/type | Version 3 / type 10 | `TRANSACTION_RECOVERY_PENALTY` |
| Certificate version | 2 | Required by signature verification |
| Maximum payload | 2,048 bytes | RPC certificate hex limited to 4,096 characters |

### Network activation schedule

The following heights belong to the referenced implementation, not an already
activated deployment of the `dev` branch before this implementation is merged.

| Network | LLMQ activation / participation indexing | RC activation | Target block interval |
| --- | ---: | ---: | ---: |
| Mainnet | 1,212,840 | 1,214,280 | 120 seconds |
| Fresh testnet | 4,320 | 8,640 | 60 seconds |
| Regtest | Explicit `poseactivationheight` | Explicit `recoveryactivationheight` | Controlled by test mining |

Mainnet dates project to January 23 and January 25, 2027, Pacific time. Heights
are consensus rules; calendar dates are estimates. Testnet dates depend on when
mining starts and its pace. Warm-up permits history collection but does not
guarantee 15 candidates will qualify. Upgraded nodes must index participation
from the LLMQ activation height; RC does not infer missing history from local logs.

The mainnet estimate uses block 1,146,197, timestamp 1792733476, 120-second target
spacing, and a 360-block-aligned RC height. No node consults wall-clock dates or
an explorer to decide activation.

## Eligibility and deterministic selection

At selection height `S`, validators examine the deterministic smartnode list at
`C = S - 60`. Candidates must be valid and confirmed, have sufficient collateral,
be unbanned, and meet both applicable age requirements: registration age at least
720 blocks and, if revived, at least 720 blocks since the last revival.

Participation records come from validated non-null production quorum commitments
of types 1–4. A selected member earns credit only when both its `validMembers` and
`signers` bits are set. The members aggregate signature authenticates the signing
identities. Null commitments and test-only quorum types provide no credit.

Records match the candidate's registration hash, operator key and service-state
hash. The service-state hash includes service address, operator key, registration
height and last revival height. Payment updates alone do not change this hash.
The code scans indexed commitment records within the history window ending at
`C`, then filters session starts to `(C - 1440, C]`.

Selection opportunities and successes are deduplicated by session start height.
When multiple quorum types select a candidate at the same start, a qualifying
signature in any one gives credit for that start. A node never selected at a
height has no missed opportunity. Absence from a successful commitment's signers
is conservative missing credit, not proof of an offline node. Failed sessions
without a non-null commitment provide no attributable individual activity record.

The seed hashes a protocol domain, genesis hash, snapshot block hash at `S - 60`
and block hash at `S - 30`. Each candidate is ranked by a domain-separated hash
of that seed and its registration hash, with registration hash as the tie-breaker.
Select the first 15; select no roster if fewer than 15 qualify. This is
reproducible pseudorandom selection, not a local random draw. Block-derived
randomness can still be influenced by miners.

The scheduled roster becomes the frozen roster when the third failure closes.
Later scheduled rotations do not replace that recovery epoch's members, renew
its time window or replenish its budget. Every certificate signer must still be
valid at the previous block and have the frozen service-state identity. No
replacement members or reduced threshold are available if members become
ineligible. Signature verification also rejects duplicate roster identities/keys.

## State machine and exact timing

| State | Event | Result |
| --- | --- | --- |
| Normal | Successful completed session | Reset consecutive failures |
| Normal | Third consecutive failed completed session | Freeze roster; set trigger, epoch and budget; enter recovery |
| Recovery | Two consecutive successful completed sessions | Return to normal |
| Recovery | Reach final authorized block | Transition to locked for subsequent blocks |
| Locked | More failed sessions | Remain locked; no renewed penalties |
| Locked | Two consecutive successful completed sessions | Return to normal |

Only `LLMQ_100_67` formation outcomes affect these counters. A failed session
means its mining window closes without a valid non-null commitment; it does not
mean a single signing request timed out. Other quorum types may still function.

Let `T` be the trigger block and `D = T + 360`. A penalty transaction must be
included before `D`; the last potentially authorized inclusion height is `D - 1`.
The stored mode becomes locked while processing `D - 1`, unless successful
sessions have already returned the state to normal. At least two consecutive
successful sessions are needed to rearm normal operation after expiry; the
expiry transition resets success/failure counters.

For a certificate `(start, end, expiry)`:

- `start > T`, `end - start >= 20`, and `end <= previous block height`.
- `expiry = min(end + 30, D - 1)` exactly, not a caller-chosen longer lifetime.
- Inclusion height must be `<= expiry` and `< D`.
- Start/end block hashes, epoch and roster must match the validating branch.
- The target must remain present, unbanned and have the same service-state hash
  at every observation block through the previous tip, not only at endpoints.

For example, if testnet sessions starting 8,640, 8,700 and 8,760 all fail, their
windows close at 8,658, 8,718 and 8,778. The trigger is 8,778. An observation from
8,779 through 8,799 first permits transaction inclusion at 8,800, with expiry
8,829. This assumes a qualified frozen roster, sufficient budget and valid
signatures. Reaching a trigger does not bypass those conditions.

## Penalties, certificates and storage

The dynamic PoSe maximum is `max(100, total registered smartnodes)`. The applied
increment is integer division `maximum * 66 / 100`, capped at the existing
maximum after addition to the target's current penalty. Reaching that maximum
sets the existing PoSe ban height. A clean node receiving one 66-point penalty
when the maximum is 100 is not immediately banned. Existing decay remains in
place, and RC cannot repeatedly penalize that target in the same epoch.

For 80 valid nodes at trigger the epoch budget is eight targets; for 100 or more
it is at most ten. The budget counts valid nodes, whereas the PoSe maximum uses
all registered nodes. Less than ten valid nodes gives a zero budget.

The certificate serializes version; committee, epoch, target and service-state
hashes; start/end block hashes; start/end/expiry heights; and sorted pairs of
zero-based selected-member index and BLS signature. It contains no network-probe
transcript. These are separate selected-operator signatures, not a newly formed
67-share threshold quorum signature.

Signatures bind the genesis and protocol domain `yerbas-recovery-penalty66-v2`
as well as all certificate fields except the signatures themselves. Roster and
selection hashes use separate version-2 domains. Cross-chain, cross-roster,
cross-epoch and changed-target reuse must fail.

Consensus rejects multiple recovery transactions in one block, same-block target
service/registrar/revocation changes, target collateral spends/replacement, stale
certificates and exhausted allowances. Transaction creation, signing or broadcast
does not apply a penalty; block inclusion and validation do.

EvoDB stores `pose_activity_v2` participation records, `pose_roster_v2` roster
objects and `pose_recovery_v2` state snapshots. State references rosters by hash.
Block disconnect removes branch-specific records/state; reconnect/reindex derives
them again. Missing/invalid required history or roster data fails with a reindex
error rather than silently manufacturing an empty authoritative state. A pruned
node needing a full reindex may need to reacquire missing blocks. Do not attempt
to repair consensus data by hand-editing database records.

## Operator configuration

| Setting or role | Configuration |
| --- | --- |
| Selected signer | Existing registered smartnode with its own `smartnodeblsprivkey` |
| Fee-paying coordinator | Ordinary upgraded full node with a funded wallet |
| Mainnet/testnet activation | Fixed release heights; no command-line override |
| Regtest activation | `poseactivationheight` and `recoveryactivationheight`; RC height must be positive and not precede PoSe activation |
| Legacy `recoverypubkey` / `recoveryprivkey` | Rejected on every network |
| Membership input | On-chain registration and participation; not seed files or monitoring-node lists |

There is no `rc=1` switch or extra RC private key. Supplying `smartnodeblsprivkey`
enables smartnode mode and disables its wallet through existing argument handling.
Use a separate funded wallet node for fees. The signer must be active, registered,
selected, and still eligible; the RPC refuses a non-selected or changed signer.

A minimal signer configuration fragment for an already registered testnet node is:

```ini
testnet=1
server=1
listen=1
smartnodeblsprivkey=<THIS_NODE_OPERATOR_SECRET>
# Configure campaign P2P peers and the registered service using the normal setup.
```

The placeholder is not a usable secret. Keep operator secrets local and RPC
restricted to trusted local access, using cookie authentication where possible.
Do not share keys, cookies or wallet backups with a certificate coordinator.
External P2P reachability still needs normal address, port and firewall setup.

An isolated regtest configuration can use:

```ini
regtest=1
poseactivationheight=60
recoveryactivationheight=1800
```

These illustrative regtest heights are not public-network settings. Recovery
regtest uses actual 100/80/67 thresholds with affordable collateral and fixed
mining difficulty; the small default PoSe regtest profile is a separate mode.

## RPC operating workflow

All examples below use an implementation-containing testnet binary. Add the
correct `-datadir` for each local node. On mainnet omit `-testnet` only after the
coordinated implementation release is deployed.

```text
yerbas-cli -testnet pose status
yerbas-cli -testnet recovery status
yerbas-cli -testnet recovery request TARGET_PROTX_HASH START_HEIGHT END_HEIGHT
yerbas-cli -testnet recovery sign UNSIGNED_CERTIFICATE_HEX
yerbas-cli -testnet recovery merge CERTIFICATE_HEX ANOTHER_SIGNED_CERTIFICATE_HEX
yerbas-cli -testnet recovery maketx CERTIFICATE_WITH_AT_LEAST_11_SIGNATURES_HEX
```

1. Verify chain, mode, selected membership, target identity and remaining budget.
   Independently investigate reachability from multiple network locations; do not
   treat a coordinator's assertion as sufficient evidence.
2. After the observation end is mined, create the unsigned request. Every signer
   should independently recreate the same request from the agreed target/heights
   and compare it. `request` creation alone does not validate every later signing
   and inclusion condition.
3. On each selected smartnode, explicitly sign the identical request. Preserve
   the returned certificate, not the secret key. The signing RPC does not probe
   the target or automatically decide that it deserves a penalty.
4. Merge returned certificates with identical request hashes until at least 11
   distinct selected member signatures are present. `merge` combines signatures;
   it is not a substitute for validation. `maketx` validates the completed
   certificate and returns an unfunded raw transaction with a zero-value data output.
5. On the funded wallet node, call `fundrawtransaction RAW_HEX`; use its returned
   `hex` with `signrawtransaction`, and require `complete: true`. Broadcast that
   signed result with `sendrawtransaction`. Check the fees before broadcasting.
6. Confirm mining before certificate expiry. Inspect `protx info TARGET_PROTX_HASH`
   and `recovery status` for the resulting penalty and consumed allowance.
   An unmined or expired transaction is not a successful penalty.

### Status interpretation

| Field | Interpretation |
| --- | --- |
| `enabled`, `activationHeight` | Consensus activation at the current tip, not committee readiness |
| `mode` | `normal`, `recovery`, or `locked` |
| `failures`, `successes` | Current state's consecutive formation counters |
| `triggerHeight`, `epoch` | Trigger block height and epoch identity |
| `committeeHash` | Frozen roster in recovery; scheduled roster in other modes |
| `committeeSize`, `threshold` | Fixed 15 and 11 |
| `qualified` | Candidates at the displayed roster's selection snapshot |
| `selectionHeight`, `snapshotHeight` | Selection block and historical eligibility cutoff |
| `members` | Displayed roster's registration hashes and operator public keys |
| `eligibleSigners` | Displayed members still passing current registration/state checks |
| `canAuthorize` | Recovery mode, full roster and at least 11 eligible members |
| `budget`, `consumed` | Trigger-time target allowance and number used in this epoch |

`canAuthorize` is not proof of online signers, available signatures, a valid
observation, or remaining budget. It does not check every target-specific
certificate condition. Review `budget` and `consumed` separately. In locked mode,
the displayed roster is scheduled; its presence does not revive expired authority.

## Diagnostics and testing applications

| Symptom / rejection | Investigation |
| --- | --- |
| `enabled=false` | Confirm correct binary/network and activation height |
| Empty `members` / too few `qualified` | Check age, history, state identity and usable mined commitments; do not lower threshold locally |
| `bad-recovery-epoch` | Wrong/expired epoch, normal/locked mode or wrong branch |
| `bad-recovery-budget` | Target already consumed or epoch allowance exhausted |
| `bad-recovery-window` | Observation too short, pre-trigger, future, expired or incorrect expiry |
| `bad-recovery-branch` | Start/end hashes differ from the current chain |
| `bad-recovery-target` | Target missing, banned or changed during the observation/validation interval |
| `bad-recovery-member` / `bad-recovery-signatures` | Selected member changed, invalid signature/index, duplicate index or insufficient signatures |
| `bad-recovery-block-limit` | More than one recovery transaction in the proposed block |
| Reindex-required errors | Missing/invalid indexed participation, roster or consensus state |

Published tests cover deterministic eligibility/ranking, signature thresholds,
state transitions, penalty validation, replay rejection, branch rollback,
restart and reindex. Native fixtures construct authenticated commitments and
cannot establish successful distributed DKG. A two-full-node testnet smoke test
covers startup, synchronization and propagation, not a smartnode fleet.

For the distributed campaign, provision 80–100 funded registered smartnodes;
testnet collateral is 4,000 test YERB each. Verify actual non-null type-4
commitments, sufficient qualifying history, three controlled formation failures,
ten-signature rejection/eleven-signature acceptance, expiry, and return to normal.
Retain at least eleven selected RC signers during the outage exercise. Test
asymmetric reachability, partitions and signer/target changes before deployment.

The implementation's accompanying
[testnet campaign guide](https://github.com/The-Yerbas-Endeavor/yerbas/blob/87d19d498280f1600932d3cccb9981be5b2b5cc0/doc/pose-testnet.md)
contains bootstrap commands and the campaign sequence. No automatic RC scanner,
proof of independent human ownership, or guarantee of network recovery is supplied.

## Source map

All implementation links are pinned to the referenced publication revision so this
reference remains usable before RC code is merged into the documentation branch.

- [Quorum profiles and activation heights](https://github.com/The-Yerbas-Endeavor/yerbas/blob/87d19d498280f1600932d3cccb9981be5b2b5cc0/src/chainparams.cpp)
- [RC constants and serialized structures](https://github.com/The-Yerbas-Endeavor/yerbas/blob/87d19d498280f1600932d3cccb9981be5b2b5cc0/src/llmq/quorums_recovery.h)
- [Selection, state transitions, validation and RPC](https://github.com/The-Yerbas-Endeavor/yerbas/blob/87d19d498280f1600932d3cccb9981be5b2b5cc0/src/llmq/quorums_recovery.cpp)
- [Service-state identity binding](https://github.com/The-Yerbas-Endeavor/yerbas/blob/87d19d498280f1600932d3cccb9981be5b2b5cc0/src/llmq/quorums_pose.cpp)
- [Penalty application and deterministic list updates](https://github.com/The-Yerbas-Endeavor/yerbas/blob/87d19d498280f1600932d3cccb9981be5b2b5cc0/src/evo/deterministicmns.cpp)
