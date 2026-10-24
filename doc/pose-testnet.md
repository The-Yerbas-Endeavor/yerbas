# Fresh testnet campaign for LLMQ_100_67 and rotating RC

Testnet uses the existing Yerbas testnet genesis, P2P port 21421 and 4,000 YERB
collateral. Do not connect mainnet wallets or import mainnet keys. Start with new
isolated testnet datadirs; this release is incompatible with old testnet history
that passed activation heights without these rules. Nothing resets mainnet.

## Fixed schedule and required fleet

- LLMQ_100_67 and participation indexing: block **4,320**.
- RC authority: block **8,640**, after 4,320 blocks of warm-up.
- At the 60-second testnet target these are roughly day 3 and day 6 from genesis;
  actual mining pace determines timing. These are heights, not timed deadlines.
- The quorum remains 100 selected / 80 minimum valid / 67 signing shares.
- RC remains 15 eligible selected registrations / 11 approvals. No testnet
  threshold reduction or appointed keys are introduced.
- Plan for at least 100 registered smartnodes to exercise full selection;
  80 valid nodes is the formation minimum, not a full 100-node selection test.
  Each requires 4,000 test YERB collateral: 400,000 for 100 registrations.
- Register well before activation, leaving 720 blocks of registration age.
  Mine enough funding first and account for coinbase maturity. Confirm reward
  and collateral balances from RPC rather than assuming funding is immediate.

## Local bootstrap

Build the headless daemon and CLI with the repository's platform build guide.
The bootstrap uses two full nodes, local P2P and cookie-authenticated local RPC.
It disables discovery and outside peers, allocates free ports, writes no private
keys to its manifest and refuses to overwrite existing directories.

    python3 contrib/pose/testnet_cluster.py smoke --bin-dir src --root /tmp/yerbas-testnet-smoke
    python3 contrib/pose/testnet_cluster.py start --bin-dir src --root /tmp/yerbas-testnet-campaign
    python3 contrib/pose/testnet_cluster.py status --bin-dir src --root /tmp/yerbas-testnet-campaign
    python3 contrib/pose/testnet_cluster.py stop --bin-dir src --root /tmp/yerbas-testnet-campaign

Use a new empty root for each start/smoke run. The start command mines one testnet bootstrap block before connecting the follower
so the seed can leave initial block download, then leaves both daemons running; stop shuts them down without deleting wallets or chain data. Smoke
starts both, verifies fixed parameters, mines a bootstrap block and propagates the next block, and stops.
This checks testnet startup and networking; it does not create smartnodes or DKG.
For a retained stopped datadir, restart the daemon directly with its datadir.

## Distributed setup

Choose seed/miner hosts and smartnode hosts, and install the same published commit
on every node. Allocate unique datadirs and RPC credentials; expose only the P2P
port to peers. The localhost script is not an internet-facing server installer.
Use explicit addnode/connect peers for the campaign; do not rely on old seed lists.
Ordinary testnet configuration starts with:

    testnet=1
    server=1
    listen=1
    port=21421
    dnsseed=0
    discover=0
    # addnode=<campaign-seed-address>:21421
    # smartnodeblsprivkey=<this registered node's operator secret>

Generate operator keys locally using `bls generate`, and use `help protx register`
on this exact build to register collateral, owner/voting identities, operator
public keys, routable services and payout addresses. Never publish operator secrets,
wallet backups or RPC cookies. Fund collateral with testnet mining only. Confirm
`protx list valid true`, `smartnode status`, peer connectivity and synchronization
before beginning DKG. Consult `help quorum dkgstatus` and `help quorum list` for
this build's quorum diagnostics. No separate RC registration or RC secret exists.

## Campaign acceptance steps

1. Before height 4,320, verify `pose status` is inactive with activationHeight 4320,
   and `recovery status` reports activationHeight 8640, size 15 and threshold 11.
2. Establish at least 80 valid participating nodes; preferably use 100 or more.
   Confirm real non-null type-4 commitments across multiple distinct sessions.
   Keep registrations/services stable and build enough recent participation for RC.
3. At/after 8,640, inspect RC qualified count, snapshot, selected registration
   identities and operator keys. Fewer than 15 qualifying candidates must produce
   no authority. Being selected does not itself authorize a penalty.
4. In the isolated campaign, take enough quorum participants offline to fail
   three completed 100_67 formation sessions while preserving 11 selected RC
   members. Record actual quorum selections; arbitrary shutdowns may remove too
   many RC signers. Verify recovery activates only after the third failure closes.
5. Observe one unresponsive target over at least 20 blocks after the trigger.
   Independently verify it from selected signers, use the request/sign/merge/maketx
   workflow in pose-recovery.md, fund/sign/broadcast the fee-paying transaction.
   Ten signatures must fail; eleven valid selected signatures may succeed.
6. Verify mined penalty, duplicate rejection, one-target-per-epoch allowance,
   budget limits, changed-member/target rejection, restart and rollback behavior.
7. Restore quorum participation. Two consecutive successful sessions must end
   recovery; an expired epoch must not renew from repeated failures or rotation.
8. Test partitions and asymmetric reachability before treating monitoring as ready.
   A failed connection alone does not prove target misconduct.

Collect logs, heights, hashes, RPC status and observed outcomes, excluding secrets.
The existing C++ fixture/replay tests use constructed commitments; this campaign
must supply real distributed DKG and active-smartnode RPC signing coverage.
Automated RC reachability scanning is not implemented. RC signing is explicit.

## Local active-identity RPC test

The serial regtest harness exercises `request`, `sign`, `merge`, `maketx`, wallet
funding/signing, submission and mining. It restarts one isolated daemon under
generated registered operator identities. It does not simulate independent
operators, distributed DKG or external reachability. Generate both fixture files
in the same run of the native test, using absolute paths:

    umask 077
    YERBAS_RC_FIXTURE=/tmp/yerbas-rc-blocks.txt YERBAS_RC_RPC_KEYS=/tmp/yerbas-rc-keys.json src/test/test_yerbas --run_test=recovery_consensus_lifecycle
    python3 contrib/pose/recovery_rpc_test.py --bin-dir src --fixture /tmp/yerbas-rc-blocks.txt --keys /tmp/yerbas-rc-keys.json --workdir /tmp/yerbas-rc-rpc

The keys file contains generated regtest operator and funding secrets. Keep it
local, never commit or publish it, and never use these keys on public networks.
The daemon binds only localhost, disables discovery and outgoing connections,
and stops on completion or a test failure. Each run creates a fresh node datadir.
This supplements the consensus replay test in `recovery_daemon_test.py`.

The simultaneous local campaign uses the same freshly generated loopback fixture:

    python3 contrib/pose/recovery_network_test.py --bin-dir src --fixture /tmp/yerbas-rc-blocks.txt --keys /tmp/yerbas-rc-keys.json --workdir /tmp/yerbas-rc-network

Use a new output directory. This starts 15 selected smartnodes and one wallet
coordinator, with small database caches and localhost service ports from the
fixture (25000–25079). Those selected service ports must be available. It checks
P2P synchronization, five stopped signer processes (ten approvals), restart of
one signer (eleven approvals), validity and expiry of previously collected
signatures during an outage, an 8/7 split, refusal by lagging and competing-branch signers,
11 approvals after partial reconnection, a propagated penalty, and convergence
after full reconnection. The coordinator disables the RPC safe-mode gate for
the deliberate expiry-test rewind. Every daemon is stopped on exit. The starting history
still contains constructed quorum commitments; this does not test distributed
DKG, independent operators, external reachability, or automatic failure detection.

Mainnet keeps its separate schedule: 1,212,840 warm-up and 1,214,280 RC authority,
projected January 23 and January 25, 2027. Testnet setup does not activate mainnet.


## Fresh 100-smartnode DKG campaign

Run the actual distributed key-generation test locally with:

    python3 contrib/pose/dkg_network_test.py --bin-dir src --workdir /tmp/yerbas-dkg-100

Use a new directory and a machine with capacity for 101 daemon processes. The
harness creates 100 registrations through wallet RPC from a fresh regtest chain,
uses separately confirmed funding outputs, and batches registration outside the
legacy quorum mining window. It keeps the production type-4 size/minimum/signing
thresholds of 100/80/67. Regtest collateral and difficulty overrides remain local.
No constructed quorum commitments or imported participation history are used.

The coordinator enables the existing regtest DKG spork with the public regtest
key from the functional framework. All registered services bind localhost. DNS
seeding and discovery are disabled. Unlike the RC replay harness, this campaign
must omit `connect=0`: Yerbas disables automatic smartnode quorum connections
when that option is present. The campaign keeps allocated local ports distinct.

It waits for real contributions and premature commitments before advancing
successful sessions. Four successful sessions establish participation history.
The campaign then isolates 21 non-RC smartnodes, retaining all 15 selected RC
members. It checks that three failed sessions activate recovery, collects 11
actual RPC approvals, mines a penalty, reconnects the fleet, and checks that two
successful sessions restore normal mode. No synthetic commitments are used.

All daemons stop on exit. Generated wallets and test identities must remain
private and must not be reused on public networks. Results are written to
`dkg-results.json`, session status to `rc-session-history.json`, and successful
quorum details to `quorum-<height>.json` in the campaign directory.

These tests run on one host and do not establish independent operators or
external reachability judgments. The campaign's disconnections are intentional
test inputs, not proof that an arbitrary unreachable public node misbehaved.

## Interrupted recovery DKG campaign

Add `--interrupt-recovery` to the fresh DKG command to insert a failed session
between recovery successes. After the penalty, session 1620 succeeds, 21 non-RC
nodes disconnect for session 1680, and all nodes reconnect for sessions 1740 and
1800. The failed session must reset the success count to zero while retaining
recovery authority and the consumed penalty. One fresh success must leave
recovery active; only the next consecutive success restores normal mode.

To reuse a completed, stopped local real-DKG campaign without repeating its
eligibility and penalty setup:

    python3 contrib/pose/dkg_network_test.py --bin-dir src --workdir /tmp/yerbas-dkg-interrupted --bootstrap-from /tmp/yerbas-dkg-100 --resume-after-penalty --interrupt-recovery

The source must contain its private `resume-identities.json` and coordinator
chain/wallet. The harness copies that state into a new private directory and
rewinds the copy to height 1619, verifying active recovery with one consumed
penalty. The source is unchanged. The resumed regtest copy disables the RPC safe-mode
gate because it retains a known longer discarded branch; synchronization and
consensus checks still run. This mode inherits previously recorded real
DKG history; it does not claim to recreate that history in the resumed run.
Never use public-network datadirs or publish generated test keys.

## First-registration mining-window regression

The initial regtest legacy type-1 quorum now uses the same three-member sizing
as the adaptive zero-smartnode configuration. Previously it began at 50 members:
constructing a candidate containing the first registration could resize it to
three while checking a 50-bit null commitment, producing `bad-qc-invalid-null`.
Public-network initialization and commitment validation are unchanged.

    python3 contrib/pose/registration_window_test.py --bin-dir src --workdir /tmp/yerbas-registration-window

This reproduces the first registration at height 401 inside the legacy mining
window, verifies it mines, disconnects/reconnects it, and restarts the daemon.
Use a fresh directory with the rebuilt binary. Existing regtest histories made
with the earlier initial quorum sizing should be regenerated for these tests.

## October 23, 2026 fault-campaign results

The refreshed native lifecycle fixture passed. The 16-daemon RC network campaign
passed all eight scenarios, including five stopped processes, ten-signature
rejection, restart to eleven signatures, and certificate expiry during an outage.
The existing partition, competing-branch, propagated-penalty and convergence
checks also passed.

The resumed 101-daemon real-DKG campaign recorded session 1620 successful with
recovery success count one; session 1680 failed and reset it to zero; session 1740
succeeded but retained recovery; and session 1800 succeeded and restored normal
mode on every daemon. It reused the prior real-DKG history and mined penalty,
then performed these four sessions anew. All campaign daemons stopped on exit.
These tests use localhost, not independent hosts or asymmetric Internet paths.

## Recovery boundary reorganizations

Run the daemon replay with the matching native fixture:

    python3 contrib/pose/recovery_daemon_test.py --bin-dir src --fixture /tmp/yerbas-rc-blocks.txt --workdir /tmp/yerbas-rc-boundaries

The harness checks activation (600), initial recovery triggering (738), qualified
committee selection (1440), qualified recovery triggering (1518), scheduled
rotation during recovery (1800), and the timeout transition (1877). At each
boundary it disconnects the original block, compares the complete RC status with
the previous state, restarts, mines a competing block, and restores the original
branch. Trigger-block replacements must produce different recovery epochs.
Restoring the original block must restore its complete original RC status.

A deeper rollback crosses both the scheduled rotation and timeout, then reconnects
to the saved locked tip and checks that roster reconstruction and enforcement
state agree. Existing penalty rollback, persistence, full reindex, and public
configuration rejection checks remain part of the campaign. Fixture commitments
are constructed; these tests exercise daemon consensus and database undo/rebuild,
not distributed DKG or peer-driven fork selection. Forks are deliberately selected
using invalidateblock/reconsiderblock RPCs in an isolated regtest daemon.

Validation on October 23, 2026: all 19 daemon scenarios passed, including the
seven new boundary/deep-rollback checks. The campaign daemon stopped on exit.

## Multi-host handoff and evidence

See `rc-release-handoff.md` for independent review scope, host information,
read-only evidence collection, and the multi-host acceptance matrix.

For a bounded, accelerated five-host regtest campaign using blocks generated on
demand, see `rc-accelerated-campaign.md`. It does not change public-network rules.
