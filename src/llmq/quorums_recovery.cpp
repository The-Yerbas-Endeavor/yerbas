// Copyright (c) 2026 The Yerbas developers
// Distributed under the MIT software license, see the accompanying COPYING file.
#include "quorums_recovery.h"

#include <algorithm>

#include "chain.h"
#include "base58.h"
#include "chainparams.h"
#include "consensus/validation.h"
#include "consensus/merkle.h"
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
           policy.maxStartDelay > 0 && policy.maxAnchorAge >= 0 && policy.minAnchorHeight >= 0 &&
           policy.activationHeight >= 0 && (policy.activationHeight == 0 ||
           (policy.activationHeight % policy.dkgInterval == 0 &&
            policy.legacyAnchorHeight >= 0 && policy.legacyAnchorHeight < policy.activationHeight &&
            !policy.legacyAnchorHash.IsNull()));
}
bool MatchesLegacyAnchor(const RecoveryPolicy& policy, const CBlockIndex& block)
{
    const auto* genesis = block.GetAncestor(0);
    if (!genesis || genesis->GetBlockHash() != policy.genesisHash) return false;
    if (policy.activationHeight == 0) return true;
    const auto* anchor = block.GetAncestor(policy.legacyAnchorHeight);
    return anchor && anchor->GetBlockHash() == policy.legacyAnchorHash;
}
const std::string RECOVERY_STATE_KEY = "llmq_recovery_state_v2";
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
    if (int64_t(parent.nHeight) + 1 < policy.activationHeight) return reject("recovery-before-activation");
    if ((request.version != 1 && request.version != 2) || ((policy.activationHeight > 0 || policy.activationByRecord) && request.version != 2))
        return reject("recovery-version");
    if (request.genesisHash != policy.genesisHash) return reject("recovery-network");
    const auto genesis = parent.GetAncestor(0);
    if (!genesis || genesis->GetBlockHash() != policy.genesisHash) return reject("recovery-branch-network");
    if (!MatchesLegacyAnchor(policy, parent)) return reject("recovery-legacy-anchor");
    if (request.previousAuthorization != previous.lastAuthorization) return reject("recovery-sequence");
    if (request.anchorHeight < std::max(policy.minAnchorHeight, policy.activationHeight - 1) || request.anchorHeight > parent.nHeight ||
        int64_t(parent.nHeight) - request.anchorHeight > policy.maxAnchorAge) {
        return reject("recovery-anchor-height");
    }
    const auto anchor = parent.GetAncestor(request.anchorHeight);
    if (!anchor || anchor->GetBlockHash() != request.anchorHash) return reject("recovery-anchor");
    const bool first = policy.activationByRecord && previous.cutoverHeight == 0;
    if (first && (request.endHeight != 0 || request.startHeight % 720 != 0))
        return reject("recovery-first-cutover");
    // The record is included at parent+1. The earliest affected quorum must
    // start later, so its parameters never depend on transactions in itself.
    if (int64_t(request.startHeight) <= int64_t(parent.nHeight) + 1 ||
        int64_t(request.startHeight) - parent.nHeight > (first ? 750 : policy.maxStartDelay) ||
        request.startHeight % policy.dkgInterval != 0) return reject("recovery-window");
    if (request.version == 1) {
        if (request.endHeight % policy.dkgInterval != 0 ||
            request.endHeight <= request.startHeight ||
            int64_t(request.endHeight) - request.startHeight > policy.maxDuration)
            return reject("recovery-window");
        if (previous.startHeight > 0 && previous.endHeight == 0)
            return reject("recovery-window-outstanding");
        if (request.startHeight < previous.endHeight) return reject("recovery-overlap");
        if (parent.nHeight < previous.endHeight) return reject("recovery-window-outstanding");
    } else {
        // Manual records are future ON (end=0) or OFF (end=start).
        // Never overwrite a pending transition or a bounded legacy window.
        if (request.endHeight != 0 && request.endHeight != request.startHeight)
            return reject("recovery-manual-action");
        if (previous.startHeight > parent.nHeight ||
            (previous.endHeight > 0 && previous.endHeight > parent.nHeight))
            return reject("recovery-window-outstanding");
        const bool open = previous.startHeight > 0 && previous.endHeight == 0;
        if ((request.endHeight == 0) == open) return reject("recovery-manual-state");
    }
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
    accepted.cutoverHeight = first ? request.startHeight : previous.cutoverHeight;
    accepted.lastAuthorization = hash;
    accepted.startHeight = request.version == 2 && request.endHeight != 0 ? previous.startHeight : request.startHeight;
    accepted.endHeight = request.endHeight;
    next = accepted;
    error.clear();
    return true;
}

bool RecoveryStateStore::ReadState(const CBlockIndex& block, RecoveryState& state) const
{
    if (!policy.enabled || !ValidPolicy(policy)) return false;
    if (policy.activationHeight > 0) {
        if (block.nHeight < policy.activationHeight - 1 || !MatchesLegacyAnchor(policy, block)) return false;
        if (block.nHeight == policy.activationHeight - 1) {
            state = RecoveryState{};
            return true; // virtual bootstrap only; never synthesize missing later state
        }
    }
    if (policy.activationHeight == 0 && block.nHeight == 0 && block.GetBlockHash() == policy.genesisHash) {
        state = RecoveryState{};
        return true;
    }
    if (policy.activationHeight == 0 && block.nHeight == 1 && !policy.bootstrapBlockHash.IsNull() && block.GetBlockHash() == policy.bootstrapBlockHash) {
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
    if (block.nHeight < policy.activationHeight) {
        error = "recovery-before-activation";
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
         existing.endHeight != next.endHeight || existing.cutoverHeight != next.cutoverHeight)) {
        error = "recovery-state-conflict";
        return false;
    }
    db.Write(std::make_pair(RECOVERY_STATE_KEY, block.GetBlockHash()), next);
    error.clear();
    return true;
}

bool RecoveryStateStore::DisconnectBlock(const CBlockIndex& block)
{
    if (!policy.enabled || !ValidPolicy(policy) || !block.pprev || block.nHeight < policy.activationHeight) return false;
    const auto key = std::make_pair(RECOVERY_STATE_KEY, block.GetBlockHash());
    if (!db.Exists(key)) return false;
    db.Erase(key);
    return true;
}

bool MigrateLegacyRecoveryHistory(CEvoDB& db, const RecoveryPolicy& policy,
    const CBlockIndex& tip,
    const std::function<bool(CBlock&, const CBlockIndex*)>& readBlock,
    const std::function<bool()>& interrupted,
    const std::function<void(int)>& progress, std::string& error)
{
    auto reject = [&](const char* reason) { error = reason; return false; };
    if (!policy.enabled || !policy.activationByRecord || !ValidPolicy(policy))
        return reject("Recovery history migration requires the transaction-selected policy.");
    std::vector<const CBlockIndex*> chain(tip.nHeight + 1);
    for (auto* index = &tip; index; index = index->pprev) chain[index->nHeight] = index;
    if (chain.empty() || !chain[0] || chain[0]->GetBlockHash() != policy.genesisHash)
        return reject("Recovery history migration has an inconsistent chain.");
    RecoveryStateStore store(db, policy);
    const std::string checkpointKey = "llmq_recovery_migration_v2";
    std::pair<int, uint256> checkpoint;
    int start = 1;
    if (db.Read(checkpointKey, checkpoint) && checkpoint.first > 0 && checkpoint.first <= tip.nHeight &&
        chain[checkpoint.first] && chain[checkpoint.first]->GetBlockHash() == checkpoint.second) {
        RecoveryState state;
        if (store.ReadState(*chain[checkpoint.first], state) && state.lastAuthorization.IsNull() &&
            state.startHeight == 0 && state.endHeight == 0 && state.cutoverHeight == 0)
            start = checkpoint.first + 1;
    }
    progress(start - 1);
    // Bounded batches and a branch-bound checkpoint make an interrupted upgrade
    // resumable without trusting a missing state entry or an unscanned prefix.
    for (int first = start; first <= tip.nHeight;) {
        auto transaction = db.BeginTransaction();
        const int last = int(std::min<int64_t>(tip.nHeight, int64_t(first) + 999));
        for (int height = first; height <= last; ++height) {
            if (interrupted()) return reject("Recovery history indexing interrupted; restart to resume.");
            const auto* index = chain[height];
            CBlock block;
            if (!index || !readBlock(block, index) || block.GetHash() != index->GetBlockHash())
                return reject("Recovery history indexing needs unavailable or unreadable historical blocks. Restore the blocks or resync; do not assume recovery is OFF.");
            bool mutated = false;
            if (BlockMerkleRoot(block, &mutated) != block.hashMerkleRoot || mutated)
                return reject("Recovery history indexing found damaged block transactions. Restore the blocks or resync.");
            for (const auto& tx : block.vtx) {
                if (tx->nVersion == 3 && tx->nType == TRANSACTION_LLMQ_RECOVERY)
                    return reject("Existing signed recovery records require validation with -reindex-chainstate (or -reindex); automatic legacy migration stopped.");
            }
            if (!store.ConnectBlock(*index, nullptr, error)) return false;
        }
        db.Write(checkpointKey, std::make_pair(last, chain[last]->GetBlockHash()));
        transaction->Commit();
        if (!db.CommitRootTransaction()) return reject("Could not save recovery history migration progress.");
        progress(last);
        first = last + 1;
    }
    error.clear();
    return true;
}

bool RecoveryProtocolEnabled()
{
    return Params().GetConsensus().fLLMQRecoveryByRecord || Params().GetConsensus().nLLMQRecoveryHeight >= 0 ||
        (Params().NetworkIDString() == CBaseChainParams::REGTEST && gArgs.GetBoolArg("-llmqrecoverytest", false)) ||
        (Params().NetworkIDString() == CBaseChainParams::DEVNET && gArgs.GetBoolArg("-llmqrecoverydevnet", false));
}

bool RecoveryUsesRecordedParams(int height, const CBlockIndex* branch)
{
    if (Params().GetConsensus().fLLMQRecoveryByRecord) {
        LOCK(cs_main);
        if (!branch) branch = chainActive.Tip();
        if (!branch) return false;
        // The first record predates its effective height. Use this branch's
        // parent state, never the active tip's authorization for another fork.
        const auto* parent = height > 0 && height <= branch->nHeight
            ? branch->GetAncestor(height - 1) : branch;
        RecoveryState state;
        return parent && RecoveryStateStore(*evoDb, GetRecoveryPolicy()).ReadState(*parent, state) &&
            state.cutoverHeight > 0 && height >= state.cutoverHeight;
    }
    if (!RecoveryProtocolEnabled()) return false;
    const int cutover = Params().GetConsensus().nLLMQRecoveryHeight;
    return cutover < 0 || height >= cutover;
}

bool RecoveryLegacyQuorumRetired(int quorumHeight, int signingHeight)
{
    int cutover = Params().GetConsensus().nLLMQRecoveryHeight;
    if (Params().GetConsensus().fLLMQRecoveryByRecord) {
        LOCK(cs_main);
        const auto* index = chainActive[signingHeight];
        RecoveryState state;
        if (!index || !RecoveryStateStore(*evoDb, GetRecoveryPolicy()).ReadState(*index, state)) return true;
        cutover = state.cutoverHeight > 0 ? state.cutoverHeight : -1;
    }
    return cutover >= 0 && quorumHeight < cutover && signingHeight >= cutover;
}

RecoveryPolicy GetRecoveryPolicy()
{
    RecoveryPolicy policy;
    if (!RecoveryProtocolEnabled()) return policy;
    policy.enabled = true;
    policy.activationByRecord = Params().GetConsensus().fLLMQRecoveryByRecord;
    policy.genesisHash = Params().GenesisBlock().GetHash();
    // Isolated regtest fixtures may use a fresh authority instead of a
    // source-embedded test key, matching the spork manager's test override.
    const auto addresses = Params().NetworkIDString() == CBaseChainParams::REGTEST && gArgs.IsArgSet("-sporkaddr")
        ? gArgs.GetArgs("-sporkaddr") : Params().SporkAddresses();
    for (const auto& address : addresses) {
        CKeyID id;
        if (!CBitcoinAddress(address).GetKeyID(id)) return RecoveryPolicy{};
        policy.authorities.emplace(id);
    }
    policy.requiredSignatures = Params().MinSporkKeys();
    // Later type-1 transitions use the existing 30-block schedule.
    policy.dkgInterval = 30;
    policy.maxDuration = 60;
    policy.maxStartDelay = 60;
    policy.maxAnchorAge = policy.activationByRecord ? 750 : 60;
    if (Params().NetworkIDString() == CBaseChainParams::DEVNET) {
        policy.maxDuration = 90;
        policy.minAnchorHeight = 1; // bind every record to this named devnet, not the shared base genesis
        policy.bootstrapBlockHash = Params().GetConsensus().hashDevnetGenesisBlock;
    }
    if (Params().GetConsensus().nLLMQRecoveryHeight >= 0) {
        policy.activationHeight = Params().GetConsensus().nLLMQRecoveryHeight;
        policy.legacyAnchorHeight = 0;
        policy.legacyAnchorHash = policy.genesisHash;
    } else if (Params().NetworkIDString() == CBaseChainParams::REGTEST) {
        policy.activationHeight = gArgs.GetArg("-llmqrecoveryactivationheight", 0);
        policy.legacyAnchorHeight = 0;
        policy.legacyAnchorHash = policy.genesisHash;
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
    if (Params().GetConsensus().fLLMQRecoveryByRecord) {
        const auto* parent = height > 0 && height <= branch->nHeight
            ? branch->GetAncestor(height - 1) : branch;
        RecoveryState state;
        // Missing historical state is not evidence of a legacy prefix.
        if (!parent || !RecoveryStateStore(*evoDb, GetRecoveryPolicy()).ReadState(*parent, state)) return false;
    }
    if (!RecoveryUsesRecordedParams(height, branch)) {
        out = it->second; // Existing legacy validation below the release boundary.
        return true;
    }
    Consensus::LLMQParams schedule = it->second;
    const bool testnet = Params().NetworkIDString() == CBaseChainParams::TESTNET;
    RecoveryDynamicParams(type, 0, false, testnet, schedule);
    const int start = height - height % schedule.dkgInterval;
    const auto* parent = branch->GetAncestor(start > 0 ? start - 1 : 0);
    if (!parent) return false;
    RecoveryState state;
    const auto policy = GetRecoveryPolicy();
    // Deferred-activation regtest uses the deterministic normal fixture profile
    // before cutover. This is NOT a resolver for unrecorded public-network history.
    if (start >= policy.activationHeight && !RecoveryStateStore(*evoDb, policy).ReadState(*parent, state)) return false;
    const auto list = deterministicMNManager->GetListForBlock(parent);
    if (!RecoveryDynamicParams(type, list.GetAllMNsCount(), state.IsLowAt(start), testnet, out))
        out = it->second; // Fixed types retain their network-specific configuration.
    return true;
}

bool ResolveRecoveryQuorumParams(Consensus::LLMQType type, const CBlockIndex* quorum, Consensus::LLMQParams& out)
{
    if (!quorum || !ResolveRecoveryParamsAtHeight(type, quorum, quorum->nHeight, out)) return false;
    return quorum->nHeight % out.dkgInterval == 0;
}

bool RecoveryQuorumCanSign(Consensus::LLMQType type, const CBlockIndex* quorum, int signingHeight)
{
    if (!RecoveryProtocolEnabled()) return true;
    LOCK(cs_main);
    if (!quorum || RecoveryLegacyQuorumRetired(quorum->nHeight, signingHeight)) return false;
    if (!RecoveryUsesRecordedParams(quorum->nHeight, quorum)) return true;
    if (type != Consensus::LLMQ_50_60) return true;
    if (quorum->nHeight < GetRecoveryPolicy().activationHeight) return true;
    RecoveryState state;
    if (!RecoveryStateStore(*evoDb, GetRecoveryPolicy()).ReadState(quorum->pprev ? *quorum->pprev : *quorum, state)) return false;
    if (!state.IsLowAt(quorum->nHeight)) return true;
    if (!state.AllowsRecoverySigning(quorum->nHeight, signingHeight)) return false;
    // An open-ended authorization needs the state at signing height too: an
    // OFF record closes it, and a later ON must not revive the old low quorum.
    if (state.endHeight == 0) {
        const CBlockIndex* signingIndex = chainActive[signingHeight];
        RecoveryState current;
        if (!signingIndex || !RecoveryStateStore(*evoDb, GetRecoveryPolicy()).ReadState(*signingIndex, current)) return false;
        return current.startHeight == state.startHeight && current.IsLowAt(signingHeight);
    }
    return true;
}

bool CheckRecoveryTransaction(const CTransaction& tx, const CBlockIndex* parent, CValidationState& state)
{
    if (!RecoveryProtocolEnabled()) return state.DoS(10, false, REJECT_INVALID, "bad-tx-type-check");
    RecoveryRequest request;
    if (!parent || !GetTxPayload(tx, request)) return state.DoS(100, false, REJECT_INVALID, "bad-recovery-payload");
    const auto policy = GetRecoveryPolicy();
    if (int64_t(parent->nHeight) + 1 < policy.activationHeight)
        return state.DoS(100, false, REJECT_INVALID, "recovery-before-activation");
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
    if (index.nHeight < GetRecoveryPolicy().activationHeight) {
        for (const auto& tx : block.vtx) {
            if (tx->nVersion == 3 && tx->nType == TRANSACTION_LLMQ_RECOVERY)
                return state.DoS(100, false, REJECT_INVALID, "recovery-before-activation");
        }
        return true;
    }
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
    if (!RecoveryProtocolEnabled() || index.nHeight < GetRecoveryPolicy().activationHeight) return true;
    RecoveryStateStore store(*evoDb, GetRecoveryPolicy());
    return store.DisconnectBlock(index);
}

} // namespace llmq
