# Recovery committee consensus review

This is a focused implementation review and regression record, not independent
security approval. It covers `quorums_recovery.cpp`, its special-transaction and
deterministic-list integration, and the participation signature verification in
`quorums_commitment.cpp`. Production consensus rules are unchanged by this review.

## Authorization and evidence

An RC certificate requires 11 distinct, ordered signer indices from the frozen
15-member roster. The roster rejects duplicate registrations and operator keys.
Each signing member must still be valid in the previous block's deterministic
list with the recorded service/operator/revival state. Network availability is
not itself a consensus predicate: an offline member cannot supply a new approval,
but previously supplied signatures remain usable while their certificate is valid.

The signed domain binds the network genesis, certificate version, roster, recovery
epoch, target identity and state, observation endpoints and block hashes, and
expiry. The validator checks every target state from observation start through
the previous block, so an intervening state change cannot be hidden by matching
endpoints. Same-block target changes, collateral spending, and replacement are
rejected separately. Signer eligibility is evaluated at the previous block, not
at an order-dependent intermediate transaction state.

Participation credits require valid non-null production commitments and the
member's valid/signing bits. Commitment verification authenticates the aggregate
operator signature. Eligibility uses distinct session starts and recorded
identity/state; null commitments do not create individual participation evidence.
This demonstrates participation, not operator independence or honesty.

## Bounded authority

Three consecutive completed failed sessions activate recovery. A successful
session resets the failure streak. In recovery or timeout lock, a failed session
resets the success streak; two consecutive completed successful sessions restore
normal mode. Incomplete sessions do not change either streak.

The active roster, epoch and penalty budget remain frozen despite later roster
rotation or eligible-pool growth. Each target may be penalized once per epoch,
only one RC transaction is permitted per block, and the budget is capped at ten
and at one tenth of the valid population at triggering. Timeout locks authority;
continued failures cannot renew it. A later epoch requires successful restoration
followed by a new three-failure streak.

## Added regression coverage

Run after building:

```sh
src/test/test_yerbas --run_test=pose_tests,recovery_consensus_lifecycle
```

Validation on October 23, 2026: the build and all 12 selected cases passed.
New assertions cover:

- A success interrupting the three-failure trigger sequence.
- A failure between recovery successes requiring two fresh successes.
- Frozen roster, epoch, budget and consumed targets during recovery.
- Budget rounding below ten nodes, the ten-target cap, and a fresh epoch reset.
- Timeout boundaries and continued failures not renewing authority.
- Tampering with every signed certificate field, out-of-range signer indices,
  and reordered signatures.
- Same-block collateral spending in both transaction orders and collateral
  replacement.
- Eight distinct funded penalty transactions exhausting an eight-target epoch
  budget, followed by rejection of a fully signed ninth certificate.

The lifecycle fixture constructs cryptographically valid commitments; it does
not perform distributed DKG. The separate real-DKG campaign documented in
`pose-testnet.md` tests the 100-smartnode lifecycle. Its prior successful run is
not a rerun of network fault scenarios in this review.

## Remaining acceptance work

Independent consensus review and separately hosted tests remain necessary before
release. Follow-up localhost campaigns now cover an interrupted real-DKG recovery streak
and stopped RC signer processes; see `pose-testnet.md` for results. Tests across
independent hosts must still cover asymmetric connectivity and intermittent
failures. Additional work includes reorganization
boundaries around activation, roster selection and timeout. Prior local replay
and partition tests provide coverage but do not establish those external-network
properties. On-chain validation cannot establish that a reachability accusation
is true; signers still need an explicit evidence and signing procedure.
