# Yerbas AI wallet and provider source — 5.0.0.0

This repository owns YERB wallet integration, local inference, provider workers,
and owner-agent code. The coordinator and verifier authority remain in
[The-Yerbas-Endeavor/YERB-Coordinator](https://github.com/The-Yerbas-Endeavor/YERB-Coordinator).

The Qt Yerbas AI page supports approved local model generation, supervised
provider controls, receipt-bound reward requests, fixed testnet allowances,
confirmation status, stale observations and reorg recovery. The page does not
sign or broadcast reward transactions. The two-host pilot has tested request,
payment and six-confirmation/reorg status end to end. This is not decentralized
verification consensus or calibrated GPU metering. Automatic rewards are off.

## Layout and compatibility

- `../../src/qt/yerbasaipage.*`: wallet page (built into the wallet).
- `payments/`: reusable YERB identity, exact draft and payment-observation code.
- `owner-agent/`: Linux peer-authenticated local control and receipt-only relay.
- `provider/`: exact public runtime source from the validated pilot. Historical
  versions are retained for existing-job recovery; `provider-future-v1` is the
  migrated coordinator route. These directories contain no enrollment or state.
- `local-service/`: loopback Ollama service/CLI; explicitly approved installed
  models only, with no automatic downloads (independent component version 0.1.0a4).
- `text-inference/`: Python standard-library CPU inference source.
- `tests/qt/`: disposable Qt tests; live/GPU cases require explicit opt-in.

Provider services are Linux/POSIX only. Other wallet platforms may use local
model generation with Python 3, but provider controls require a supported agent.
Local generation does not require blockchain synchronization, wallet unlock,
GPU access or a coordinator. No model is downloaded automatically.

## Build and use

The normal wallet build includes the AI page. GitHub Actions builds Linux x86_64,
Linux ARM64, macOS Intel and Windows x86_64 packages using the existing depends
pipeline. Each archive includes binaries, SHA256SUMS and this public support
source. An archive is not an automatic provider installer.

Choose an existing approved portable model folder in the wallet. Model weights,
private job artifacts and pilot state are deliberately not shipped in CI.
The validated demo package is `yerbas-ai-text-model-0.1.0`; its checkpoint hash is
`b45353d27546bcb88b6fe77c973a1a29b973868da79d1f6abe1161377a2a93fe`.
The tiny demo is not a general chatbot.

Provider deployment still requires operator-reviewed root-owned policy, a
separate service account, GPU locks, installed approved runtime/model, provider
credential and public CA certificate. Never copy coordinator keys to a provider.
The imported runtime retains strict policy pins and existing pilot public CA
binding; new deployments must provision their own reviewed trust binding.
Do not run these files as a fresh-host installer or overwrite existing journals.
No wallet, live database, credential, TLS key or signed transaction belongs here.

## Tests

Run `python3 -B ci/check-ai-source.py` and `python3 -B ci/test-ai.py` from the
repository root. Linux Qt checks build separately with qmake6; the CI script
selects disposable tests and does not contact any live service or run a GPU.

Owner cancellation uses a durable retry queue. After the local job reaches a terminal state, the authenticated relay releases its coordinator reservation once. Completed, settled work is never refunded; network failures remain pending across agent restarts.
