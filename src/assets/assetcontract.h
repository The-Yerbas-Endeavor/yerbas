// Copyright (c) 2026 The Yerbas Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#ifndef YERBAS_ASSETCONTRACT_H
#define YERBAS_ASSETCONTRACT_H

#include "amount.h"
#include "primitives/transaction.h"
#include "script/script.h"
#include "serialize.h"
#include "uint256.h"

#include <cstdint>
#include <string>
#include <vector>

static const uint16_t ASSET_CONTRACT_PROTOCOL_VERSION = 1;
static const uint32_t MAX_ASSET_CONTRACT_DEPLOY_PAYLOAD = 4 * 1024;
static const uint32_t MAX_ASSET_CONTRACT_CALL_PAYLOAD = 2 * 1024;
static const uint32_t MAX_ASSET_CONTRACT_STATE_ENTRIES = 256;
static const uint32_t MAX_ASSET_CONTRACT_STATE_KEY_SIZE = 64;
static const uint32_t MAX_ASSET_CONTRACT_STATE_VALUE_SIZE = 512;
static const uint32_t MAX_ASSET_CONTRACT_OPERATIONS = 1000;
static const uint32_t MAX_ASSET_CONTRACTS_PER_TX = 8;
static const uint16_t MAX_ASSET_CONTRACT_ROYALTY_BPS = 2500;

/** Consensus-defined templates. No arbitrary executable bytecode is accepted. */
enum class AssetContractTemplate : uint8_t
{
    INVALID = 0,
    ESCROW = 1,
    ROYALTY = 2,
    AUCTION = 3,
    ATOMIC_SWAP = 4,
    VOTING = 5
};

enum class AssetContractOperation : uint8_t
{
    INVALID = 0,
    DEPLOY = 1,
    CALL = 2,
    CANCEL = 3,
    FINALIZE = 4
};

enum class AssetContractStatus : uint8_t
{
    INVALID = 0,
    ACTIVE = 1,
    COMPLETED = 2,
    CANCELLED = 3,
    EXPIRED = 4
};

/** Immutable contract deployment data. */
class CAssetContractDeploy
{
public:
    uint16_t nVersion;
    AssetContractTemplate nTemplate;
    uint16_t nTemplateVersion;
    std::string strAssetName;
    CScript ownerScript;
    std::vector<unsigned char> vParameters;
    uint32_t nExecutionLimit;

    CAssetContractDeploy()
    {
        SetNull();
    }

    void SetNull()
    {
        nVersion = ASSET_CONTRACT_PROTOCOL_VERSION;
        nTemplate = AssetContractTemplate::INVALID;
        nTemplateVersion = 0;
        strAssetName.clear();
        ownerScript.clear();
        vParameters.clear();
        nExecutionLimit = 0;
    }

    bool IsNull() const
    {
        return nTemplate == AssetContractTemplate::INVALID;
    }

    bool IsValid(std::string& strError) const;

    ADD_SERIALIZE_METHODS;

    template <typename Stream, typename Operation>
    inline void SerializationOp(Stream& s, Operation ser_action)
    {
        READWRITE(nVersion);
        READWRITE(nTemplate);
        READWRITE(nTemplateVersion);
        READWRITE(strAssetName);
        READWRITE(ownerScript);
        READWRITE(vParameters);
        READWRITE(nExecutionLimit);
    }
};

/** A bounded state transition request against an existing contract. */
class CAssetContractCall
{
public:
    uint16_t nVersion;
    uint256 contractId;
    AssetContractOperation nOperation;
    uint16_t nMethod;
    std::vector<unsigned char> vArguments;
    uint32_t nExecutionLimit;
    CAmount nAttachedYerb;

    CAssetContractCall()
    {
        SetNull();
    }

    void SetNull()
    {
        nVersion = ASSET_CONTRACT_PROTOCOL_VERSION;
        contractId.SetNull();
        nOperation = AssetContractOperation::INVALID;
        nMethod = 0;
        vArguments.clear();
        nExecutionLimit = 0;
        nAttachedYerb = 0;
    }

    bool IsNull() const
    {
        return contractId.IsNull() || nOperation == AssetContractOperation::INVALID;
    }

    bool IsValid(std::string& strError) const;

    ADD_SERIALIZE_METHODS;

    template <typename Stream, typename Operation>
    inline void SerializationOp(Stream& s, Operation ser_action)
    {
        READWRITE(nVersion);
        READWRITE(contractId);
        READWRITE(nOperation);
        READWRITE(nMethod);
        READWRITE(vArguments);
        READWRITE(nExecutionLimit);
        READWRITE(nAttachedYerb);
    }
};

/** Persisted metadata for one deployed contract. */
class CAssetContractData
{
public:
    CAssetContractDeploy deploy;
    COutPoint deploymentOutpoint;
    AssetContractStatus nStatus;
    int nCreatedHeight;
    int nUpdatedHeight;

    CAssetContractData()
    {
        SetNull();
    }

    void SetNull()
    {
        deploy.SetNull();
        deploymentOutpoint.SetNull();
        nStatus = AssetContractStatus::INVALID;
        nCreatedHeight = -1;
        nUpdatedHeight = -1;
    }

    ADD_SERIALIZE_METHODS;

    template <typename Stream, typename Operation>
    inline void SerializationOp(Stream& s, Operation ser_action)
    {
        READWRITE(deploy);
        READWRITE(deploymentOutpoint);
        READWRITE(nStatus);
        READWRITE(nCreatedHeight);
        READWRITE(nUpdatedHeight);
    }
};

/** Deterministically derive a contract ID from its deployment outpoint. */
uint256 GetAssetContractId(const COutPoint& deploymentOutpoint);

#endif // YERBAS_ASSETCONTRACT_H
