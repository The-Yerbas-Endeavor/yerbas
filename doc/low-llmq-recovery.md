# LOW_LLMQ recovery investigation

This investigation starts from `4815c09d086866df84377c7f805b4b65d3ca2e01`
on branch `4.0.0.4`. Public-network quorum/PoSe consensus, historical activation rules, and mainnet sporks are
unchanged. A separately verified mainnet checkpoint typo is corrected below. An explicit regtest-only DKG fixture is added.
The current chain-record implementation repairs the tested replay paths on
explicitly opted-in regtest nodes, with a separate isolated developer-network
profile described below. It is not a mainnet deployment. Earlier
sections below preserve the investigation and prior milestones; see the current
integration results at the end.

## Evidence from the implementation

* `CSporkManager::IsSporkActive` compares the latest accepted value with
  `GetAdjustedTime()`, not the height/time of the block under validation.
  `sporks.dat` serializes spork maps, but validation does not select historical
  values from them. The active map replaces older messages per signer.
* `BuildNewListFromBlock` and `GetListForBlock` both call `UpdateLLMQParams`
  with the current LOW_LLMQ spork. The latter can mutate global consensus
  parameters while answering a historical query.
* The static cache requires `lastCheckHeight < height`; it has no disconnect
  rollback and is not reset by `SelectParams`. Mining-window suppression also
  depends on whichever global parameters happen to be installed.
* `ProcessSpecialTxsInBlock` validates quorum commitments before processing the
  deterministic smartnode list. `CFinalCommitment::VerifyNull` and `Verify`
  check vector lengths against the mutable global parameter map. Consequently,
  a parameter transition can change the acceptance of an identical commitment.
* The general mainnet selection conditions and unchanged-count fallback have
  different boundaries. For example, a direct lookup at 8319 selects LOW_LLMQ,
  while an ascending, unchanged-count sequence switches back at 8319. This is
  a characterization of the existing code, not permission to change history.
* PoSe decay also reads current spork state above 37650. Fixing only quorum
  sizes would leave historical list-state reconstruction nondeterministic.

## Ghost smartnode scope

`CalculateScores` selects confirmed, non-banned entries with payable collateral
at the list height. It has no network-liveness input, so eligible offline nodes
can be selected. Selection is bounded by quorum size; a 200-member quorum does
not cover every registered node when there are more than 200 eligible nodes.

`VerifyAndComplain` marks missing contributions bad locally. The separate
bad-vote path has threshold 8 in `llmq200_2`; this does not mean eight votes are
required for every missing-contribution failure. A successfully finalized,
mined, non-null commitment is necessary for `HandleQuorumCommitment` penalties.
Null commitments do not punish anyone.

Each failed selected member receives floor(66% of max(100, registered count)).
Penalties saturate at that maximum and set a PoSe ban height. Sufficiently close
failures can ban a node; recovery between failures and how often it is selected
matter. Above 37650, current LOW_LLMQ state changes recovery from every second
block to every thirtieth block. The hard-coded recovery windows are separate
from quorum activation windows and must also be preserved during replay work.

Banned entries remain registered but are excluded from valid-member selection
and future payee selection. A payee already chosen from the previous list can
still receive the current block's payment. Explorer visibility alone therefore
does not establish eligibility. No live explorer records were classified here.

Two signatures meet the configured minimum and threshold but do not establish
honest participation, sufficient connectivity, successful DKG, or comprehensive
ghost cleanup. The follow-up below verifies one isolated three-member/two-contributor case;
it does not establish mainnet security or comprehensive cleanup.

## Reproduction commands

Build with the repository's Autotools build system and compatible dependencies.
The investigation used system OpenSSL 3.5.5, system Boost/BDB, and an existing
compatible chiabls prefix, with wallet/tests enabled and GUI/bench disabled.
An older depends prefix failed configuration because OpenSSL >= 3.5 was absent.

Run each characterization case in a fresh process. They are disabled by default
because the production static caches otherwise contaminate other tests. They
assert observed defects, not desired future behavior:

```sh
src/test/test_yerbas --run_test=low_llmq_characterization/continuous_historical_windows
src/test/test_yerbas --run_test=low_llmq_characterization/fresh_historical_boundary
src/test/test_yerbas --run_test=low_llmq_characterization/spork_transition_and_backward_lookup
src/test/test_yerbas --run_test=chainparams_tests,low_llmq_pose_tests
```

The opt-in functional reproducer asserts convergence and is intentionally not
registered in the default passing test runner while the defect remains:

```sh
python3 test/functional/llmq-lowparams-replay.py --scenario=fresh-active
python3 test/functional/llmq-lowparams-replay.py --scenario=restart
python3 test/functional/llmq-lowparams-replay.py --scenario=fresh-inactive
python3 test/functional/llmq-lowparams-replay.py --scenario=rewind
python3 test/functional/llmq-lowparams-replay.py --scenario=fork
```

These use isolated regtest nodes and null commitments, not smartnode DKG.
`rewind` uses invalidate/reconsider across activation; it is not a competing
fork reorganization test. The separate `fork` scenario isolates a normal-spork
peer at height 60, activates LOW_LLMQ on the other peers, and reconnects the
isolated peer after it mines a higher-work normal-parameter fork to height 150.

## Safe repair requirements

A safe fix needs an agreed, replayable activation/deactivation record tied to
chain history, immutable quorum parameters resolved for the relevant quorum,
and deterministic PoSe recovery. The latest wall-clock spork alone cannot tell
a fresh node when a past temporary interval began or ended. Persisting local
activation observations alone cannot solve fresh synchronization or forks.
Inferring permissive parameters from untrusted commitment sizes would weaken
validation and is not an acceptable workaround.

Before selecting a compatibility rule, obtain actual mainnet blocks, list
snapshots, and available historical spork/rejection logs around all activation
boundaries, and replay them with the candidate implementation. Extend tests to
real DKG with selected offline members, threshold-two sparse participation,
restarts, deactivation, and competing forks. Do not deploy or activate LOW_LLMQ
on mainnet on the strength of these diagnostic tests.

## Results (2026-10-24, America/Los_Angeles)

The full `make -j6` daemon/CLI/unit-test build succeeded (exit 0).
The diagnostic follow-up also built with
`make -j4 -C src yerbasd test/test_yerbas` (exit 0).
The initial diagnostic change adds type, quorum hash, minimum size, threshold,
and DKG interval to existing commitment-size rejection logs. Rejection
conditions and return values are unchanged. The original `4815c09` logging
compiled successfully; its two paths do not cover the reproduced invalid-null
failure.

| Test | Exact result |
| --- | --- |
| Existing chainparams tests + new PoSe/payment test | 3 cases, 38 assertions passed; exit 0 |
| Existing `evo_dip3_activation_tests` | 2 cases, 947 assertions passed; exit 0 |
| Continuous historical-window probe | 1 case, 37,651 assertions passed; exit 0 |
| Fresh height-8319 probe | 1 case, 1 assertion passed; exit 0 |
| Spork transition/backward-lookup probe | 1 case, 6 assertions passed; exit 0 |
| Continuously running regtest peers | Same chain at height 120 after activation; at height 180 after deactivation |
| Fresh replay while LOW_LLMQ active | FAIL, exit 1: stops at height 9; block 10 rejected, size 3 versus expected 200 |
| Restart during LOW_LLMQ, then extend chain | PASS, exit 0; peers converge at height 150 |
| Fresh replay after deactivation | FAIL, exit 1: stops at height 69; block 70 rejected, size 200 versus expected 3 |
| Invalidate/reconsider across activation | FAIL, exit 1: stops at height 39; block 40 rejected, size 3 versus expected 200 |
| Higher-work competing fork across activation | FAIL, exit 1: LOW_LLMQ peer rejects the normal-parameter fork with size 3 versus expected 200 |

The four convergence failures above report `bad-qc-invalid-null`. They are
actual isolated-daemon reproductions, not simulations. The new log was observed
on the failing path with `llmqType=1`, `minSize=2`, `threshold=2`, and
`dkgInterval=30`. This proves a replay defect on regtest; it does not establish
that every historical mainnet incident had exactly the same rejection path.

Initial attempts and limitations:

* Sandbox listeners were unavailable; isolated localhost tests were rerun with
  network-capable execution. No public-network node was started.
* The initial PoSe test fixture used regtest's empty collateral schedule and
  selected zero members. It was corrected to an in-memory mainnet-schedule
  fixture; the final test passes.
* Bulk mining with near-identical timestamps caused the first deactivation
  test to time out on RPC. The final reproducer advances mock time 150 seconds
  per block and asserts block counts; it reproduces a consensus rejection.
* The existing `llmq-simplepose.py` run was stopped during funding setup after
  several minutes (exit 143). It never reached DKG assertions. Its baseline
  timing/setup needs repair before it can validate end-to-end ghost cleanup.
* At the initial milestone, no mainnet replay or real sparse DKG was complete.
  See the follow-up below for subsequent results. The full unit suite and a
  live explorer audit remain outstanding.

The primary success criterion is **not met**: fresh nodes still diverge.
The demonstrated mechanism is current-spork/global-state-dependent historical
validation, compounded by non-rewindable caches and boundary-dependent rules.
No consensus repair is claimed or committed without mainnet compatibility
fixtures and a replayable activation design.

## Historical archive and real-DKG follow-up

The checkpoint fixture extractor in `contrib/llmq/extract_replay_fixture.py`
reads only raw archive files. It verifies checkpoint ancestry, transaction
Merkle roots, payload heights, and commitment serialization. Its manifest is
explicitly **not** a consensus-validation certificate; daemon replay is separate.
Seven extractor tests pass, including out-of-order archive records, truncated
payloads, invalid Merkle roots, wrong ancestry heights, and unchanged sources.

Local mainnet archive fixtures now cover checkpoints 8837 and 42069. The latter
contains 42,070 blocks and 10,377 commitments, with SHA-256
`f43fe3fbd63a65c8df905a17ba5fbcdd445bad3a2ecb47ae3b32f2a6329152b1`.
Serialized type-1 vector sizes first change at the following commitment heights:

| Height | Size |
| --- | --- |
| 10 | 3 |
| 2740 | 10 |
| 6760 | 200 |
| 8320 | 10 |
| 15910 | 200 |
| 16420 | 10 |
| 20380 | 50 |
| 22780 | 200 |
| 37660 | 50 |

These are observations from blocks, not a proposed activation schedule.
An isolated offline replay with `-assumevalid=0` reached checkpoint 8837,
`25c1c019d70e6990d3ed680fa9703cb84d620008a6cb8f635bbcdcef913dfbae`.
The current LOW_LLMQ spork was off. Thus current code can replay the first
historical window in that configuration; this does not establish the precise
failure in older wallet versions or prove replay with the spork on.

`-llmqtestfixture` is an explicit regtest-only option for affordable collateral,
early smartnode payments, and fixed test difficulty. Ordinary regtest and public
network parameters remain unchanged. Selecting a public network with the flag
throws an error. The updated native suite passes 4 cases / 46 assertions.
The opt-in `test/functional/llmq-lowparams-pose.py` exercises actual operator
contributions and commitments rather than synthetic null commitments.
Unsynced operator nodes must bootstrap outbound: they reject inbound peers.
DKG final commitments are produced after entering phase 6, not during phase 5.

### Repair architecture constraints

A cache reset alone cannot repair this feature: the latest spork message does
not encode the sequence of historical activation and deactivation intervals.
The same block history and latest spork can result from different local spork
arrival times. No deterministic historical resolver can recover missing
information from those inputs alone.

A future protocol needs authenticated mode changes recorded in chain history,
with network-specific domain separation, replay protection, and bounded expiry.
It must define when a transition takes effect relative to DKG boundaries, retain
the parameter set of every in-flight quorum, and apply the same chain-derived
mode to PoSe decay. Disconnect/reconnect must restore mode state with chain state.
Expired recovery mode must restore normal thresholds without depending on a
later operator action or a fresh wall-clock message.

Before enabling that protocol anywhere public, the legacy range needs a verified
compatibility policy, including any LOW_LLMQ periods after 37650. The checkpoint
fixture here ends at 42069 and cannot establish later network history. Signing
authority, maximum recovery duration, and deployment mechanism are consensus
choices, not incidental cache fixes. The later regtest-only record prototype
below does not assign public activation. Further integration must be reviewed
against these constraints and rerun the failing convergence scenarios.

### Verified follow-up results

The complete isolated replay reached height **42069** and checkpoint
`729ee24deac4d1df060191debdf52079a70987dc2001e058002641a1412d3782`,
then shut down normally (exit 0). It validated all three historical LOW_LLMQ
windows with the current spork off, `-assumevalid=0`, no wallet, no listeners,
no outbound connections, and the checkpoint-anchored local block fixture.
Import progress was not used as a substitute for connected-chain validation.
This is a baseline on current code, not validation of a consensus repair.

The real DKG run finalized a healthy type-1 quorum with three valid signers at
height 131. With one selected operator stopped, two operators finalized a
size-200 type-1 commitment at height 161 marking that identity invalid.
The separate type-100 regtest commitment also marked it invalid in that block;
the combined penalties reached 100 and banned the identity at height 161.
Both online identities retained penalty 0 and ban height -1. Attribution to
LOW_LLMQ alone would therefore be incorrect. This run proves the selected
missing participant can be identified by a real two-contributor DKG, not that
two signatures make such judgments secure on mainnet.

### Small-quorum connection-loop defect

Extending the real DKG test past the ban exposed an independent production bug
in `CLLMQUtils::GetQuorumConnections`. With two eligible members, the second
ring step points back to the current member. The old `continue` skipped advancing
both `gap` and `k`, so it repeated forever. A one-member ring has the same issue.
The DKG thread stopped progressing, and normal shutdown could not join it.
The failing functional run timed out waiting for phase-2 contributions at
height 182; the two stalled isolated operator processes required termination.

The fix skips inserting self-connections but always advances the loop counters.
It preserves the connection choices for larger quorums and does not modify
membership, signature thresholds, commitment validation, or activation rules.
The extended functional test checks that the next quorum contains only the two
remaining valid identities and can finalize. This is separate from the still
unrepaired spork/history synchronization defect.

With the loop fix, the complete extended real-DKG test passes (exit 0): healthy
three-member quorum, two contributors identifying a selected offline member,
PoSe ban, and a subsequent two-member quorum excluding the banned identity.
All test nodes shut down normally. The rebuilt daemon/unit binary succeeded;
the targeted native suite still passes 4 cases / 46 assertions. Seven archive
extractor tests also pass. The full native suite has not been run.

## Checkpoint correction discovered during the archive audit

The source checkpoint at height 1078436 contained a misplaced hexadecimal
character. The archived header hashes to
`7168c4a4f4ac744d2047e64a1291aecf9fe1bc1cca0f0f80c0d5522d4c890b37`;
the old literal ended in `55224c890b37d` instead of `5522d4c890b37`.
The [public explorer block-hash API](https://explorer.yerbas.org/api/getblockhash?index=1078436)
and [block header](https://explorer.yerbas.org/api/getblock?hash=7168c4a4f4ac744d2047e64a1291aecf9fe1bc1cca0f0f80c0d5522d4c890b37)
independently corroborate the local record. The previous checkpoint at 1060820
matches the archive.

The literal is corrected, with a regression test deriving the expected hash
from the actual header fields. This branch uses `GetLastCheckpoint` to find a
known checkpoint in `mapBlockIndex` and reject forks older than it; it does not
reject a block solely because its height's checkpoint literal differs. Thus the
typo made this checkpoint unrecognized; it is not presented as the cause of the
LOW_LLMQ fresh-sync failures. No historical LOW_LLMQ boundary was changed.

## Explicit validation context and extended archive audit

Commitment validation now has overloads accepting an explicit parameter value.
They reject a mismatched type, oversized selected membership, malformed sizes,
insufficient signers/members, and invalid BLS signatures. The original callers
still select the current global context: this API is preparation for the
historical resolver, **not a fix for spork-dependent replay**. The caller must
supply trusted chain-derived parameters; commitment contents cannot authorize
weaker validation.

The new tests construct and verify actual BLS member/quorum signatures, reject
altered signatures and out-of-membership bits, and show that an explicit normal
snapshot continues validating a historical null commitment after live LOW_LLMQ
parameters change. The targeted suite passes 6 cases / 60 assertions; the
separate transition probe passes 8 assertions. The full real DKG/PoSe functional
test passes again, including the next two-member quorum and clean shutdown.
The refactored validator also replays through checkpoint 42069 successfully
(exit 0, `-assumevalid=0`); it reuses PoW cache entries computed by the earlier
isolated replay, without importing the user's existing node databases.

The read-only archive audit reaches the locally logged tip at height 1143209,
`f9a0d74c5f9f2431bb17c0835f8c222858e5b93688a6f80e64021b932930c6e9`.
It checks ancestry and transaction Merkle roots for 1,143,210 blocks and parses
233,607 commitments. It finds no additional type-1 size-200 commitments after
the third historical window. This does not prove that no short-lived spork
changes occurred between commitments, and it is not a full consensus replay
through that height. The summary's `consensus_validated` remains false.
The hash of the corresponding ordered framed block stream is
`80530fc46a18ac9c8a55aafb5712830673e2e0f6020c15d1686c50e6e22e1143`.

`--summary-only` performs these checks without copying the block archive.
Eight extractor tests pass, including equality with full extraction and parsing
of a size-200 commitment in summary mode. The first attempted audit correctly
refused the mistyped source checkpoint; the subsequent local-tip audit and
independent public-explorer check exposed the typo described above.

The proposed next protocol and its acceptance criteria are documented in
[low-llmq-replay-design.md](low-llmq-replay-design.md). In particular, recovery
expiry must retire low-threshold signing authority, not merely change the size
of future DKG quorums. No public activation or reduced security setting has been enabled. The following
prototype adds a regtest-only authorization record.


## Experimental authenticated recovery records

The opt-in `-llmqrecoverytest` prototype accepts transaction type 10 on regtest
only. It verifies domain-separated compact signatures from the configured
regtest authority, binds a recent ancestor and previous authorization, and
stores a future bounded window in the evolutionary database keyed by block hash.
It rejects replacing a pending/active window; expiry requires no off message.
Database updates use the caller's block transaction and undo path. Public
networks reject the flag; ordinary regtest rejects the new transaction type.

At that milestone this was authorization and storage infrastructure only.
The following integration now connects it to quorum behavior. Early termination
is not implemented. The legacy spork-only path remains unchanged.

The focused native suite passes 13 cases / 452 assertions, covering policy,
real signatures, bounded deserialization, database rollback, and opt-in guards.
The daemon test passes fresh sync during and after expiry, restart, reindex,
invalidate/reconsider, and a competing higher-work branch without the record.
A node without the flag rejects the record; an altered signature is rejected.

An initial fork run crossing regtest height 200 failed with
`bad-cb-founder-payment-not-found`. `ProcessNewBlock` initially calls `CheckBlock`
with the active tip's next height, so founder-payment checks can reject a side
branch using the wrong height. The authorization test now uses window [120,180)
and a winning branch ending at 190 to isolate recovery rollback below this
independent boundary. This does not establish fork correctness across founder
payment activation, and no payment consensus rule was changed.


## Chain-derived integration results

The user selected dynamic recovery windows recorded in the chain. With
`-llmqrecoverytest`, quorum parameters are resolved from the recovery state and
total registration count at the parent of the quorum-start block. Member
selection uses the existing quorum-block list. Sessions and quorum objects own
these resolved values. PoSe decay, signature-share sizes, commitment retention,
and signing eligibility use chain context rather than today's LOW spork.

Verified integrated replay uses signed window [120,180), while the old LOW
spork remains ON. Null commitments have 3 slots at height 100, 200 at 130 and
160, and 3 again at 190. A fresh node joins at 131, after an actual LOW
commitment exists; another joins after expiry. Restart, reindex at 191,
invalidate/reconsider, and a higher-work fork to 199 without the record all pass.
The winning branch removes the authorization on every participating node.

The real operator test produces non-null LOW commitments for quorums 120 and
150, then a normal quorum at 180. Stopping one selected operator produces an
invalid member flag and a PoSe ban at 161. Type 100 also commits and penalizes
at that height: the combined penalty reaches 100; do not attribute the ban
solely to type 1. The normal quorum excludes the banned registration.

Two operators produce a real recovered signature during recovery. At height
180, signing requests are rejected while only expired LOW quorums are available.
After the normal commitment at 191, signing resumes with the normal quorum.
A fresh fifth node then replays through 199, including all three real signed
commitments, and matches every registration state and the ban on the live node.
This small-population normal template itself has threshold 2; native tests
also check the larger-population normal thresholds (7 and 30). This is not a
large-network availability or adversarial security proof.

The focused native suite passes 14 cases / 464 assertions. Separate-process
legacy characterization tests still reproduce the same historical boundaries
and mutable-cache behavior. The original spork-only fresh-active control still
fails: live nodes reach 120, the fresh node stops at 9, and rejects the identical
height-10 block because its three-slot null commitment is checked with size 200.
This control failure is expected and retained as evidence, not counted as a pass.

Public networks still reject the experimental flag. No activation height,
mainnet window, or deployment was set. Legacy-window behavior is unchanged;
the previously verified replay through 42069 was not repeated for this opt-in
integration. Public activation/compatibility policy and wider network-scale,
adversarial, and recovery-under-reorganization signing tests remain release gates.
The independent founder-payment side-branch issue is still outside this fix.


## Isolated recovery developer network

The public testnet seed probe found no peers during its bounded observation.
A private bootstrap using unmodified public-testnet mining rules timed out;
that attempt is not a successful testnet validation. The operator selected a
new isolated network with a dedicated test signing authority instead.

`-devnet=llmq-recovery-v1 -llmqrecoverydevnet
-llmqrecoveryauthority=<test-public-address>` enables the new experimental
profile. The flag is rejected on mainnet, public testnet, and regtest, and
requires a nonempty devnet name and authority. Wire magic derives from the name
and authority. Every recovery record must anchor at height 1 or later, binding
it to the named devnet history rather than the shared base genesis. Recovery
windows are bounded to 90 blocks, with a 60-block maximum start delay and anchor
age. The profile starts with chain-derived recovery rules active.

This developer network has easy, non-retargeting on-demand mining, localhost
operator addresses, no seeds, and a 4,000-coin smartnode collateral requirement.
The harness disables DNS seeding, supplies only its local peers, and binds to
localhost. Smartnode outbound connections remain enabled for DKG. The bootstrap block uses a DIP3 coinbase, claims no subsidy, and is
mined against the actual proof-of-work hash. These bootstrap changes apply only
to the new recovery profile. Public-network rules remain unchanged.

The functional harness generates a fresh test authority for each run and keeps
its private key in node0's mode-0600 local config. Only the public identity and
test evidence are exported. It mines spendable test coins, registers three
operators, authorizes [750,840), and exercises real DKG/signing, an offline
operator, expiry, fresh sync, restart, and reindex. It stops its nodes on exit.
Run it from the repository with a new absolute temporary directory:

```sh
python3 test/functional/llmq-lowparams-pose.py --recovery-devnet --portseed=930 --tmpdir=/absolute/new/test-directory --nocleanup
```

This is accelerated private-network testing, not public-testnet interoperability
or production readiness. It does not activate or broadcast anything on mainnet.


### Verified isolated-network results

`recovery-devnet-v7.log` passed with exit code 0. Real LOW quorums at heights
750, 780, and 810 used the size-200/threshold-two template. The offline third
operator accumulated penalties 66 then 100 and was banned at height 821.
At height 840, expired LOW keys could no longer sign before replacement;
the normal small-population quorum committed at 851, excluded the banned
operator, and produced a recovered signature. A fresh fifth node replayed to
859 and matched all smartnode states and quorum types. Restart and full
reindex preserved the recovery state and PoSe states. All test nodes stopped.

The existing chain-recovery regtest operator test also passed
(`recovery-regtest-control-v3.log`). The native recovery, chainparams, and PoSe
suites passed all 15 cases / 482 assertions (`native-recovery-devnet-final.log`).
The exported devnet JSON files contain public identity, commitment/PoSe results,
and signing/replay evidence. Configs, private keys, and wallets are not exported.
Earlier setup runs exposed and corrected the bootstrap coinbase/subsidy,
localhost-registration restrictions, duplicate bind arguments, and the harness's
`-connect=0` DKG-connection suppression. They are not counted as passing tests.

The operator run did not exercise a devnet reorganization; the follow-up
replay test below adds that coverage. Larger operator populations, independent hosts,
public-testnet interoperability, and production activation are still unverified.


### Isolated devnet reorganization follow-up

The isolated-devnet replay test (`recovery-devnet-reorg-v1.log`) passed. It
accepted a signed [120,180) window, rejected a modified signature and an
oversized window, replayed active/expired history on fresh nodes, rebuilt state
with reindex, and removed/restored authorization by invalidate/reconsider.
A partitioned node then supplied a higher-work branch ending at height 199
without the authorization. All five nodes adopted it with no active recovery
window; a restarted node retained that result. Type-1 null commitments at
heights 130, 160, and 190 had normal size 3 on the winning fork; the abandoned
branch had size 200 at 130 and 160. This demonstrates branch-derived rules even
while the legacy LOW_LLMQ spork remains ON.

The replay harness now supports `--recovery-devnet`, sharing local authority
setup with the operator harness. Network traffic on the partitioned node is
explicitly disabled until its competing branch is ready. This scenario checks
null-commitment consensus and authorization rollback, not rollback of real
operator penalties. It stays below the separate founder-payment boundary bug
at height 200; crossing that boundary remains unverified.

```sh
python3 test/functional/llmq-recovery-record.py --recovery-devnet --portseed=1020 --tmpdir=/absolute/new/reorg-test-directory --nocleanup
```

The same updated replay harness passed its regtest control
(`recovery-record-regtest-v3.log`). Both runs exited successfully and stopped
their nodes. This follow-up changes test coverage and shared test setup only;
it makes no additional production consensus changes.
