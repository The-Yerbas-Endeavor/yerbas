// Copyright (c) 2026 The Yerbas Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#ifndef YERBAS_ASSETCONTRACTDB_H
#define YERBAS_ASSETCONTRACTDB_H

#include "assets/assetcontract.h"
#include "assets/assetcontractstate.h"
#include "dbwrapper.h"
#include "uint256.h"

#include <map>
#include <memory>

class CAssetContractDB : public CDBWrapper
{
public:
    explicit CAssetContractDB(size_t nCacheSize, bool fMemory = false, bool fWipe = false);

    CAssetContractDB(const CAssetContractDB&) = delete;
    CAssetContractDB& operator=(const CAssetContractDB&) = delete;

    bool ReadContract(const uint256& contractId, CAssetContractData& data) const;
    bool ReadState(const uint256& contractId, CAssetContractState& state) const;
    bool ReadBlockUndo(const uint256& blockHash, CBlockAssetContractUndo& undo) const;

    bool HaveContract(const uint256& contractId) const;
    bool HaveState(const uint256& contractId) const;

    bool WriteContract(const uint256& contractId, const CAssetContractData& data);
    bool WriteState(const uint256& contractId, const CAssetContractState& state);
    bool WriteBlockUndo(const uint256& blockHash, const CBlockAssetContractUndo& undo);

    bool EraseContract(const uint256& contractId);
    bool EraseState(const uint256& contractId);
    bool EraseBlockUndo(const uint256& blockHash);

    bool WriteBatch(const std::map<uint256, CAssetContractData>& contracts,
                    const std::map<uint256, CAssetContractState>& states,
                    const std::map<uint256, bool>& erasedContracts,
                    const std::map<uint256, bool>& erasedStates);
};

#endif // YERBAS_ASSETCONTRACTDB_H
