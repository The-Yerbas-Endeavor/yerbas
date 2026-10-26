# LOW_LLMQ history migration

Status: proposed migration rules. Public-network activation is disabled; this
commit publishes an isolated, tested manual-history prototype, not a mainnet
activation or a complete migration implementation.

## Operator workflow

Use the existing spork authority to turn LOW_LLMQ ON and later OFF. There is no
automatic expiry. The production Qt/RPC command should fund, sign and broadcast
the history record and report its confirmation/effective height. Operators
should not assemble raw transactions or manage migration files themselves.
The isolated prototype now provides `quorum recovery on|off|status`, using the
selected wallet for fees and the configured spork key for authorization. The
legacy broadcast-only spork command does not create a chain record. Public
activation and migration remain unfinished.

A confirmed ON record takes effect at a future quorum boundary. OFF takes effect
at a later boundary and retires low-quorum signing without invalidating old
blocks. Fresh nodes reconstruct both transitions from blocks. Records are bound
to the configured authority, network, ancestor block and previous authorization.
Reject replayed records, wrong signatures and overlapping pending transitions.
The initial public policy must accept manual version 2 only; automatic-expiry
version 1 remains an older experimental format.

## One-time migration rules for existing history

1. **Preserve the existing chain.** No reset, registration replacement, collateral
   change or node-renewal scheme is part of this repair.
2. **Audit and pin the legacy prefix.** Select an audited height H and block hash.
   Ship an immutable, release-reviewed historical rule table for that exact
   prefix. This is an explicit checkpoint/trust decision: missing old spork
   authorization cannot be recovered from commitment signatures alone.
3. **Bind exceptions exactly.** Historical signed commitments must match their
   approved quorum hash, mined-block/transaction hash and full parameter profile.
   Reconstruct membership and verify thresholds and both signatures. Do not infer
   permission to use a low threshold merely from a 200-slot bitset. Cover null
   commitments, other quorum types, count transitions and PoSe decay as well.
4. **Replay deterministically.** Use the audited rules, never today's spork, to
   reconstruct legacy state. Independently compare block hashes and smartnode
   states. A conflicting prefix cannot inherit an exception. Missing or
   ambiguous audit data blocks activation; it does not trigger permissive
   fallback or bypass signature verification.
5. **Leave no gap at cutover.** Pick activation height A only after every block
   through A-1 has a defined replay rule. Any interval between the audited prefix
   and A must use agreed deterministic rules, validated against all blocks
   already produced there. Do not invent historical boundaries from timestamps
   or a wallet's current state. If a compatible transition cannot be coordinated,
   extend the audit and defer activation.
6. **Start the new system OFF without requiring a working quorum.** A
   release-defined, network-bound bootstrap state initializes recorded history;
   an old active spork cannot implicitly enable it. Normal quorum formation is
   not a precondition: the purpose includes recovery from stalled DKG. Ordinary
   proof-of-work blocks must still advance and include an authority-signed,
   fee-paying ON transaction. Submission, relay, funding and block validation
   must not require InstantSend or an existing threshold signature. Subsequent
   OFF also requires a newly signed, confirmed record. Preserve registrations,
   collateral and the reconstructed PoSe state across cutover; initializing
   recovery authorization OFF is not a reset of those states. Reorgs restore
   branch-local state; reorgs conflicting with a pinned legacy prefix follow
   its separately approved checkpoint rule.

The audit table must identify the network, checkpoint, canonical schema/digest,
complete historical profiles and PoSe rules, source evidence, and reference state
hashes. It is release data maintained by developers, not an operator setting or
mutable download. Neither those data nor H/A have been selected in this commit.

## Before public activation

Require fresh genesis sync, reindex and matching smartnode state across the
legacy prefix, cutover, ON, OFF and a second ON. Test real DKG and PoSe, normal
quorum return, rollback/reorg, unauthorized low commitments, tampered migration
data, and the finished Qt/RPC workflow. Explicitly test a stalled normal quorum
at cutover: an ordinary mined ON transaction must still permit recovery. The prototype's passing isolated tests
cover manual ON/OFF, no expiry, DKG/PoSe, normal return, fresh replay, reindex and
OFF rollback; they do not establish completed mainnet migration.

Protocol 70224 continues to accept older peers during the initial release.
Minimum-version enforcement remains a separate later decision. Before activating
new consensus rules, compatible validator adoption must still be established.
No shared-testnet deployment or spork change is part of this commit.
