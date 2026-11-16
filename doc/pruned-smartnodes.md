# Experimental pruned smartnodes

This work includes isolated regtest experiments and a controlled private
testnet trial, not a declaration of supported pruned operation on public networks. Keep archival nodes available. Do not
change a live smartnode to pruning based on these tests alone.

## Historical governance

During block connection, a pruned node retains transactions containing a
proposal-sized, sufficiently funded burn output in its block-index database.
Only transactions from locally validated blocks enter this store. Governance
still checks the exact proposal hash, output scripts, fee and active-chain
confirmations. Disconnected collateral does not become valid merely because
its record remains on disk. This store adds persistent storage proportional to
qualifying burns; it is not an unlimited historical transaction index.

The store cannot recover transactions already deleted before this software was
installed. An upgrade from an existing pruned data directory needs an archival
rebuild to establish complete historical coverage. Missing records fail closed.
The store is local validated state, not an import API for untrusted receipts.

## InstantSend

Unspent confirmed input values and heights come from validated chainstate,
which survives pruning. Mempool parents still require their existing lock.
For a tracked mined transaction, spent inputs can be recovered from its retained
spending block and checksummed undo data. Recovery checks the active chain,
block Merkle root, exact spending transaction and input, and a nonzero original
coin height. Legacy undo records without that height fail closed. Fully spent
transactions retain their tracked transaction and mined height for signing and
normal confirmed-lock cleanup. Missing evidence retains the archival fallback;
it does not grant a lock.

This is not arbitrary historical InstantSend recovery: cold-start rediscovery
of old spent transactions and late locks after tracking has been discarded need
further coverage. Required-signer ChainLocks are covered after deletion and restart. Broader
long-running public-network coverage remains necessary.

## Historical list proofs and quorum indexes

Pruned nodes retain the coinbase, quorum commitment transactions, and Merkle
proofs for each locally validated block. Historical smartnode-list differences
use the retained coinbase proof when the original block has been deleted. The
proof is checked against the indexed block header; deterministic registry state
and the existing active-chain checks are still required.

The regtest-only `-llmqtestrebuildindex` startup option rebuilds mined quorum
commitment indexes from full blocks or verified retained evidence. It validates
the entire available history before one atomic database update, preserving
unrelated records. Missing evidence refuses startup recovery without changing
the indexes. Normal startup without this test option can use the original
indexes. The option is rejected on public networks.

This does not recover a lost deterministic registry, DKG signing keys, wallet,
or payment journal. Retained evidence must exist from before deletion; older
pruned directories require an archival rebuild. No external metadata import is
provided.

## Deep reorganization recovery

Before disconnecting an active chain segment, the node checks that every block
and undo record is available. If pruning deleted a required record, rollback
is refused before changing the tip. The competing chain is not labelled
consensus-invalid just because local history is missing.

This refusal does not restore synchronization. An operator must recover the
missing history. Do not delete replay protection, governance data, keys or
wallets to bypass the refusal. Do not simply reconsider the block and assume
missing files have returned.

A conservative recovery procedure is:

1. Stop the affected node and preserve its complete data directory and config.
2. Prepare a separate recovery directory on the same network with the same
   genesis and consensus configuration. Keep wallet and RPC credentials out of
   shared archives. Leave the original directory unchanged.
3. Obtain complete block files from an archival source, or synchronize a fresh
   node from genesis. Treat archive contents as untrusted: rebuild with full
   validation (`-reindex -assumevalid=0` for block-file recovery), without
   importing another operator's chainstate or private keys.
4. Check the recovered network, tip, chainwork, registry and relevant payment
   history against the intended network. Retry the previously unavailable
   rollback only on the recovered copy, and verify its result.
5. Restore the operator's own identity and wallet configuration only through
   the existing protected deployment process. Check quorum participation and
   payment observation before returning the node to service.

The isolated recovery probe exercises block-file rebuilding and rollback; it
is not an automated production recovery tool. In particular, it does not
migrate live wallet, authority or payment journals.

## Verified local coverage

The isolated regression deletes a normal 128 MiB block file through the
pruning RPC, then checks historical collateral and exact historical list-proof
agreement after restart, wrong-proposal rejection, atomic quorum-index rebuild,
fresh DKG and signing, and InstantSend with the pruned signer required for a
two-of-three threshold, including confirmed-lock retirement. The InstantSend
scenarios include unspent historical
inputs, a mined spent input, and a fully spent child plus descendant.

A six-block fork and stale payment-proof refusal are covered. A higher-work
deep branch is offered through block submission; archival rebuilding recovers
it and permits switching back to the original valid branch. Separate tests
cover missing retained evidence, unchanged indexes on recovery refusal, and
rejection of the test-only recovery flag outside regtest.

Local extension tests also cover a 550 MiB automatic pruning target, required
ChainLock signing after restart, historical proposal votes, and a signed
superblock payout validated by a pruned copy. The payout recovery probe checks
missing-payout rejection, restart, rollback, stale-proof refusal and
reconsideration. These remain regtest experiments with accelerated budget and
quorum settings.

Public-network readiness still requires long-running testnet operation with
public network parameters, broader historical InstantSend recovery,
retention-growth/performance testing, and deployment of payment-observation
recovery. These experiments do not enable live pruning.

The final compiled core suite passed all 330 tests, including retained-proof
tampering, exact spent-input undo binding, legacy missing-height refusal, and
atomic quorum-index recovery refusal. Six payment-witness tests and the existing
manual quorum-recovery functional regression also passed.

## Repeating the extended experiments

Use the functional test runner with `feature_pruned_smartnode.py`,
`feature_pruned_smartnode.py --automatic-pruning`, and
`feature_pruned_governance.py`. The automatic scenario uses `-prune=550` and
normal block-file allocation. Budget overrides and affordable smartnode
collateral are confined to regtest. Keep sufficient temporary disk space for
archival peers as well as the pruned node; the pruning target is not a limit on
total directory size, indexes, wallets or retained metadata.

After a disconnection these tests advance their simulated clock while waiting
for signatures so that peer retry timers can run. A signature timeout must be
investigated rather than counted as a successful pruning result. Final evidence
must include each required assertion, not merely successful startup.

The combined network regression also rejects a competing native-PoW block after
a ChainLock without changing the tip, and validates an actual signed-trigger
superblock payout after historical voting and restart.

## Private testnet peer routing

A pruned node still needs archival peers for data it no longer has. Keep the
chain observer independently connected to an archival source; do not make its
only source the pruned smartnode it observes. This version does not advertise
full archival service from a pruned node. A matching local tip alone is not
evidence that upstream connectivity remains healthy. Monitor the intended
upstream connection and the observer tip separately.

In the disposable-server trial, a source configured for 16 total connections
had exhausted its available inbound slots. Raising its bounded connection
limit to 64 restored the private relay. This limit is a deployment choice, not
a universal recommendation. The temporary SSH relay was disabled when the server trial ended; the
continuation uses local archival peers.

The 100-node scale trial uses distinct wallet-disabled processes with pruning
enabled, initialized from a consistent, already-validated public-chain snapshot.
It is not 100 independent genesis validations, 100 registered smartnodes, or
100 independent operators. Quorum tests use separately registered isolated
regtest smartnodes. Shared ownership and private testnet collateral options
remain explicit limitations.

## Automatic quorum peer connections

Use `addnode` for a preferred archival peer when operating a smartnode. In this
version, configuring `connect` disables the dedicated smartnode connection
thread, so chain synchronization can succeed while DKG contributions cannot
be exchanged.

Dedicated outbound smartnode links no longer require the remote peer to
advertise archival block service. They still use the existing native smartnode
authentication and quorum membership checks. Ordinary automatic block-download
connections retain the full-storage service requirement, and pruned peers do
not advertise archival capability. This change does not authorize an arbitrary
peer as a quorum signer.

`feature_pruned_quorum_connections.py` checks automatic authenticated links,
real DKG contributions, a mined commitment and a recovered signature with all
three operator nodes configured for pruning. It deliberately avoids manually
connecting operators to one another, which would bypass the automatic-peer
service check. The previously deployed binary fails at the contribution phase;
the corrected binary passes. This test does not delete historical block files;
the deletion and historical recovery tests above cover that separately.

The disposable private testnet used 20 additional registered smartnodes and
80 testnet coins locked as collateral. Their protected state was preserved and
the cohort moved to local machines for continued testing. These are same-owner
nodes on the private testnet profile, not independent public-network validators.

The corrected private-testnet trial exchanged all eight selected reachable
members' contributions at height 1140 and mined their genuine commitment at
height 1151. Earlier sessions with only five, six or seven reachable selected
members correctly failed the eight-member formation requirement. No threshold
was lowered and no synthetic commitment was inserted. A recovered signature
was subsequently observed after the signing-height offset. This is evidence
for the corrected peer path on the private profile, not public-network pruning
approval or evidence of independent ownership.

Live restart recovery also passed: the restarted member retained the earlier
recovered signature, then supplied a required share in a second signature
requested from exactly seven members. The observer rejected a different
message for the first request and recognized the conflict. All nine application
payment records remained intact and four application replicas agreed.

The post-repair observation recorded 13 healthy samples over approximately
57 minutes. The planned 48-hour observation was stopped to avoid further
server rental costs; it did not pass a 48-hour endurance requirement. Recovery
archives and evidence were preserved on two local hosts before retirement.

The live trial generated 142 large blocks and rotated block files at height
1302. Local continuation is advancing the retention window before attempting
native block-file deletion, followed by quorum formation, required-signer
restart, payment-proof checks and archival recovery. Those post-deletion live
results are still pending. Successful live quorum formation and restart above
preceded deletion; actual deletion coverage currently comes from the isolated
regressions. Public-network pruning readiness is not established.
