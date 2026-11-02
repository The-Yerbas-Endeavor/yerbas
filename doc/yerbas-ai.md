# Yerbas AI 5.0.0.0

Wallet and provider source: [contrib/yerbas-ai](../contrib/yerbas-ai/README.md).
Coordinator source: https://github.com/The-Yerbas-Endeavor/YERB-Coordinator.

The authoritative development branch for this wallet integration is `5.0.0.0`.
Actions binary artifacts are produced per platform on pushes to that branch,
pull requests and manual runs. Download the matching `*-binaries` artifact from
a successful run; preserve the complete archive and verify SHA256SUMS.
This source update does not replace any running node or provider automatically.

The private reduced-collateral testnet is selected explicitly with `-testnet=1
-testnetfastcollateral=1` and a separate data directory. Never reuse mainnet
wallet data for pilot tests. Ordinary testnet and the reduced-collateral profile
are different networks. The AI page does not change the node's network flags.
