// Copyright (c) 2026 The Yerbas Core developers
// Distributed under the MIT software license, see COPYING.
#ifndef YERBAS_WALLET_ASSETISSUANCE_H
#define YERBAS_WALLET_ASSETISSUANCE_H
#include <string>

// V4 wallet policy only, not consensus. Estimated 2027-01-01 00:00 UTC
// from height 1149666 and the preceding 10080 blocks (122.5578 seconds/block).
// This fixed height does not guarantee a wall-clock activation time.
static constexpr int MAINNET_ASSET_WALLET_ACTIVATION_HEIGHT = 1195400;
inline bool WalletAssetHeightReached(bool mainnet, int tipHeight, int unlockHeight)
{
    return !mainnet || (unlockHeight >= 0 && tipHeight >= unlockHeight);
}
class CTransaction;
bool IsWalletAssetTransaction(const CTransaction& tx);
bool WalletAssetOperationsAllowed(std::string& reason);
#endif
