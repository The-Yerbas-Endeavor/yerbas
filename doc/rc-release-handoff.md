# RC independent review and multi-host handoff

This is a handoff for the unmerged PR targeting `dev`, not release approval.
The local evidence covers real DKG, recovery penalties, interrupted recovery,
signer outages and RPC-driven reorganizations. It does not establish independent
operators, asymmetric Internet reachability or independent consensus review.

## Independent review scope

A reviewer should record the exact Git commit and tree reviewed, findings with
file/line references, their severity and reproduction, and unresolved questions.
Review the entire PR against `dev`, not only its latest test additions. The
existing implementation review in `rc-consensus-review.md` is author-side work.

Prioritize these paths and questions:

| Path | Review question |
| --- | --- |
| `src/llmq/quorums_recovery.cpp` | Are epoch, roster, target state, branch, expiry, signer eligibility and budget checks complete on every acceptance path? |
| `src/llmq/quorums_commitment.cpp` | Does authenticated participation credit match the actual selected signers and valid members? |
| `src/evo/deterministicmns.cpp` | Can transaction ordering, target replacement or collateral spending bypass penalty constraints? |
| `src/evo/specialtx.cpp` | Are validation, database commit, undo and reindex consistent, including failed candidate blocks? |
| `src/chainparams.cpp` | Are warm-up, authority activation and quorum parameters appropriate for each network and upgrade path? |
| `src/llmq/quorums_pose.cpp` | Can monitor evidence acquire authority without the required quorum approval? |

Review the limits of block-derived selection randomness and multiple registrations
controlled by one operator. Do not equate distinct identities with independent
operators. Verify resource bounds for participation scans and certificate checks.
Assess the old adaptive quorum sizing interaction beyond the fixed initial
regtest mismatch. A passing test campaign is not a substitute for this review.

## Host information needed

Provide SSH aliases, host roles (miner/seed, smartnode, observer), public P2P
services, operating system/architecture, and available capacity. Keep credentials
and operator keys out of the inventory. Record fault domains so a campaign across
several processes on one server is not reported as independent-host testing.
No hosts are provisioned by these instructions.

Use the fixed schedule, collateral requirements and setup in `pose-testnet.md`.
The campaign needs 100 registered smartnodes to test a full selection, plus mining
and observation capacity. Use the same reviewed source revision; compare hashes
only among identical build artifacts/platforms. Record build provenance separately.
Register well before activation and preserve the 100/80/67 and 11/15 thresholds.
Use fresh testnet datadirs and explicit P2P peers. RPC stays local to each host;
remote administration uses SSH. Do not place `connect=0` on DKG participants.

## Public evidence collection

Run on each campaign host after installing the collector and the tested binaries:

```sh
python3 contrib/pose/testnet_evidence.py --bin-dir /path/to/bin \
  --datadir /path/to/testnet-data --label node-001 --output node-001-before.json
```

The collector only invokes read-only RPCs. It verifies testnet parameters, samples
chain/RC/quorum state at a stable observed tip, and exports an explicit field
allowlist. It does not export cookies, configuration, wallet data or peer lists.
Use non-sensitive labels. Output files must be new. The daemon-file SHA-256 is a
local file hash, not an attestation of the running process or source revision.

Collect before and after each fault, retaining heights and block hashes. Compare
snapshots taken at the same height and hash; otherwise synchronize or explain the
difference before comparing RC states. A snapshot with no committee or no type-4
quorums is valid evidence of that state, not a successful readiness result.

## Multi-host acceptance matrix

1. Establish matching chain tips and real type-4 commitments across hosts; build
   mature participation and confirm the selected RC without an appointed roster.
2. Disconnect enough selected quorum members to leave fewer than 80 valid, while
   retaining sufficient RC signers. Record three completed formation failures.
3. Collect independent reachability observations from selected members before
   explicit signing. Distinguish a target outage from observer/path failures.
   Never infer misconduct from a single failed connection.
4. Exercise ten versus eleven approvals, a funded penalty, duplicate rejection,
   signer outages and expiry. Capture the resulting target state and transaction.
5. Restore, interrupt, then restore DKG again; verify the success streak resets
   and requires two consecutive fresh successes.
6. Exercise one-way connectivity and partitions across fault domains. Record who
   can reach whom and why signers approve or refuse; there is no automatic scanner.
7. Exercise peer-driven competing branches around relevant boundaries on an
   isolated campaign network, then verify convergence, restart and reindex.

Keep the PR draft until findings are resolved and reviewers assess the evidence.
Before release, re-evaluate activation-height estimates and coordinate upgrades.
No automatic merge, deployment, paid provisioning or reviewer notification is
performed by this handoff.

## Handoff status on October 23, 2026

The read-only collector was exercised against two isolated local testnet nodes.
Their chain and RC snapshots agreed and correctly showed zero registrations,
no type-4 quorums and inactive preactivation features; both daemons stopped.
No multi-host campaign has run. No host aliases were supplied for this stage.
GitHub returned no submitted reviews for PR 53. The separate Code Review
connector denied workspace access; its CI diagnostics were unavailable. The
GitHub commit-status endpoint returned no entries for the then-current head;
that does not establish the presence or absence of Actions check runs.
