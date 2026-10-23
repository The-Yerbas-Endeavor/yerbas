# Rotating smartnode Recovery Committee: 11 of 15

This implementation replaces the earlier appointed seven-key prototype. Mainnet activation is scheduled: LLMQ_100_67/participation indexing at
block **1,212,840**, then RC authority at **1,214,280**. Certificate/storage domains are now version 2; old
prototype certificates and state are not compatible. Use fresh regtest datadirs
or reindex a compatible test chain. Do not reuse a v1 chain containing penalties.

## Objective

After three consecutive failed LLMQ_100_67 formation sessions, permit a temporary
committee of consistently participating registered smartnodes to authorize bounded
PoSe penalties. Fifteen smartnodes are selected deterministically; eleven distinct
selected operator signatures are required. Membership is not appointed, and
nodes_main.txt and administrator-supplied public key lists play no role.

Several smartnodes may have the same underlying operator. This is a possible
consequence of collateral-backed registrations, not an objective or encouragement.
Distinct registrations and keys do not prove distinct human ownership. Activity
records are not an honesty score or a guarantee of continuous network availability.

## Eligibility rules implemented for testing

All validators derive eligibility from the same historical chain snapshot:

- Valid, confirmed collateral-backed registration; no PoSe ban at the snapshot.
- Registration age at least 720 blocks. A revived node must also have remained
  unrevived for 720 blocks after its last revival.
- Evidence from non-null, validated production quorum commitments (types 1–4).
  A credited member must appear in both validMembers and signers. The aggregate
  members signature authenticates the signer identities; validMembers alone is
  insufficient. No credit is taken from null commitments or test quorum types.
- Look back 1,440 blocks. Require participation in at least three distinct session
  start heights spanning at least 120 blocks. The latest must be within 360 blocks
  of the snapshot.
- Require credit in at least 80% of distinct recorded selection opportunities.
  Multiple quorum types at the same session start count once; a qualifying signature
  in any of those commitments provides credit for that start height. Nodes absent
  from every selected member list at a height incur no missed opportunity.
- Records must match the candidate's current snapshot service identity and operator
  key. Old-key/service records do not qualify a different identity.

An omitted signer in a mined commitment may have been online; this conservative
screening rule does not claim that omission proves misconduct. Failed sessions
without a non-null commitment provide no attributable individual participation.
A valid signature proves participation in signing that commitment, not external
reachability or honest operation. Minimum age and sample count are screening
parameters, not guarantees of independence or security.

These numeric history parameters are implementation defaults for evaluation, not
an agreed mainnet deployment policy. Measure the actual qualified pool and review
the parameters before distributing this scheduled mainnet release.

## Selection and epoch binding

Selection rotates every 360 blocks, and once when RC activation first takes effect.
Eligibility is frozen 60 blocks before selection. A domain-separated seed combines
the genesis, that snapshot's hash and the block hash 30 blocks before selection.
Candidates are deterministically ranked by a hash of the seed and registration
identity, with a registration-hash tie break. Choose the first 15, or no committee
if fewer than 15 qualify. The threshold never automatically shrinks.

The seed is later than the eligibility snapshot and matures before selection.
This reduces opportunities to adapt registrations to a known seed; it does not
make block-derived randomness immune to miner influence.

The latest scheduled roster is frozen when the third failed 100_67 session closes.
Later rotations cannot replace that epoch's members, reset its budget, or extend
its authority. Certificates bind the chain, roster, recovery epoch and target
identity. A signer must still have a valid registration and matching operator/
service identity when the certificate is validated. Removed, banned or changed
members are not silently replaced. Eleven valid selected signers are still required.

Roster data and per-block participation records are stored atomically in EvoDB.
Only roster references, rather than duplicate roster contents, are stored in each
recovery-state snapshot. Historical selection does not require unpruned block
bodies after its participation records have been indexed. Undo/reindex reconstruct
branch-specific activity, selection and penalties.

## Trigger, penalty and authority limits

Only LLMQ_100_67 formation failures count. A session fails when its entire mining
window closes without a valid non-null commitment. Incomplete and pre-activation
sessions do not count. Older quorums may remain capable of signing.

After three consecutive failures, authority is available from the next block only
if a full selected roster exists and eleven eligible signers approve an action.
Two consecutive successful 100_67 sessions end recovery. Recovery also expires
six intervals (360 blocks) after its trigger, then locks until two successful
sessions rearm normal operation. Repeated failure and roster rotation cannot renew
expired authority. Lack of a qualified committee does not create an exception.

The fee-paying version-3/type-10 transaction applies existing CalcPenalty(66),
66% of the dynamic PoSe maximum. It does not confiscate collateral or guarantee
an immediate ban. Existing decay and ban thresholds remain unchanged.

Limits remain one transaction per block, one penalty per target per epoch, and
min(10, floor(valid smartnodes at trigger / 10)) targets total. Fewer than ten
valid smartnodes allow no penalties. These limits can prevent sufficient cleanup
of a severely degraded network. They do not create responsive operators.

Observations start after the trigger and span at least 20 blocks. Certificates
expire 30 blocks after the observation end or on the final authorized recovery
block, whichever is earlier. Changed targets, replays, wrong branches and
same-block target updates/spends are rejected. Mining applies the penalty;
request creation, reports, signatures and transaction broadcast do not.

## Warm-up and installation

Mainnet activation heights are set in chainparams.cpp. Testnet uses blocks 4,320 and 8,640 respectively; see pose-testnet.md. No public roster is configured or needed.
The existing smartnode operator keys identify selected members. The obsolete
recoverypubkey and recoveryprivkey options are explicitly rejected on all networks.
Do not generate or distribute a separate official RC key roster.

Build and install the patched daemon using the repository's platform build guide.
The implementation targets `dev` through PR #53. Build its complete source
revision; do not apply an older 4.0.0.2 cumulative patch to dev or stack patches
on the appointed-key prototype. Back up the wallet and smartnode configuration before replacing
binaries. Existing registered smartnodes retain their registration and operator key;
there is no separate RC registration transaction or permanent RC server role.

For an isolated regtest, configure poseactivationheight and recoveryactivationheight.
No recovery public/private key options are used. This opt-in mode retains the
production 100_67 size and uses affordable collateral/fixed difficulty test fixtures.
It is not a public-network economic change.

Participation indexing starts when 100_67 is enabled, before RC activation if the
heights differ. A coordinated rollout should provide a measured warm-up period
before enabling RC authority. This permits qualifying evidence from existing
production quorum types while 100_67 is forming or failing. Pre-indexing history
is not silently inferred from local logs. If no source quorums produce usable
records, the RC cannot qualify candidates; operators must restore participation.

Selected signers use their existing smartnodeblsprivkey configuration and must run
as registered smartnodes. Keep RPC local, use cookie authentication, and do not
share operator keys or signer RPC credentials with a coordinator. A coordinator
or fee payer can use an ordinary upgraded full node with a funded wallet.

    yerbas-cli recovery status
    yerbas-cli recovery request <proTxHash> <startHeight> <endHeight>
    yerbas-cli recovery sign <unsignedCertificateHex>
    yerbas-cli recovery merge <certificateHex> <anotherSignedCertificateHex>
    yerbas-cli recovery maketx <certificateWithElevenSignaturesHex>

Each signer independently investigates repeated authenticated reachability failures
and recreates the unsigned request from the agreed target/heights before signing.
No RPC command automatically probes the target. Combine at least eleven returned
signatures, create the raw transaction, fund it with fundrawtransaction, sign the
funding inputs with signrawtransaction, and broadcast with sendrawtransaction.
Confirm block inclusion and the resulting protx info penalty and epoch consumption.

Status exposes the selected registration identities/operator public keys, snapshot
and selection heights, qualified count, committee size, threshold, and epoch.
canAuthorize means the mode/roster and current registration checks permit signing;
it does not prove that eleven operators are online or willing to approve.

This scheduled mainnet release needs independent review and coordinated
validator/miner/smartnode upgrades before block 1,212,840. It does not need appointed
RC keys. Old clients reject the new transaction type. Mainnet command-line activation overrides remain rejected.

## Validation commands and scope

    YERBAS_RC_FIXTURE=/absolute/path/rc-fixture.txt \
      src/test/test_yerbas --run_test=pose_tests,recovery_consensus_lifecycle
    python3 contrib/pose/recovery_daemon_test.py --bin-dir src \
      --fixture /absolute/path/rc-fixture.txt

The native fixture creates 80 registrations and cryptographically valid 100_67
commitments, selects 15 qualified members, and constructs an eleven-signature
penalty. Commitments are constructed in the fixture, not formed by distributed
DKG. The exported fixture contains public blocks and expected results, not keys.
The daemon independently replays these blocks and validates selection, penalty,
restart, reorg, reindex, frozen-roster behavior and expiry using real consensus.
These tests do not replace multi-host DKG, live reachability/partition testing,
operator concentration analysis, or review of block-seed manipulation.

## January 2027 activation estimate

The RC target is January 25, 2027, America/Los_Angeles. Using mainnet block
1,146,197 (hash a50392d8d5a59c890ef89f2138c9eb700906708e9010e21427e68b43473dcc8d,
time 1792733476) and the consensus target of 120 seconds per block, project to
January 25 at midnight Pacific and round upward to a 360-block selection boundary.
This yields 1,214,280 (estimated January 25 at 10:57:16 Pacific). Indexing and
100_67 begin 1,440 blocks earlier at 1,212,840 (estimated January 23 at 10:57:16).
Reference: https://explorer.yerbas.org/api/v1/block/1146197

These are fixed heights, not time gates; mining can move the dates. The warm-up
provides time to collect evidence but does not guarantee 15 eligible members.
Only completed 100_67 sessions starting at or after RC activation count toward
its three-failure trigger. Deploying the binary does not immediately enable RC.
