# YERB identity and payment primitives

These library modules provide fixed-purpose testnet identity claims, exact reward
drafts, approval journals, duplicate-safe transaction bindings and reorg-aware
observations. `consensus-verify.cpp` is the native script-verification helper;
`signature_verifier.py` requires its separately built, hash-pinned executable.
The default CI package does not include a prebuilt native helper or enable signing.
The application must supply reviewed coordinator evidence and explicit testnet
policy. No live treasury, keys, transactions, approval records or account data
are included. Site-specific operator scripts remain outside the repository.
These modules do not make provider-reported GPU time trustworthy.
