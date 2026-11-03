# Yerbas-AI marketplace roadmap

Target: a wallet-controlled marketplace for approved AI jobs, recoverable
execution, explicit verification, and transparent YERB rewards. The first
deployment is a supervised private reduced-collateral testnet. This document
does not activate a new reward policy or a consensus rule.

## Current baseline

The wallet starts preassigned public-text training jobs through a local owner
agent. Providers use verified HTTPS, protected runtime policies, GPU locks,
deadlines and durable journals. The coordinator is a trusted scheduling and
accounting authority. Separate providers have reproduced completed training
results and submitted signed attestations. Private-testnet reward requests,
payments and confirmation observations have been exercised.

The fixed demonstration recipe is byte-context-mlp-v1. It is a small text model,
not a general chatbot. Historical runtimes remain available for job recovery.
The installed GPU path is Linux-specific; wallet platform support does not
imply GPU-worker support on those platforms.

Observed kernel intervals are diagnostic evidence. Capture completeness,
calibration of payable GPU time, and resistance to dishonest timing reports
remain unverified. Reproducing the public deterministic checkpoint does not
prove that a provider performed fresh work. Test allowances do not establish
market prices or permissionless consensus.

## 1. Explicit job offers and reward terms

First expose the existing pilot's terms before starting work: approved recipe,
separate verification, simulated accounting, absence of a promised YERB amount,
and owner stop/recovery behavior. This requires no change to existing tickets.

Next introduce versioned coordinator-issued offers with:

- Offer ID, expiry, network/genesis and coordinator identity.
- Recipe, dataset, initial checkpoint and runtime identities; data license and
  permitted use; supported hardware and bounded resource requirements.
- Work range, execution deadline, result format and verification policy/version.
- Exact reward basis, amount or bounded calculation, denomination, payer,
  fees, funding status and cancellation/dispute terms.
- Provider acceptance binding the exact offer digest and enrolled identity.

Implement the authority and durable acceptance in YERB-Coordinator; implement
validation and presentation in the wallet/provider repository. A local JSON
file is a preview, not payment authority. Authentication must bind the actual
offer to the configured coordinator. Modified, expired, cross-network and
replayed offers must fail without reserving twice or starting work twice.
Never reinterpret an old ticket as a new offer or rewrite existing jobs.

Acceptance gate: the wallet shows the same immutable terms enforced by the
coordinator and provider. Completion, verification, reward approval, broadcast,
and confirmation remain separate states. A changed offer requires new acceptance.

## 2. Defensible testnet rewards

The current rate is 1 testnet YERB per operator-approved GPU-hour. Approval of
the rate does not make observed runtime payable. Preserve explicit allowances
and show their basis; do not silently convert diagnostic time into earned YERB.

Before automatic rewards, choose and document a measurable service unit and
verification cost. Consider a fixed price for an accepted work unit alongside
time-based pricing. A slower GPU must not earn more merely by running longer.
Any policy change must be explicit, versioned, bounded and shown before consent.

Reserve a job's budget once, specify who bears fees, persist payment intent,
and reconcile chain state before retrying an uncertain broadcast. Release
unearned reservations on cancellation/expiry; never refund a settled result.
Do not describe an operator database reservation as on-chain escrow.

Acceptance gate: crash, duplicate request, cancellation, failed verification,
insufficient funding and reorg scenarios preserve accounting and truthful wallet
status. Evaluate net useful compute after verification cost, not gross GPU time.

## 3. Stronger work verification

Keep exact reproduction for the fixed pilot recipe. Before accepting untrusted
providers, add assignment-specific work and tests against cached-result replay,
copied evidence, substituted artifacts, collusion and verifier self-dealing.
Nonces alone do not prove useful computation. Bind receipts and attestations to
the assignment, complete artifact and verification policy.

For additional recipes, define output-quality tests, tolerance for numerical
differences and data leakage controls before enrollment. Evaluate independent
holdout checks and selectively reproduced work against explicit attacks; do
not call probabilistic checks a proof. Verification assignments need independent
selection, an appeal path and measured false-accept/false-reject rates.

Acceptance gate: publish threat model, adversarial results, verification expense
and residual trust. A signed statement proves its signer, not its truth.

## 4. Easier provider installation

Provide a read-only readiness command for OS, driver, VRAM, runtime, disk,
connectivity and existing installation detection. Explain downloads and resource
limits before installation. Offer an idempotent installer with least-privilege
services, pinned dependencies and a validated rollback path.

Enroll a provider with only its own credential and the public CA. Leave wallet
keys local. Refuse to overwrite existing journals or credentials. Keep local AI
on loopback. Provide owner-visible pause, stop, resource limits and uninstall
instructions that preserve earned receipts and recovery data.

Acceptance gate: a genuinely fresh supported host can join, complete one
approved job, recover a restart, request its reward and leave safely. Upgrading
our two existing hosts does not satisfy fresh-host acceptance.

## 5. Reduce coordinator trust in stages

First publish portable job/receipt/attestation formats and reproducible audit
tools. Then test independent coordinators with distinct authority and explicit
provider selection. Do not migrate live databases by synchronizing them.

Design verifier independence, Sybil/collusion resistance, dispute resolution,
budget custody, coordinator failure handling and settlement finality before
claiming permissionless operation. Blockchain payments alone do not decentralize
job scheduling or validate AI results. Any future quorum or consensus change
requires its own protocol review and testnet deployment.

## Release gates and order

1. Truthful wallet terms for the current approved recipe.
2. Authenticated, immutable offers and durable acceptance across wallet,
   provider and coordinator; no automatic reward policy change.
3. Fresh-host installation and one complete offer-to-reward acceptance run.
4. Adversarial verification and reward-policy evaluation with explicit metrics.
5. Independent coordinator/verifier trials after those contracts stabilize.

Run tests that resolve a named risk. Do not repeat successful GPU benchmarks
unless code, hardware, measurement method or an unresolved hypothesis changes.
Keep private-testnet readiness separate from public-network or mainnet readiness.
