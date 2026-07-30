// Copyright (c) 2026 The Yerbas Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#ifndef YERBAS_ASSETCONTRACTSTATE_H
#define YERBAS_ASSETCONTRACTSTATE_H

#include "assets/assetcontract.h"
#include "serialize.h"
#include "uint256.h"

#include <map>
#include <string>
#include <vector>

/** Deterministic key/value state. std::map guarantees canonical key ordering. */
class CAssetContractState
{
public:
    uint16_t nVersion{ASSET_CONTRACT_PROTOCOL_VERSION};
    uint256 contractId;
    AssetContractStatus nStatus{AssetContractStatus::INVALID};
    std::map<std::string, std::vector<unsigned char>> mapState;
    int nLastHeight{-1};
    uint256 lastTxid;

    void SetNull();
    bool IsNull() const { return contractId.IsNull(); }
    bool IsValid(std::string& strError) const;
    uint256 GetHash() const;

    ADD_SERIALIZE_METHODS;
    template <typename Stream, typename Operation>
    inline void SerializationOp(Stream& s, Operation ser_action)
    {
        READWRITE(nVersion);
        READWRITE(contractId);
        READWRITE(nStatus);
        READWRITE(mapState);
        READWRITE(nLastHeight);
        READWRITE(lastTxid);
    }
};

/** Previous value for one state key. */
struct CAssetContractStateUndoEntry
{
    std::string key;
    bool fExisted{false};
    std::vector<unsigned char> oldValue;

    ADD_SERIALIZE_METHODS;
    template <typename Stream, typename Operation>
    inline void SerializationOp(Stream& s, Operation ser_action)
    {
        READWRITE(key);
        READWRITE(fExisted);
        READWRITE(oldValue);
    }
};

/** Complete reversible record for one contract mutation. */
struct CAssetContractUndo
{
    uint256 contractId;
    bool fContractExisted{false};
    AssetContractStatus oldStatus{AssetContractStatus::INVALID};
    int oldLastHeight{-1};
    uint256 oldLastTxid;
    std::vector<CAssetContractStateUndoEntry> entries;

    ADD_SERIALIZE_METHODS;
    template <typename Stream, typename Operation>
    inline void SerializationOp(Stream& s, Operation ser_action)
    {
        READWRITE(contractId);
        READWRITE(fContractExisted);
        READWRITE(oldStatus);
        READWRITE(oldLastHeight);
        READWRITE(oldLastTxid);
        READWRITE(entries);
    }
};

struct CBlockAssetContractUndo
{
    std::vector<CAssetContractUndo> contracts;

    ADD_SERIALIZE_METHODS;
    template <typename Stream, typename Operation>
    inline void SerializationOp(Stream& s, Operation ser_action)
    {
        READWRITE(contracts);
    }
};

#endif // YERBAS_ASSETCONTRACTSTATE_H
