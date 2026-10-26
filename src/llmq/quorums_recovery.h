// Copyright (c) 2026 The Yerbas developers
// Distributed under the MIT software license, see the accompanying COPYING file.
#ifndef YERBAS_QUORUMS_RECOVERY_H
#define YERBAS_QUORUMS_RECOVERY_H

#include "consensus/params.h"
#include "pubkey.h"
#include "serialize.h"
#include "uint256.h"

#include <array>
#include <set>
#include <string>
#include <vector>

class CBlockIndex;
class CEvoDB;
class CBlock;
class CTransaction;
class CValidationState;

namespace llmq {

// Experimental protocol building block: public networks cannot enable it.
struct RecoveryPolicy {
    bool enabled{false};
    uint256 genesisHash;
    std::set<CKeyID> authorities;
    size_t requiredSignatures{0};
    int dkgInterval{0};
    int maxDuration{0};
    int maxStartDelay{0};
    int maxAnchorAge{0};
    int minAnchorHeight{0};
    uint256 bootstrapBlockHash; // named devnet block 1, which is connected by startup
};

struct RecoveryRequest {
    static constexpr size_t MAX_SIGNERS = 16;
    uint16_t version{1};
    uint256 genesisHash;
    uint256 previousAuthorization;
    int32_t anchorHeight{0};
    uint256 anchorHash;
    int32_t startHeight{0};
    int32_t endHeight{0}; // v1: exclusive expiry. v2: 0=ON, startHeight=OFF.
    std::vector<std::array<unsigned char, 65>> signatures;

    // Domain-separated identity excludes signature ordering/encoding.
    uint256 GetAuthorizationHash() const;

    ADD_SERIALIZE_METHODS;
    template <typename Stream, typename Operation>
    inline void SerializationOp(Stream& s, Operation ser_action)
    {
        READWRITE(version);
        READWRITE(genesisHash);
        READWRITE(previousAuthorization);
        READWRITE(anchorHeight);
        READWRITE(anchorHash);
        READWRITE(startHeight);
        READWRITE(endHeight);
        uint64_t count = signatures.size();
        READWRITE(COMPACTSIZE(count));
        if (count > MAX_SIGNERS) throw std::ios_base::failure("too many recovery signatures");
        if (ser_action.ForRead()) signatures.resize(count);
        for (auto& signature : signatures) {
            for (auto& byte : signature) READWRITE(byte);
        }
    }
};

struct RecoveryState {
    uint256 lastAuthorization;
    int32_t startHeight{0};
    int32_t endHeight{0};

    bool IsLowAt(int height) const { return startHeight > 0 && height >= startHeight && (endHeight == 0 || height < endHeight); }
    // Evaluate against the frozen state that authorized this quorum.
    bool AllowsRecoverySigning(int quorumHeight, int signingHeight) const
    {
        return IsLowAt(quorumHeight) && signingHeight >= quorumHeight && (endHeight == 0 || signingHeight < endHeight);
    }

    ADD_SERIALIZE_METHODS;
    template <typename Stream, typename Operation>
    inline void SerializationOp(Stream& s, Operation ser_action)
    {
        READWRITE(lastAuthorization);
        READWRITE(startHeight);
        READWRITE(endHeight);
    }
};

// Validate a record proposed for the child of parent. Inputs must come from
// the same branch. Failure leaves next untouched; there is no global mutation.
bool ApplyRecoveryRequest(const RecoveryRequest& request, const RecoveryPolicy& policy,
                          const CBlockIndex& parent, const RecoveryState& previous,
                          RecoveryState& next, std::string& error);

// Uses the caller's existing CEvoDB block transaction. No active-tip cache:
// every lookup is keyed by block hash, including competing branches.
class RecoveryStateStore {
    CEvoDB& db;
    const RecoveryPolicy policy;
public:
    RecoveryStateStore(CEvoDB& database, const RecoveryPolicy& rules) : db(database), policy(rules) {}
    bool ReadState(const CBlockIndex& block, RecoveryState& state) const;
    bool ConnectBlock(const CBlockIndex& block, const RecoveryRequest* request, std::string& error);
    bool DisconnectBlock(const CBlockIndex& block);
};

// Experimental integration: opt-in regtest or the isolated recovery devnet profile.
bool RecoveryProtocolEnabled();
RecoveryPolicy GetRecoveryPolicy();
bool ResolveRecoveryParamsAtHeight(Consensus::LLMQType type, const CBlockIndex* branch, int height, Consensus::LLMQParams& out);
bool RecoveryQuorumCanSign(Consensus::LLMQType type, const CBlockIndex* quorum, int signingHeight);
// Resolve from the parent of the quorum-start block, never the active tip.
bool ResolveRecoveryQuorumParams(Consensus::LLMQType type, const CBlockIndex* quorum, Consensus::LLMQParams& out);
bool CheckRecoveryTransaction(const CTransaction& tx, const CBlockIndex* parent, CValidationState& state);
bool ConnectRecoveryBlock(const CBlock& block, const CBlockIndex& index, CValidationState& state);
bool DisconnectRecoveryBlock(const CBlockIndex& index);

} // namespace llmq
#endif
