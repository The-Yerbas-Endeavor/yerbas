# Wallet service integration candidates

These are public source snapshots of the enrolled u26 and anno2 test deployment,
not a fresh-host installer. Root-owned runtimes, owner identities, separate
consensus credit, fixed testnet transport and prior deployment modules are
required. Never copy private state or run a historical activation blindly.

The verifier and rental service components have passed live testing. The new
wallet orchestration adapters are integration candidates; a fresh unattended
rental acceptance result is still required. Build scripts reference the
retained deployment layout and public datasets, which are not included here.
Generated installers, credentials, wallets, databases, and model weights are
excluded. No mainnet activation is implied.

Portable interruption tests are in `../wallet-workflow`. The owner adapter tests
require the matching protected deployment and must not be included in ordinary
CI as live tests.
