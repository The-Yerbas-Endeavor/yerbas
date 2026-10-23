// Copyright (c) 2026 The Yerbas developers
// Distributed under the MIT software license, see COPYING.
#ifndef YERBAS_QUORUMS_RECOVERY_H
#define YERBAS_QUORUMS_RECOVERY_H
#include "bls/bls.h"
#include "consensus/params.h"
#include "primitives/transaction.h"
#include <set>
class CBlock;
class CBlockIndex;
class CValidationState;
class JSONRPCRequest;
class UniValue;
namespace llmq {
static constexpr size_t RECOVERY_SIZE = 15;
static constexpr size_t RECOVERY_THRESHOLD = 11;
static constexpr int RECOVERY_ROTATION = 360;
static constexpr int RECOVERY_HISTORY = 1440;
static constexpr int RECOVERY_AGE = 720;
struct CRecoveryMember {
    uint256 proTxHash, stateHash;
    CBLSPublicKey key;
    ADD_SERIALIZE_METHODS;
    template <typename Stream, typename Operation> void SerializationOp(Stream& s, Operation ser_action) {
        READWRITE(proTxHash); READWRITE(stateHash); READWRITE(key);
    }
};
struct CRecoveryParticipation {
    CRecoveryMember member;
    int32_t session{0};
    bool signedValid{false};
    ADD_SERIALIZE_METHODS;
    template <typename Stream, typename Operation> void SerializationOp(Stream& s, Operation ser_action) {
        READWRITE(member); READWRITE(session); READWRITE(signedValid);
    }
};
struct CRecoveryRoster {
    int32_t height{0}, cutoff{0}, qualified{0};
    uint256 cutoffHash, seed;
    std::vector<CRecoveryMember> members;
    ADD_SERIALIZE_METHODS;
    template <typename Stream, typename Operation> void SerializationOp(Stream& s, Operation ser_action) {
        READWRITE(height); READWRITE(cutoff); READWRITE(qualified);
        READWRITE(cutoffHash); READWRITE(seed); READWRITE(members);
    }
    uint256 GetHash(const Consensus::Params& params) const;
};
bool HasRecoveryParticipation(const std::vector<CRecoveryParticipation>& history,
                             const CRecoveryMember& member, int cutoff);
std::vector<CRecoveryMember> RankRecoveryMembers(std::vector<CRecoveryMember> candidates,
                                               const uint256& seed);
CRecoveryRoster GetRecoveryRoster(const uint256& id);

struct CRecoveryState {
    uint8_t mode{0}; // 0 normal, 1 recovery, 2 locked after timeout
    int32_t failures{0}, successes{0}, trigger{-1}, budget{0};
    uint256 epoch, scheduledRoster, frozenRoster;
    bool sessionCommitted{false};
    std::set<uint256> consumed;
    ADD_SERIALIZE_METHODS;
    template <typename Stream, typename Operation> void SerializationOp(Stream& s, Operation ser_action) {
        READWRITE(mode); READWRITE(failures); READWRITE(successes); READWRITE(trigger);
        READWRITE(budget); READWRITE(epoch); READWRITE(scheduledRoster); READWRITE(frozenRoster);
        READWRITE(sessionCommitted); READWRITE(consumed);
    }
    void Advance(int height, const uint256& hash, bool closed, bool success, int eligible, int interval);
};
struct CRecoveryCertificate {
    uint16_t version{2};
    uint256 committee, epoch, target, stateHash, startHash, endHash;
    int32_t start{0}, end{0}, expiry{0};
    std::vector<std::pair<uint8_t, CBLSSignature>> signatures;
    ADD_SERIALIZE_METHODS;
    template <typename Stream, typename Operation> void SerializationOp(Stream& s, Operation ser_action) {
        READWRITE(version); READWRITE(committee); READWRITE(epoch); READWRITE(target);
        READWRITE(stateHash); READWRITE(startHash); READWRITE(endHash);
        READWRITE(start); READWRITE(end); READWRITE(expiry); READWRITE(signatures);
    }
    uint256 SignHash(const Consensus::Params& params) const;
    bool VerifySignatures(const Consensus::Params& params, const CRecoveryRoster& roster) const;
};
bool RecoveryEnabled(const Consensus::Params& params, int height);
CRecoveryState GetRecoveryState(const CBlockIndex* index);
bool CheckRecoveryTx(const CTransaction& tx, const CBlockIndex* prev, CValidationState& state);
bool CheckRecoveryBlock(const CBlock& block, const CBlockIndex* prev, CValidationState& state);
void ProcessRecoveryBlock(const CBlock& block, const CBlockIndex* index);
void UndoRecoveryBlock(const CBlockIndex* index);
UniValue RecoveryRPC(const JSONRPCRequest& request);
}
#endif
