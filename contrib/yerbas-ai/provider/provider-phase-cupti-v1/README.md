# Phase-attributed provider runtime

Source for the installed Linux private-pilot runtime. The wallet build archives carry this source; building or opening the wallet does not install it or enable GPU jobs.

This upgrade depends on an already enrolled provider and its retained legacy, measured, future, and direct runtimes. It is not a fresh-host installer. Existing run IDs keep their original runtime and state; ambiguous state is rejected. Disabling new-job selection preserves phase-runtime recovery.

The deployment payload is sealed by INSTALL-SHA256.json and direct_policy.py. The separately supplied collector.so must match SHA256 56e562f1e3ef224f64d7468c59ef998af259075d68adc029975fd05c3f90ef8e. No executable collector, NVIDIA headers, CUDA runtime, dataset, credentials, or private state are shipped here. collector/collector.cpp records the collector source used by the pilot. Recompilation alone does not establish equivalence to the accepted binary; a different binary requires review, repinning and GPU acceptance.

Use prepare_package.py with the existing verified collector to assemble a separate deployment directory. It checks every sealed runtime file before producing the directory. install.py still checks the manifest, existing root-owned policy, runtime files, service overrides and state ownership. Installation requires root and explicit --activate to route future jobs. Never copy provider journals or credentials between hosts.

Validation: both physical hosts passed isolated GPU HTTPS/lost-ack acceptance. One installed anno2 contribution completed against the migrated coordinator and was independently reproduced on u26. Installed u26 interruption at step 1000 resumed once through step 6000 under its original deadlines, with one settlement and matching duplicate resume. Receipt-bound raw phase reanalysis passed. The interrupted prefix remains missing from timing coverage.

Training and checkpoint kernel intervals are reported separately. Capture completeness, calibration, honest provider timing, and approved GPU reward time remain unverified. This runtime does not authorize payments or decentralized consensus. Hashes and matching model outputs do not establish trustworthy time accounting.

CI runs CPU-only evidence, routing, policy and package checks. GPU execution, installation, mining and payments are never part of these tests.
