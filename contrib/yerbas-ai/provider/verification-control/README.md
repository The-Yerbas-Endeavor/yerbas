Scoped verifier maintenance
==========================

The reward relay shares the provider account but does not run GPU work.
`paused()` temporarily stops its socket and service, then restores their prior
active states even when verification fails. Keep the existing strict provider
process checks and GPU checks inside this context. Never use it to exclude
arbitrary processes from safety checks. The caller must serialize maintenance.
This module requires a privileged supervisor; importing it performs no action.
Restoration failures are reported. SIGKILL or a host crash cannot run cleanup.
