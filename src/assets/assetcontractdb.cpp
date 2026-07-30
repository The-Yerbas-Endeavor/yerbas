// Copyright (c) 2026 The Yerbas Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include "assets/assetcontractdb.h"

#include "fs.h"

namespace {
static const char DB_CONTRACT = 'c';
static const char DB_STATE = 's';
static const char DB_UNDO = 'u';
}

CAssetContractDB::CAssetContractDB(size_t nCacheSize, bool fMemory, bool fWipe)
    : CDBWrapper(GetDataDir() / "assetcontracts", nCacheSize, fMemory, fWipe)
{
}

bool CAssetContractDB::ReadContract(const uint256& contractId, CAssetContractData& data) const
{
    return Read(std::make_pair(DB_CONTRACT, contractId), data);
}

bool CAssetContractDB::ReadState(const uint256& contractId, CAssetContractState& state) const
{
    return Read(std::make_pair(DB_STATE, contractId), state);
}

bool CAssetContractDB::ReadBlockUndo(const uint256& blockHash, CBlockAssetContractUndo& undo) const
{
    return Read(std::make_pair(DB_UNDO, blockHash), undo);
}

bool CAssetContractDB::HaveContract(const uint256& contractId) const
{
    return Exists(std::make_pair(DB_CONTRACT, contractId));
}

bool CAssetContractDB::HaveState(const uint256& contractId) const
{
    return Exists(std::make_pair(DB_STATE, contractId));
}

bool CAssetContractDB::WriteContract(const uint256& contractId, const CAssetContractData& data)
{
    return Write(std::make_pair(DB_CONTRACT, contractId), data);
}

bool CAssetContractDB::WriteState(const uint256& contractId, const CAssetContractState& state)
{
    return Write(std::make_pair(DB_STATE, contractId), state);
}

bool CAssetContractDB::WriteBlockUndo(const uint256& blockHash, const CBlockAssetContractUndo& undo)
{
    return Write(std::make_pair(DB_UNDO, blockHash), undo);
}

bool CAssetContractDB::EraseContract(const uint256& contractId)
{
    return Erase(std::make_pair(DB_CONTRACT, contractId));
}

bool CAssetContractDB::EraseState(const uint256& contractId)
{
    return Erase(std::make_pair(DB_STATE, contractId));
}

bool CAssetContractDB::EraseBlockUndo(const uint256& blockHash)
{
    return Erase(std::make_pair(DB_UNDO, blockHash));
}

bool CAssetContractDB::WriteBatch(const std::map<uint256, CAssetContractData>& contracts,
                                  const std::map<uint256, CAssetContractState>& states,
                                  const std::map<uint256, bool>& erasedContracts,
                                  const std::map<uint256, bool>& erasedStates)
{
    CDBBatch batch(*this);
    for (const auto& item : contracts) batch.Write(std::make_pair(DB_CONTRACT, item.first), item.second);
    for (const auto& item : states) batch.Write(std::make_pair(DB_STATE, item.first), item.second);
    for (const auto& item : erasedContracts) if (item.second) batch.Erase(std::make_pair(DB_CONTRACT, item.first));
    for (const auto& item : erasedStates) if (item.second) batch.Erase(std::make_pair(DB_STATE, item.first));
    return CDBWrapper::WriteBatch(batch, true);
}
