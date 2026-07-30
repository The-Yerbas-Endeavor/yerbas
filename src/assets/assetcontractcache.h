// Copyright (c) 2026 The Yerbas Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#ifndef YERBAS_ASSETCONTRACTCACHE_H
#define YERBAS_ASSETCONTRACTCACHE_H

#include "assets/assetcontractdb.h"

#include <map>

class CAssetContractCache
{
private:
    CAssetContractDB* m_db;
    std::map<uint256, CAssetContractData> m_contracts;
    std::map<uint256, CAssetContractState> m_states;
    std::map<uint256, bool> m_erasedContracts;
    std::map<uint256, bool> m_erasedStates;

public:
    explicit CAssetContractCache(CAssetContractDB* db) : m_db(db) {}

    bool GetContract(const uint256& contractId, CAssetContractData& data) const;
    bool GetState(const uint256& contractId, CAssetContractState& state) const;
    bool HaveContract(const uint256& contractId) const;

    void PutContract(const uint256& contractId, const CAssetContractData& data);
    void PutState(const uint256& contractId, const CAssetContractState& state);
    void EraseContract(const uint256& contractId);
    void EraseState(const uint256& contractId);

    bool Flush();
    void Clear();
};

#endif // YERBAS_ASSETCONTRACTCACHE_H
