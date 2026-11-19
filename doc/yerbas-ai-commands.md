# Yerbas AI commands and abilities

Yerbas-AI 5.0.0.0 combines a coin wallet, approved local AI generation, GPU
provider controls, and a private-testnet marketplace. The current deployment is
an invite-only prototype on u26 and anno2, operated by one owner. It is not a
mainnet release or a demonstration of independent-operator decentralization.

## Wallet controls

| Area | Ability | Current limit |
| --- | --- | --- |
| Send and Receive | Review recipients, amounts and fees; send native coins and view transactions | Use a separate testnet wallet for development |
| Local AI | Generate text with an explicitly selected, approved installed model | No automatic model downloads; the fixed demonstration is a small text model |
| Provide GPUs | Detect NVIDIA GPUs, select enrolled devices to offer, reserve the desktop GPU | Linux owner-agent and protected enrollment required |
| Rent GPUs | Review a quote, pay its deposit, check confirmations, schedule funded work, recover saved orders | Current automatic workflow is restricted to one enrolled GPU1 work unit |
| Verification | Reproduce the fixed 6,000-step workload on anno2 and retain a signed result | Separate host, same owner; not proof of an independent operator |
| Payment | Exact deposit/output binding, protected signing, confirmation checks and replay refusal | Operator-controlled testnet treasury; not trustless escrow |
| Recovery | Preserve original deposits, execution records, signing history and uncertain requests | An uncertain effect requires reconciliation; it is never blindly repeated |

On 18 November 2026, wallet build workflow4 completed a fresh rental from the
GUI through GPU execution, automatic verification on anno2, payout, six native
confirmations on both nodes, and capacity release. No per-order helper commands
or terminal authentication were used. The provider received 0.00100000 tYERB.
The enrolled services and consensus credit were prepared beforehand; private
chain blocks were mined as test infrastructure. This is a same-owner test.
See [the acceptance record](yerbas-ai-wallet-acceptance-2026-11-18.json).
An earlier run also tested explicit recovery without repeating its deposit,
completed training or payout.

## Normal rental workflow

1. Connect the enrolled owner agent and keep the desktop GPU reserved.
2. Offer the enrolled work GPU, then open Rent GPUs and check the price.
3. Review the exact work, provider reward, fee and deposit before paying.
4. Wait for the required six confirmations and check the original deposit.
5. Schedule funded work. Automatic run, verification and payment is an explicit
   opt-in and appears only when the matching local controller is installed.
6. Use Refresh rental progress or Saved deposits to follow the original order.

The current fixed unit costs 101,000 base units (0.00101000 testnet YERB), including
100,000 for the provider and 1,000 for payout fees. The buyer also pays the deposit
transaction fee. The prototype also requires native-backed consensus credit;
that separate accounting prerequisite is not additional provider compensation.
The workflow must check credit before accepting a GPU lease.

## Local AI CLI

The source entrypoint is `contrib/yerbas-ai/local-service/yerbas-ai-cli`.
Supply the private state directory of an already configured local service.
These commands do not create a network GPU rental or authorize a coin payment.

```sh
./yerbas-ai-cli --state-dir /path/to/local-service-state status
./yerbas-ai-cli --state-dir /path/to/local-service-state hardware
./yerbas-ai-cli --state-dir /path/to/local-service-state models
./yerbas-ai-cli --state-dir /path/to/local-service-state runtime
./yerbas-ai-cli --state-dir /path/to/local-service-state config show
./yerbas-ai-cli --state-dir /path/to/local-service-state provider status
./yerbas-ai-cli --state-dir /path/to/local-service-state schedule show
./yerbas-ai-cli --state-dir /path/to/local-service-state prompt --local --model MODEL "Your prompt"
./yerbas-ai-cli --state-dir /path/to/local-service-state chat --local --model MODEL
./yerbas-ai-cli --state-dir /path/to/local-service-state job JOB_ID
./yerbas-ai-cli --state-dir /path/to/local-service-state cancel JOB_ID
```

`config set-default-model MODEL` and `config clear-default-model` change the
saved local model preference. `provider pause` and `provider resume` change this
local service's policy. `schedule set --timezone America/Los_Angeles --days
mon,tue,wed,thu,fri --start 18:00 --end 23:00` stores an availability window;
`schedule disable` disables it. This older local-service schedule does not enroll
GPUs or supersede the marketplace's per-GPU controls.

## Deployment health commands

On u26, these read service status without starting GPU work or sending coins:

```sh
systemctl status yerbas-ai-provider-trust-lifecycle.timer
systemctl status yerbas-ai-provider-headers.timer
systemctl status yerbas-ai-trust-lifecycle.timer
nvidia-smi
```

On anno2:

```sh
systemctl status yerbas-wallet-verifier.service yerbas-wallet-rental.service
```

Trust maintenance renews still-valid trust only with verified advancing headers,
under a bounded authorization. Expired trust requires explicit recovery while
preserving original anchors and signing journals. A timer being active does not
by itself prove that its latest maintenance run succeeded.

The private reduced-collateral network requires `-testnet=1
-testnetfastcollateral=1` and its own data directory. Never reuse a mainnet wallet
or node directory. Installed versions and root-owned policy pins must be updated
together; historical activation scripts are not generic fresh-host installers.

## Development tests

From the wallet source root:

```sh
python3 -B ci/check-ai-source.py
python3 -B ci/test-ai.py
python3 -B -m unittest discover -s contrib/yerbas-ai/wallet-workflow -v
```

The workflow tests cover duplicate requests, changed deposit/assignment binding,
concurrent execution, invalid journals, and lost replies at every workflow stage.
They use test adapters and do not establish live payout success.

## Remaining release gates

- Repeat the passing wallet-driven workflow under restart, network-loss, busy-GPU,
  refund and prolonged-operation conditions; uncertain effects still require reconciliation.
- Package the u26 workflow and its dependencies into the consolidated installer;
  test clean installation, interrupted upgrade, restart and recovery.
- Test independent operators, authority handover and failure domains beyond one
  owner; verify onboarding, revocation, abuse limits and operational support.
- Review treasury custody, fee economics, replay/reorg behavior and verification
  incentives before enabling real-value payments. Deterministic reproduction of
  public work alone cannot prove that fresh paid computation occurred.
- Run sustained reliability tests and obtain security review before declaring
  mainnet readiness. A passing private-testnet demonstration is not that release.

## Installation and resilience checks — November 18, 2026

A disabled provider installation passed in a fresh, network-isolated container
using pinned offline wheels. Interrupted installation and repeat installation
both refused to overwrite retained state. This is not a physical-host enrollment
or systemd boot test. Public candidate source and reproducible harnesses are in
`contrib/yerbas-ai/deployment-candidates/fresh-provider/`.

The wallet restarted with all four saved deposit records intact. The remote
verifier restarted with all eight retained runs intact. A fresh 6,000-step GPU
verification completed after the client discarded its reply; duplicate execution
was refused and the GPU returned idle. Four real-process network/crash tests and
69 refund regressions passed. The prior incomplete-work refund was rechecked at
61 confirmations; no new refund was broadcast in these checks.

Wallet cancellation still records a refund for protected operator settlement.
Fully automatic refunds, physical clean-host boot/enrollment, and independent
operator deployment remain acceptance gates. Detailed results are in
`yerbas-ai-resilience-2026-11-18.json`.
