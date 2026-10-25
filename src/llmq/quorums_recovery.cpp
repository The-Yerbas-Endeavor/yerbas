// Copyright (c) 2026 The Yerbas developers
// Distributed under the MIT software license, see the accompanying COPYING file.
#include "quorums_recovery.h"

#include "chain.h"
#include "base58.h"
#include "chainparams.h"
#include "consensus/validation.h"
#include "evo/evodb.h"
#include "evo/deterministicmns.h"
#include "evo/specialtx.h"
#include "hash.h"
#include "primitives/block.h"
#include "util.h"
#include "version.h"
#include "validation.h"

namespace llmq {

namespace {
bool ValidPolicy(const RecoveryPolicy& policy)
{
    return !policy.genesisHash.IsNull() && !policy.authorities.empty() &&
           policy.authorities.size() <= RecoveryRequest::MAX_SIGNERS &&
           policy.requiredSignatures > policy.authorities.size() / 2 &&
           policy.requiredSignatures <= policy.authorities.size() &&
           policy.dkgInterval > 0 && policy.maxDuration > 0 &&
           policy.maxStartDelay > 0 && policy.maxAnchorAge >= 0 && policy.minAnchorHeight >= 0;
}
const std::string RECOVERY_STATE_KEY = "llmq_recovery_state_v1";
}

uint256 RecoveryRequest::GetAuthorizationHash() const
{
    CHashWriter writer(SER_GETHASH, PROTOCOL_VERSION);
    writer << std::string("Yerbas/LLMQRecovery/v1") << version << genesisHash
           << previousAuthorization << anchorHeight << anchorHash << startHeight << endHeight;
    return writer.GetHash();
}

bool ApplyRecoveryRequest(const RecoveryRequest& request, const RecoveryPolicy& policy,
                          const CBlockIndex& parent, const RecoveryState& previous,
                          RecoveryState& next, std::string& error)
{
    auto reject = [&](const char* reason) { error = reason; return false; };
    if (!policy.enabled) return reject("recovery-disabled");
    if (!ValidPolicy(policy)) {
        return reject("recovery-invalid-policy");
    }
    if (request.version != 1) return reject("recovery-version");
    if (request.genesisHash != policy.genesisHash) return reject("recovery-network");
    const auto genesis = parent.GetAncestor(0);
    if (!genesis || genesis->GetBlockHash() != policy.genesisHash) return reject("recovery-branch-network");
    if (request.previousAuthorization != previous.lastAuthorization) return reject("recovery-sequence");
    if (request.anchorHeight < policy.minAnchorHeight || request.anchorHeight > parent.nHeight ||
        int64_t(parent.nHeight) - request.anchorHeight > policy.maxAnchorAge) {
        return reject("recovery-anchor-height");
    }
    const auto anchor = parent.GetAncestor(request.anchorHeight);
    if (!anchor || anchor->GetBlockHash() != request.anchorHash) return reject("recovery-anchor");
    // The record is included at parent+1. The earliest affected quorum must
    // start later, so its parameters never depend on transactions in itself.
    if (int64_t(request.startHeight) <= int64_t(parent.nHeight) + 1 ||
        int64_t(request.startHeight) - parent.nHeight > policy.maxStartDelay ||
        request.startHeight % policy.dkgInterval != 0 ||
        request.endHeight % policy.dkgInterval != 0 ||
        request.endHeight <= request.startHeight ||
        int64_t(request.endHeight) - request.startHeight > policy.maxDuration) {
        return reject("recovery-window");
    }
    if (request.startHeight < previous.endHeight) return reject("recovery-overlap");
    if (parent.nHeight < previous.endHeight) return reject("recovery-window-outstanding");
    if (request.signatures.size() < policy.requiredSignatures ||
        request.signatures.size() > policy.authorities.size()) return reject("recovery-signature-count");

    const auto hash = request.GetAuthorizationHash();
    std::set<CKeyID> signers;
    for (const auto& bytes : request.signatures) {
        CPubKey key;
        if (!key.RecoverCompact(hash, std::vector<unsigned char>(bytes.begin(), bytes.end())) ||
            !policy.authorities.count(key.GetID())) return reject("recovery-signature");
        if (!signers.emplace(key.GetID()).second) return reject("recovery-duplicate-signer");
    }
    RecoveryState accepted;
    accepted.lastAuthorization = hash;
    accepted.startHeight = request.startHeight;
    accepted.endHeight = request.endHeight;
    next = accepted;
    error.clear();
    return true;
}

bool RecoveryStateStore::ReadState(const CBlockIndex& block, RecoveryState& state) const
{
    if (!policy.enabled || !ValidPolicy(policy)) return false;
    if (block.nHeight == 0 && block.GetBlockHash() == policy.genesisHash) {
        state = RecoveryState{};
        return true;
    }
    if (block.nHeight == 1 && !policy.bootstrapBlockHash.IsNull() && block.GetBlockHash() == policy.bootstrapBlockHash) {
        state = RecoveryState{};
        return true;
    }
    return db.Read(std::make_pair(RECOVERY_STATE_KEY, block.GetBlockHash()), state);
}

bool RecoveryStateStore::ConnectBlock(const CBlockIndex& block, const RecoveryRequest* request, std::string& error)
{
    if (!policy.enabled) { error = "recovery-disabled"; return false; }
    if (!ValidPolicy(policy)) { error = "recovery-invalid-policy"; return false; }
    if (!block.pprev || int64_t(block.nHeight) != int64_t(block.pprev->nHeight) + 1) {
        error = "recovery-parent";
        return false;
    }
    RecoveryState previous;
    if (!ReadState(*block.pprev, previous)) {
        error = "recovery-parent-state-missing";
        return false;
    }
    RecoveryState next = previous;
    if (request && !ApplyRecoveryRequest(*request, policy, *block.pprev, previous, next, error)) return false;
    RecoveryState existing;
    if (ReadState(block, existing) &&
        (existing.lastAuthorization != next.lastAuthorization || existing.startHeight != next.startHeight ||
         existing.endHeight != next.endHeight)) {
        error = "recovery-state-conflict";
        return false;
    }
    db.Write(std::make_pair(RECOVERY_STATE_KEY, block.GetBlockHash()), next);
    error.clear();
    return true;
}

bool RecoveryStateStore::DisconnectBlock(const CBlockIndex& block)
{
    if (!policy.enabled || !ValidPolicy(policy) || !block.pprev) return false;
    const auto key = std::make_pair(RECOVERY_STATE_KEY, block.GetBlockHash());
    if (!db.Exists(key)) return false;
    db.Erase(key);
    return true;
}

bool RecoveryProtocolEnabled()
{
    return (Params().NetworkIDString() == CBaseChainParams::REGTEST && gArgs.GetBoolArg("-llmqrecoverytest", false)) ||
        (Params().NetworkIDString() == CBaseChainParams::DEVNET && gArgs.GetBoolArg("-llmqrecoverydevnet", false));
}

RecoveryPolicy GetRecoveryPolicy()
{
    RecoveryPolicy policy;
    if (!RecoveryProtocolEnabled()) return policy;
    policy.enabled = true;
    policy.genesisHash = Params().GenesisBlock().GetHash();
    for (const auto& address : Params().SporkAddresses()) {
        CKeyID id;
        if (!CBitcoinAddress(address).GetKeyID(id)) return RecoveryPolicy{};
        policy.authorities.emplace(id);
    }
    policy.requiredSignatures = Params().MinSporkKeys();
    // Test-network policy only; no public-network values are assigned.
    policy.dkgInterval = 30;
    policy.maxDuration = 60;
    policy.maxStartDelay = 60;
    policy.maxAnchorAge = 60;
    if (Params().NetworkIDString() == CBaseChainParams::DEVNET) {
        policy.maxDuration = 90;
        policy.minAnchorHeight = 1; // bind every record to this named devnet, not the shared base genesis
        policy.bootstrapBlockHash = Params().GetConsensus().hashDevnetGenesisBlock;
    }
    return policy;
}

bool ResolveRecoveryParamsAtHeight(Consensus::LLMQType type, const CBlockIndex* branch, int height, Consensus::LLMQParams& out)
{
    LOCK(cs_main);
    if (!RecoveryProtocolEnabled() || !branch || height < 0 || int64_t(height) > int64_t(branch->nHeight) + 1) return false;
    const auto& types = Params().GetConsensus().llmqs;
    auto it = types.find(type);
    if (it == types.end()) return false;
    const int start = height - height % it->second.dkgInterval;
    const auto* parent = branch->GetAncestor(start > 0 ? start - 1 : 0);
    if (!parent) return false;
    RecoveryState state;
    if (!RecoveryStateStore(*evoDb, GetRecoveryPolicy()).ReadState(*parent, state)) return false;
    if (type == Consensus::LLMQ_50_60) {
        const auto list = deterministicMNManager->GetListForBlock(parent);
        out = RecoveryType1Params(list.GetAllMNsCount(), state.IsLowAt(start));
    } else {
        out = it->second;
    }
    return true;
}

bool ResolveRecoveryQuorumParams(Consensus::LLMQType type, const CBlockIndex* quorum, Consensus::LLMQParams& out)
{
    if (!quorum || !ResolveRecoveryParamsAtHeight(type, quorum, quorum->nHeight, out)) return false;
    return quorum->nHeight % out.dkgInterval == 0;
}

bool RecoveryQuorumCanSign(Consensus::LLMQType type, const CBlockIndex* quorum, int signingHeight)
{
    if (!RecoveryProtocolEnabled() || type != Consensus::LLMQ_50_60) return true;
    LOCK(cs_main);
    if (!quorum) return false;
    RecoveryState state;
    if (!RecoveryStateStore(*evoDb, GetRecoveryPolicy()).ReadState(quorum->pprev ? *quorum->pprev : *quorum, state)) return false;
    return !state.IsLowAt(quorum->nHeight) || state.AllowsRecoverySigning(quorum->nHeight, signingHeight);
}

bool CheckRecoveryTransaction(const CTransaction& tx, const CBlockIndex* parent, CValidationState& state)
{
    if (!RecoveryProtocolEnabled()) return state.DoS(10, false, REJECT_INVALID, "bad-tx-type-check");
    RecoveryRequest request;
    if (!parent || !GetTxPayload(tx, request)) return state.DoS(100, false, REJECT_INVALID, "bad-recovery-payload");
    const auto policy = GetRecoveryPolicy();
    RecoveryStateStore store(*evoDb, policy);
    RecoveryState previous, next;
    std::string error;
    if (!store.ReadState(*parent, previous)) return state.Error("recovery-parent-state-missing");
    if (!ApplyRecoveryRequest(request, policy, *parent, previous, next, error)) {
        return state.DoS(100, false, REJECT_INVALID, error);
    }
    return true;
}

bool ConnectRecoveryBlock(const CBlock& block, const CBlockIndex& index, CValidationState& state)
{
    if (!RecoveryProtocolEnabled()) return true;
    RecoveryRequest request;
    bool found = false;
    for (const auto& tx : block.vtx) {
        if (tx->nVersion != 3 || tx->nType != TRANSACTION_LLMQ_RECOVERY) continue;
        if (found) return state.DoS(100, false, REJECT_INVALID, "bad-recovery-duplicate");
        if (!GetTxPayload(*tx, request)) return state.DoS(100, false, REJECT_INVALID, "bad-recovery-payload");
        found = true;
    }
    RecoveryStateStore store(*evoDb, GetRecoveryPolicy());
    std::string error;
    // TestBlockValidity uses an index without phashBlock. Bind its temporary
    // state to the actual candidate hash; the caller's DB transaction rolls back.
    const auto hash = block.GetHash();
    CBlockIndex candidate = index;
    candidate.phashBlock = &hash;
    if (!store.ConnectBlock(candidate, found ? &request : nullptr, error)) {
        if (error == "recovery-parent-state-missing" || error == "recovery-state-conflict" ||
            error == "recovery-parent" || error == "recovery-invalid-policy" || error == "recovery-disabled") {
            return state.Error(error); // local state/configuration failure, not peer misconduct
        }
        return state.DoS(100, false, REJECT_INVALID, error);
    }
    return true;
}

bool DisconnectRecoveryBlock(const CBlockIndex& index)
{
    if (!RecoveryProtocolEnabled()) return true;
    RecoveryStateStore store(*evoDb, GetRecoveryPolicy());
    return store.DisconnectBlock(index);
}

} // namespace llmq
