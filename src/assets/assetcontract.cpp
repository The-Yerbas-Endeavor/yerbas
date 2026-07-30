// Copyright (c) 2026 The Yerbas Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include "assets/assetcontract.h"

#include "hash.h"

namespace {

bool IsKnownTemplate(AssetContractTemplate type)
{
    switch (type) {
    case AssetContractTemplate::ESCROW:
    case AssetContractTemplate::ROYALTY:
    case AssetContractTemplate::AUCTION:
    case AssetContractTemplate::ATOMIC_SWAP:
    case AssetContractTemplate::VOTING:
        return true;
    case AssetContractTemplate::INVALID:
        return false;
    }
    return false;
}

bool IsKnownCallOperation(AssetContractOperation operation)
{
    switch (operation) {
    case AssetContractOperation::CALL:
    case AssetContractOperation::CANCEL:
    case AssetContractOperation::FINALIZE:
        return true;
    case AssetContractOperation::INVALID:
    case AssetContractOperation::DEPLOY:
        return false;
    }
    return false;
}

} // namespace

bool CAssetContractDeploy::IsValid(std::string& strError) const
{
    strError.clear();

    if (nVersion != ASSET_CONTRACT_PROTOCOL_VERSION) {
        strError = "unsupported asset contract protocol version";
        return false;
    }

    if (!IsKnownTemplate(nTemplate)) {
        strError = "unknown asset contract template";
        return false;
    }

    if (nTemplateVersion == 0) {
        strError = "asset contract template version must be nonzero";
        return false;
    }

    if (strAssetName.empty()) {
        strError = "asset contract must specify a controlling asset";
        return false;
    }

    if (ownerScript.empty()) {
        strError = "asset contract owner script is empty";
        return false;
    }

    if (vParameters.size() > MAX_ASSET_CONTRACT_DEPLOY_PAYLOAD) {
        strError = "asset contract deployment payload exceeds limit";
        return false;
    }

    if (nExecutionLimit == 0 || nExecutionLimit > MAX_ASSET_CONTRACT_OPERATIONS) {
        strError = "asset contract execution limit is out of range";
        return false;
    }

    return true;
}

bool CAssetContractCall::IsValid(std::string& strError) const
{
    strError.clear();

    if (nVersion != ASSET_CONTRACT_PROTOCOL_VERSION) {
        strError = "unsupported asset contract protocol version";
        return false;
    }

    if (contractId.IsNull()) {
        strError = "asset contract ID is null";
        return false;
    }

    if (!IsKnownCallOperation(nOperation)) {
        strError = "invalid asset contract call operation";
        return false;
    }

    if (vArguments.size() > MAX_ASSET_CONTRACT_CALL_PAYLOAD) {
        strError = "asset contract call payload exceeds limit";
        return false;
    }

    if (nExecutionLimit == 0 || nExecutionLimit > MAX_ASSET_CONTRACT_OPERATIONS) {
        strError = "asset contract execution limit is out of range";
        return false;
    }

    if (nAttachedYerb < 0 || !MoneyRange(nAttachedYerb)) {
        strError = "attached YERB amount is out of range";
        return false;
    }

    return true;
}

uint256 GetAssetContractId(const COutPoint& deploymentOutpoint)
{
    CHashWriter ss(SER_GETHASH, 0);
    ss << deploymentOutpoint;
    return ss.GetHash();
}
