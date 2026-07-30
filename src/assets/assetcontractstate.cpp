// Copyright (c) 2026 The Yerbas Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include "assets/assetcontractstate.h"

#include "hash.h"

void CAssetContractState::SetNull()
{
    nVersion = ASSET_CONTRACT_PROTOCOL_VERSION;
    contractId.SetNull();
    nStatus = AssetContractStatus::INVALID;
    mapState.clear();
    nLastHeight = -1;
    lastTxid.SetNull();
}

bool CAssetContractState::IsValid(std::string& strError) const
{
    if (nVersion != ASSET_CONTRACT_PROTOCOL_VERSION) {
        strError = "unsupported asset contract state version";
        return false;
    }
    if (contractId.IsNull()) {
        strError = "asset contract state has null contract id";
        return false;
    }
    if (nStatus == AssetContractStatus::INVALID) {
        strError = "asset contract state has invalid status";
        return false;
    }
    if (mapState.size() > MAX_ASSET_CONTRACT_STATE_ENTRIES) {
        strError = "asset contract state contains too many entries";
        return false;
    }
    for (const auto& item : mapState) {
        if (item.first.empty() || item.first.size() > MAX_ASSET_CONTRACT_STATE_KEY_SIZE) {
            strError = "asset contract state key size is invalid";
            return false;
        }
        if (item.second.size() > MAX_ASSET_CONTRACT_STATE_VALUE_SIZE) {
            strError = "asset contract state value is too large";
            return false;
        }
    }
    return true;
}

uint256 CAssetContractState::GetHash() const
{
    return SerializeHash(*this);
}
