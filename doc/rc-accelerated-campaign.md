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
staging the 100-node campaign. Full distributed DKG remains pending resizing.
