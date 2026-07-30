// Copyright (c) 2026 The Yerbas Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include "assets/assetcontractcache.h"

bool CAssetContractCache::GetContract(const uint256& contractId, CAssetContractData& data) const
{
    const auto erased = m_erasedContracts.find(contractId);
    if (erased != m_erasedContracts.end() && erased->second) return false;
    const auto cached = m_contracts.find(contractId);
    if (cached != m_contracts.end()) {
        data = cached->second;
        return true;
    }
    return m_db && m_db->ReadContract(contractId, data);
}

bool CAssetContractCache::GetState(const uint256& contractId, CAssetContractState& state) const
{
    const auto erased = m_erasedStates.find(contractId);
    if (erased != m_erasedStates.end() && erased->second) return false;
    const auto cached = m_states.find(contractId);
    if (cached != m_states.end()) {
        state = cached->second;
        return true;
    }
    return m_db && m_db->ReadState(contractId, state);
}

bool CAssetContractCache::HaveContract(const uint256& contractId) const
{
    CAssetContractData data;
    return GetContract(contractId, data);
}

void CAssetContractCache::PutContract(const uint256& contractId, const CAssetContractData& data)
{
    m_contracts[contractId] = data;
    m_erasedContracts.erase(contractId);
}

void CAssetContractCache::PutState(const uint256& contractId, const CAssetContractState& state)
{
    m_states[contractId] = state;
    m_erasedStates.erase(contractId);
}

void CAssetContractCache::EraseContract(const uint256& contractId)
{
    m_contracts.erase(contractId);
    m_erasedContracts[contractId] = true;
}

void CAssetContractCache::EraseState(const uint256& contractId)
{
    m_states.erase(contractId);
    m_erasedStates[contractId] = true;
}

bool CAssetContractCache::Flush()
{
    if (!m_db || !m_db->WriteBatch(m_contracts, m_states, m_erasedContracts, m_erasedStates)) return false;
    Clear();
    return true;
}

void CAssetContractCache::Clear()
{
    m_contracts.clear();
    m_states.clear();
    m_erasedContracts.clear();
    m_erasedStates.clear();
}
