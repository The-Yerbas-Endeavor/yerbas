# Isolated installation acceptance

Build the disposable image with `docker build -t yerbas-clean-install:20261118 .`
from this directory. Obtain the exact offline wheels listed in the sibling
`provider-fresh-host-candidate-v1/runtime/WHEELS.json`, then set
`YERBAS_OFFLINE_WHEELS` to their absolute directory. Run `bash run-container.sh`
and `bash run-interrupted.sh`. Container names are fixed intentionally; inspect
and preserve a previous result before choosing a new name. No automatic cleanup
or overwrite is performed. Docker image preparation downloads Ubuntu packages;
the installer containers themselves have no network access.

The harnesses require Docker access. They mount only public candidate files,
offline wheels and this evidence directory. They create separate disposable
accounts and never mount live keys, wallets or service state. The successful
installation remains disabled. The interruption test kills the installer after
root staging, checks its journal is unchanged and confirms retry refusal.

The two pinned collector.so artifacts are the collector included in the tested
runtime; corresponding collector source is under the repository's
`contrib/yerbas-ai/provider/provider-phase-cupti-v1/collector/`. They are hash
checked, never loaded during these CPU-only installation checks.

A passing result does not establish physical GPU enrollment, systemd boot,
independent operators, or mainnet readiness.
