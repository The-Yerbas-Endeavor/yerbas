# Proposed deterministic LOW_LLMQ recovery protocol

Status: integrated experimental regtest implementation. Authenticated records
now drive quorum parameters, membership, DKG snapshots, PoSe decay, retention,
and signing expiry. Public-network activation remains disabled/unassigned.
The legacy spork-only negative control still fails; it is not silently
reinterpreted under the new protocol.

## Why the current message cannot be the historical authority

`GETSPORKS` sends only the latest active message per signer. A fresh node cannot
recover earlier LOW_LLMQ intervals from it, even though a continuously running
node may have observed those messages. Local observation time must not decide
block validity. Copying `sporks.dat` between operators is not a consensus fix.

A new recovery request must be authenticated and recorded in the chain before
it changes validation. No rule may choose a weaker parameter set because a
received commitment happens to fit it.

## Proposed record and authority

Use a new versioned special transaction containing the network genesis hash,
a previous authorization identifier, start quorum height, exclusive end quorum
height, and signatures from the existing network spork-signing authority at its
configured signature threshold. Use a dedicated signature domain; existing
wall-clock spork signatures must not authorize these records. Bind the signed
record to a recent ancestor block to prevent reuse on unrelated fork histories.

The record must be mined before the first affected quorum begins. Start/end
must align with the affected quorum's DKG interval. Reject conflicting,
overlapping, expired, duplicate, wrong-network, wrong-ancestor, and insufficiently
signed requests. Define a bounded maximum duration as a consensus parameter.
Do not choose or enable a mainnet value without a network deployment decision.
Early termination, if supported, is another authenticated record effective at a
future quorum boundary; it cannot retroactively change an in-flight quorum.

The existing LOW_LLMQ spork can remain an operational signal, but after protocol
activation it must not independently change historical quorum or PoSe rules.

## State and parameter resolution

Store recovery state by block hash in the evolutionary database, transactionally
with block connection. Resolve a candidate block from its parent state, and
restore the previous state on disconnect. Include this state in snapshots and
reindex/replay paths; never initialize it from wall-clock spork state.

Resolve an immutable parameter value for `(quorum type, quorum block hash)`.
Freeze both the size schedule and recovery mode at the specified quorum context.
The adaptive normal-size rule also needs a precisely specified list snapshot;
it cannot depend on a historical query mutating the live global map. Preserve
legacy behavior behind a separate compatibility resolver until new rules are
activated. Do not reinterpret existing blocks under the proposed rule.

Pass the resolved value to commitment-size checks, non-null signature validation,
member selection, DKG session creation, quorum objects, and signing-share checks.
The new `CFinalCommitment::Verify(params, ...)` and `VerifyNull(params)` provide
the validation boundary; legacy callers still use the existing global selection.
They are not a historical resolver and do not authenticate the supplied context.

Resolve PoSe recovery from the block's chain-derived recovery state. Keep
historical penalty schedules intact. A quorum started under recovery mode keeps
its original membership and threshold through its commitment mining window.

## Ending recovery must also end reduced signing authority

Restoring normal parameters for newly created quorums is insufficient: existing
low-threshold quorum keys may remain in the active signing set. Define explicit
eligibility expiry for recovery quorums in ChainLocks/InstantSend and recovered
signature handling. Historical commitment verification still uses their original
parameters. Do not replace historical verification with today's normal values.

If no normal quorum is available after expiry, signing must pause rather than
silently extending low-threshold authority. This availability tradeoff needs to
be explicit in the protocol and tests. Never disable block validation, signature
checks, or thresholds to compensate for an unavailable normal quorum.

## Legacy compatibility evidence still required

The verified replay covers genesis through checkpoint 42069 with the current
spork off. It does not establish every later mainnet interval or identify the
exact failure in older wallets. The local raw archive audit is separate from
full consensus validation. The audit exposed a mistyped checkpoint at 1078436; the correction was
corroborated by the public explorer and a header-derived native test. The audit
through local tip 1143209 finds no additional type-1 size-200 commitments, but
is not a full consensus replay through that height.

No public activation height or recovery duration has been assigned. The prototype
reserves transaction type 10 only behind `-llmqrecoverytest` on regtest; ordinary
nodes reject it. Public networks reject the flag. Test policy uses existing
regtest spork authority, a 30-block interval, and 60-block duration/start-delay/
anchor-age bounds. Serialization caps signatures at 16 before allocation.

The prototype stores authenticated state per connected block hash in CEvoDB,
using the surrounding block transaction for atomic rollback. Signed fields bind
the network, recent ancestor, preceding authorization, and future window.
A new record cannot replace a pending or active window. Expiry requires no off
message. Early termination is not implemented.

`quorum recoveryrequest` signs a test payload using the configured regtest spork
key; `quorum recoverystate` inspects stored state. These RPCs are experimental.
Existing regtest databases need a reindex when enabling the feature.

The type-1 resolver freezes the recovery mode and total registration count at
the parent of the quorum-start block. Normal templates remain size 3 below 5
registrations, size 10 below 100, and size 50 otherwise; LOW uses size 200,
minimum 2 and threshold 2. Banned registrations still count in this normal-size
schedule, as in the legacy rule. Eligible member selection uses the existing
quorum-block list and excludes banned identities. No commitment bitset selects
its own parameters. The global updater is disabled only in experimental mode.

DKG sessions and quorum objects own their resolved parameters in experimental
mode. Signature-share inventory lengths use the session/quorum snapshot.
Commitment-root retention and active signing pools resolve their policy from
the relevant branch/height. PoSe decay uses the parent recovery state for the
candidate block (every 30 blocks while active, otherwise every 2).

Reduced-authority quorums are excluded from signing selection at expiry and
from current active-quorum checks used for received shares/recovered signatures.
Queued local signing checks eligibility again before signing. Historical
commitment validation retains the quorum's original parameters. Normal quorums
may continue signing; if no eligible replacement exists, signing pauses.

This does not reconstruct unknown legacy spork history. Historical mainnet
windows and legacy behavior remain on the existing path. A public deployment
still needs an explicit activation/compatibility policy, network authorization
and bounds, and wider adversarial/network-scale testing.

## Required acceptance tests

* Fresh nodes with empty databases converge during recovery, after expiry, and
  regardless of current spork state. Early termination is not implemented; it
  would require separate tests if introduced.
* Restart, reindex, invalidate/reconsider, and competing-work forks restore the
  same mode, members, commitment validity, and deterministic PoSe state.
* Signed recovery records reject wrong authority/domain/network, replayed or
  conflicting records, invalid boundaries, and excessive duration.
* Ordinary blocks cannot select weaker parameters through commitment sizes.
* Quorums crossing an expiry boundary complete under their frozen parameters;
  expired recovery quorums cannot issue new authoritative recovered signatures.
* Real DKG identifies a selected offline member, bans it through existing PoSe
  enforcement, excludes it from later quorums/payments, and returns to normal
  quorum thresholds without a mandatory follow-up operator action.
* Historical mainnet fixtures retain identical accepted blocks and list roots.


## Isolated network activation policy

The operator chose a new isolated developer network rather than restarting
public testnet. `-llmqrecoverydevnet` enables the experimental protocol from
bootstrap on a named devnet and requires a dedicated public authority address.
It cannot be enabled on mainnet or public testnet. Name and authority determine
peer wire magic; recovery authorizations must anchor into the named history at
height 1 or later. The profile uses 90-block maximum windows, 30-block DKG
intervals, and 60-block limits for scheduling delay and anchor age. The test
harness keeps its generated authority private key local and exports public
identity only. See the investigation report for parameters, commands, and
validation results. Production activation and authority governance remain
separate work.
