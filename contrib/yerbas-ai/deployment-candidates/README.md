# Wallet service integration and clean-install candidates

The wallet rental adapters are source snapshots of the enrolled u26/anno2
same-owner test deployment. A fresh wallet-driven rental, verification and
payout passed; see `doc/yerbas-ai-wallet-acceptance-2026-11-18.json`.
They still depend on protected runtimes, owner enrollment, separate consensus
credit and testnet transport. Do not run historical activations on a new host.

`fresh-provider/` is the self-contained public disabled-install candidate.
It passed installation into a disposable Ubuntu filesystem using pinned offline
wheels, dedicated owner/provider accounts, actual service-definition validation,
and a CPU runtime check. An interrupted installation preserved its journal and
refused automatic retry. No live state was copied. This does not establish
physical GPU enrollment or boot-time service acceptance on a clean machine.

The explicit `--offline-services` option only stages disabled images. It refuses
a running systemd manager and never substitutes for live service inventory.
The normal installer continues to require that inventory. See the candidate's
README and `acceptance/` harnesses. Wheels and private state are not included.

Portable process/network interruption tests are in `../wallet-workflow`.
Owner adapter tests require the matching protected deployment. Automatic wallet
refund settlement remains incomplete: cancellation records a plan, while payment
still needs protected operator settlement. No mainnet readiness is implied.
