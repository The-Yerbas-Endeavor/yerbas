// Distributed under the MIT software license, see COPYING.
#ifndef YERBAS_PRUNEDBLOCK_H
#define YERBAS_PRUNEDBLOCK_H
#include "merkleblock.h"

// Small locally validated evidence retained independently of prunable block files.
struct CPrunedBlockMetadata {
    CTransactionRef coinbase;
    CPartialMerkleTree coinbaseProof;
    std::vector<CTransactionRef> commitments;
    CPartialMerkleTree commitmentProof;
    ADD_SERIALIZE_METHODS;
    template <typename Stream, typename Operation>
    void SerializationOp(Stream& s, Operation ser_action) {
        READWRITE(coinbase); READWRITE(coinbaseProof);
        READWRITE(commitments); READWRITE(commitmentProof);
    }
    bool Verify(const uint256& root) const {
        if (!coinbase || !coinbase->IsCoinBase()) return false;
        std::vector<uint256> hashes; std::vector<unsigned int> positions;
        auto proof = coinbaseProof;
        if (proof.ExtractMatches(hashes, positions) != root || hashes.size() != 1 ||
            positions.size() != 1 || positions[0] != 0 || hashes[0] != coinbase->GetHash()) return false;
        proof = commitmentProof; hashes.clear(); positions.clear();
        if (proof.ExtractMatches(hashes, positions) != root || hashes.size() != commitments.size()+1 ||
            positions.size() != hashes.size() || positions[0] != 0 || hashes[0] != coinbase->GetHash()) return false;
        for (size_t i=0; i<commitments.size(); ++i) {
            if (!commitments[i] || commitments[i]->nType != TRANSACTION_QUORUM_COMMITMENT ||
                commitments[i]->GetHash() != hashes[i+1] || positions[i+1] <= positions[i]) return false;
        }
        return true;
    }
};
#endif
