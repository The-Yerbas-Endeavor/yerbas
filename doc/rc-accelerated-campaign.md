# Accelerated five-host RC campaign

This campaign uses an isolated regtest chain across five real servers. It keeps
100 selected / 80 valid / 67 signing shares and 11-of-15 recovery approval. Blocks
are generated on demand; the controller waits for actual DKG messages and final
commitments before advancing. Mainnet and ordinary testnet parameters do not change.

## Capacity and runtime

Use the coordinator followed by four smartnode hosts, with 25 registrations per
smartnode host. The controller checks the agreed capacity profile before staging
or mining: coordinator at least two CPUs, approximately 4 GB RAM and 10 GiB free;
smartnode hosts at least four CPUs, approximately 16 GB RAM and 40 GiB free. The
RAM checks allow for the difference between advertised capacity and Linux totals.
The prior 1-GB machines can run the connectivity smoke, not the 100-node profile.

The default campaign deadline is 12 hours and cannot exceed 12 hours. Each remote
daemon gets a systemd RuntimeMaxSec equal to the remaining campaign time, plus at
most 30 seconds to stop. The controller also refuses further RPCs near the deadline
and stops services in cleanup. A disconnected controller does not remove the
remote systemd deadline. These limits stop test workloads, not VPS billing. Delete
the disposable cloud instances after collecting results; instance destruction
is not performed by these scripts.

Allow approximately one hour for automated setup as a target, followed by several
hours for DKG/fault testing. This is not a guarantee. Do not automatically extend
a failed campaign into another day. Collect the failure evidence and stop.

## Runtime and access

Use SSH aliases with noninteractive agent authentication and verified host keys.
Hosts require systemd, UFW and Python 3, plus sufficient privileges to create the
isolated campaign directory, transient services and temporary firewall rules.
The supplied runtime tarball contains `bin/yerbasd`, `bin/yerbas-cli` and `lib/`
with compatible runtime dependencies. Build binaries from the reviewed source
and record their hashes/provenance; do not download an unverified binary package.

RPC stays on loopback and is accessed through SSH. P2P uses ports 22000–22024,
restricted by UFW and systemd network filters to the five supplied host IPs.
The smoke uses port 22421. Each run has a separate private `/opt/yerbas-*`
directory. Generated operator keys and wallet data must remain private. Do not
publish these directories, configuration archives, or resume identity files.

## Five-host connectivity smoke

```sh
python3 contrib/pose/remote_regtest_smoke.py \
  --hosts testc test1 test2 test3 test4 \
  --runtime /path/to/runtime.tar.gz --output /path/to/new-smoke-results.json
```

This starts one unregistered full node per host, generates 21 blocks, verifies
matching tips and stops all services. Its default service deadline is 15 minutes.
It does not test DKG, RC eligibility or smartnode capacity.

## Full real-DKG campaign

```sh
python3 contrib/pose/dkg_network_test.py --bin-dir src \
  --workdir /path/to/new-private-campaign \
  --remote-hosts testc test1 test2 test3 test4 \
  --runtime /path/to/runtime.tar.gz --max-seconds 43200 --interrupt-recovery
```

A local isolated bootstrap daemon creates 100 real RPC registrations with the
remote service addresses and mines age/funding blocks. Its stopped chain is
copied to remote daemons before the first DKG session; the coordinator wallet
moves only to testc, while smartnodes receive no copy of that wallet. No quorum
commitments are constructed. All subsequent DKG, failure, penalty and restoration
sessions run on the remote hosts. SSH control connections are multiplexed.

The campaign establishes eligibility through four successful real sessions,
isolates 21 non-RC members for three formation failures, collects eleven actual
approvals and mines a penalty, then exercises success/failure/success/success
recovery. The final two consecutive successes must restore normal mode everywhere.

Other existing quorum types can penalize and ban isolated identities during the
campaign. Failed-session assertions therefore use the actual selected roster,
not a fixed count of 21 bad members. Before healthy recovery sessions, banned
test identities are restored through ordinary funded ProUpServ transactions.
This is explicit operator revival after reconnection, not automatic unbanning
by RC or a consensus-rule bypass. The recovery success counter is tested separately
from the individual nodes' PoSe state.

Keep `dkg-results.json`, `rc-session-history.json`, `remote-capacity.json`,
`remote-cleanup.json` and `stop-errors.json` as evidence. Inspect cleanup failures;
remote runtime limits remain the fallback. Success requires the lifecycle
assertions, not merely daemon startup or an empty results file.

## Validation status

The localhost real-DKG lifecycle and interrupted-recovery campaigns have passed
previously. The SSH backend is newly added and must pass the complete campaign on
resized hosts before it is considered validated. Do not report the five-host
connectivity smoke as a 100-smartnode result. Independent operators, asymmetric
network paths and independent consensus review remain separate acceptance work.

On October 23, 2026 the five-host smoke passed at height 21 with matching tips,
all services stopped and no firewall cleanup failures. A one-daemon probe of
the actual SSH backend passed upload/start, RPC/mining, runtime-limit and cleanup
checks. A separate five-second systemd deadline test terminated with Result=timeout.
The full controller correctly refused the original 1-vCPU/1-GB hosts before
staging the 100-node campaign. After resizing, the first full remote run formed
four 100-member quorums and recorded two intended failures. It stopped in the
third failed session because the harness expected 21 bad members although five
isolated identities had already been PoSe-banned at height 1511. All 79 online
participants agreed on 16 bad members. Cleanup stopped all daemons and removed
temporary rules, independently verified on all five hosts. The corrected harness
uses actual membership and normal service-update revival; complete remote RC
penalty/restoration validation remains pending its rerun.

The second remote run passed all four healthy sessions, the three-failure trigger,
and a penalty signed by eleven selected members. One banned test identity was
revived through a mined service update. Restoration session 1620 then timed out
waiting for authenticated ring connections, despite 100 selected/online identities.
All five hosts were independently verified stopped with temporary rules removed.
The exact missing edges were not recorded by that version, so the cause remains
unconfirmed. The harness now saves connection diagnostics and refreshes the
previously isolated nodes' connections after synchronization and revival.

A private stopped coordinator-chain snapshot and matching generated identities
can resume only restoration using `--bootstrap-from /private/snapshot
--resume-after-penalty --interrupt-recovery` together with the usual remote
options. The snapshot must contain `coordinator/regtest` and
`resume-identities.json`; every service address must match the authorized fleet.
It rewinds the isolated chain to 1619 and disables only the RPC safe-mode gate
for that known discarded branch. These are restart/restoration tests, not a
claim that the original warm-reconnection failure has been resolved. Never
publish the snapshot or identities. That resumed run used a six-hour cap.

## Restoration-only attempt (v3)

The five-host restart-restoration attempt reused real DKG history and a mined RC
penalty from the stopped v2 chain. Session 1620 succeeded and advanced recovery
to one success. The deliberate 21-node outage at session 1680 failed as expected,
reset successes to zero and preserved the consumed penalty. The campaign then
timed out waiting for zero connections during post-sync network refresh. Sessions
1740 and 1800 were not reached; this is partial evidence, not lifecycle success.
All five hosts were independently checked: zero yerbasd processes and no campaign
firewall rules. The recurring monitor was paused; no full campaign was auto-retried.

Source inspection found that OpenNetworkConnection tests network-active before
ConnectNode and inserts the new peer later, while SetNetworkActive closes only
its current peer snapshot. This is a possible explanation for lingering peers,
not a confirmed diagnosis of either observed timeout. The harness now explicitly
disconnects remaining peers while network-active is false and records peer IDs
if draining fails. This workaround does not change Core or prove the original
warm-reconnect authentication problem resolved. A local three-daemon drain smoke
test and a subsequent real-DKG warm restoration test are separate validation gates.
The local smoke test passed ten reconnect/disable cycles and stopped all three
child daemons. It did not run DKG or reproduce the original authentication timeout.

## Successful restoration retry (v4)

The same five hosts completed the real-DKG restart-restoration run with explicit
peer draining. Session 1620 advanced recovery to one success; the deliberate
failure at 1680 reset successes to zero and retained the mined penalty; 1740
advanced to one success; 1800 restored normal mode on all 101 daemons. One node
temporarily had only 99 contributions in the final session; the last arrived
without intervention and all 100 premature commitments were received. Controller
exit was zero. Independent SSH checks found zero daemons and no campaign firewall
rules on every host; controller cleanup also reported no errors.

This proves restart-restoration with the harness workaround, not an uninterrupted
fresh lifecycle or a production networking fix. The original authentication
timeout has not been independently root-caused. A fresh full campaign on the
updated, separately staged build is the next validation gate. AI work is paused.

## Fresh full-lifecycle campaign (v5): passed

The updated build completed the full sequence on a fresh regtest chain across
the five hosts, without a restored starting snapshot. Four successful real DKG
sessions established participation history. Three consecutive failed sessions
activated the selected 11-of-15 RC, which authorized a mined penalty. A later
failure reset restoration progress while preserving that penalty. Two subsequent
successful sessions restored normal mode on all 101 daemons. Controller exit was
zero, with no stop errors. Independent SSH checks confirmed zero yerbasd processes
and no campaign firewall rules on all five hosts. The monitor was paused after
completion; VPS instances were preserved.

This closes the fresh updated-build lifecycle gate using the explicit peer-drain
and refresh harness. It does not establish a production networking fix or the
root cause of the earlier authentication timeout. Accelerated regtest conditions
and 100 identities on five machines do not substitute for production deployment
validation or independent code review. AI work remains paused.

## Follow-up networking fix (local, not deployed)

Source review confirmed that both accept and outbound connect paths could insert
a peer after SetNetworkActive(false) had swept the existing list. Both now use a
shared final admission check under cs_vNodes; a peer arriving while networking is
disabled is immediately marked disconnected and closed, then follows normal
socket-handler finalization. This does not change consensus or RC schedules.

The rebuilt daemon and test binary passed 16 networking/PoSe unit cases, including
a deterministic late-admission regression for inbound and outbound peers. Three
local daemons also passed ten reconnect/disable cycles using setnetworkactive
alone, without the harness's explicit disconnectnode workaround; all stopped.
This patch was not part of v5 and still needs a distributed DKG regression.
The local checks do not close that gate. It does not independently resolve or explain the earlier
MNAUTH timeout. Independent reviewer approval remains outstanding.

The patched build subsequently passed the native recovery_consensus_lifecycle
fixture and all 19 local daemon assertions covering activation/trigger/selection
rollback, competing branches, restart persistence, penalty rollback, full reindex,
frozen recovery authority, rotation/timeout reorgs and rejection of public-network
activation overrides and obsolete appointed-key options. All local test daemons
stopped. These tests use cryptographically valid constructed commitments, not real
distributed DKG, and did not use or restart any paid test server. This source review
and validation are implementation self-review, not independent reviewer approval.
