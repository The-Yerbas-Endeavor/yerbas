Fresh marketplace provider v2 — development staging, not an installer release

The deployed migration router requires four historical policies and state stores.
A fresh provider should not need those old installations. direct_router.py uses
only the direct-CUPTI policy, dedicated provider account and original executor.
Training requires an explicit enabled selector. Receipt-only replay requires
retained private state and remains possible while new execution is disabled.
The existing executor continues enforcing hashes, HTTPS, locks and deadlines.
Existing providers must retain their migration router for historical recovery.

build_runtime.py verifies the existing approved source manifests and stages 45
public code/data files, including a self-contained bootstrap/runtime manifest.
No installed state, credentials, wallet files or private keys are read or copied.
It refuses an existing destination. No service, GPU or payment is started.

Validation: python3 -B -m unittest discover -s this-directory -v
The entry-point tests mock the privileged boundary and exec; they are CPU tests,
not physical-host acceptance. Root-controlled bootstrap and executor remain
required at installation. The staged files are not deployed.

The compose.py read-only planner now combines the 15 explicitly selected public
broker/owner/relay modules with the direct runtime, corpus and source license.
CONTROL-SOURCES.json records each source path and hash. No recursive copy of
installed directories is performed. Broker preflight is adapted to the direct
policy. Both broker submission flags and the direct selector start disabled.
Service files contain no automatic enablement; relay startup requires both role
enrollments and the public CA. This candidate remains bound to the existing
private coordinator CA/origin and is not a general public network installer.

Sixteen CPU tests passed, including isolated staging using the existing guarded
exclusive writer, refusal to overwrite files, and imports from the staged broker,
owner and relay trees. Rehearsal files retain the test user's ownership: this is
not root installation, service activation or physical GPU acceptance.

Journaled application primitives are now in install_phases.py. They partition
root and owner targets, hash each phase, check every destination before writing,
use the existing exclusive dirfd writer, and finalize exact ownership metadata.
There is deliberately no live-install CLI. The host-level wrapper still needs
account/runtime/enrollment preflight before these primitives can be deployed.

Twenty-two CPU tests passed, including altered plans, occupied destinations,
modified retained files and interruption between write and completion recording.
No automatic retry or deletion is performed after an incomplete attempt.
rehearse_install.py creates only a new private directory beneath this package.
The retained rehearsal installation-rehearsal-z5_3fwp2/ACCEPTANCE.json reconciled
87 root-phase entries and 14 owner-phase entries, with ownership mapped to the
current user. It does not establish privileged ownership or systemd acceptance.

Remaining before a fresh-provider release:
* Privileged acceptance of the disabled installer on a genuinely fresh host.
* Separate enrollment for the provider credential, public CA and GPU identity.
* Run isolated install/rollback and actual fresh-GPU-host acceptance.
* Maintain fixed-unit billing; this work does not calibrate GPU reward timing.

host_preflight.py now binds the composed phases to explicit owner/provider
accounts, separate groups, a non-login provider shell, trusted directory handles,
an empty service inventory, CPython 3.14/x86_64 Linux, required host tools,
20 GiB free staging space and the pinned offline wheel cache. It is read-only.
Existing owner .local/share anchors must be provisioned and owner-controlled.
The current u26 host was correctly refused at /opt/yerbas-ai, before any service
query or wheel scan. Separately, all 29 cached wheels passed their pinned hashes.
Twenty-nine CPU tests passed. A successful fresh-host preflight is still untested
on a real clean machine; preflight does not establish GPU/runtime acceptance.

fresh_install.py is the disabled installer candidate. Without --install-disabled
it only runs preflight. The explicit install mode requires root, repeats the
whole-host preflight, checks the phase hashes, creates exclusive installation
state, and runs root staging, offline runtime preparation, exact-owner staging
and systemd-analyze verify in order. It never enables or starts services.
Any failed phase prevents later phases. Partial state and journals are retained;
an existing installation attempt cannot be automatically retried or overwritten.
The owner helper is copied with its dependencies into root-owned public storage
before execution under the exact owner UID/GID with supplemental groups cleared.
Root journals are private; public helper code contains no enrollment secrets.

Thirty-two tests passed. Orchestration failure tests use injected phase adapters;
they are not evidence of a full privileged install. The entry point was exercised
read-only on u26-2T and correctly refused its existing /opt/yerbas-ai deployment.
Do not run installation mode on either working provider. Fresh-host acceptance
still needs a clean target, separate accounts and the verified wheel cache.
