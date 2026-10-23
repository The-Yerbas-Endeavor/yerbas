// Copyright (c) 2026 The Yerbas developers
// Distributed under the MIT software license, see COPYING.
#include "quorums_recovery.h"
#include "quorums_pose.h"
#include "quorums_commitment.h"
#include "quorums_utils.h"
#include "smartnode/activesmartnode.h"
#include "evo/evodb.h"
#include "evo/specialtx.h"
#include "evo/providertx.h"
#include "consensus/validation.h"
#include "rpc/server.h"
#include "core_io.h"
#include "validation.h"
#include "util.h"
#include <algorithm>

namespace llmq {
static const std::string DB_RECOVERY = "pose_recovery_v2";
static const std::string DB_ACTIVITY = "pose_activity_v2";
static const std::string DB_ROSTER = "pose_roster_v2";
uint256 CRecoveryRoster::GetHash(const Consensus::Params& p) const {
    CHashWriter h(SER_GETHASH, 0);
    h << std::string("yerbas-recovery-roster-v2") << p.hashGenesisBlock << *this;
    return h.GetHash();
}
CRecoveryRoster GetRecoveryRoster(const uint256& id) {
    CRecoveryRoster roster;
    if (id.IsNull()) return roster;
    if (!evoDb->Read(std::make_pair(DB_ROSTER,id),roster) || roster.GetHash(Params().GetConsensus())!=id)
        throw std::runtime_error("Missing or invalid recovery roster; reindex required");
    return roster;
}
bool HasRecoveryParticipation(const std::vector<CRecoveryParticipation>& history,
                             const CRecoveryMember& member, int cutoff) {
    std::set<int> opportunities, successes;
    for (const auto& event : history) {
        if (event.member.proTxHash != member.proTxHash || event.member.stateHash != member.stateHash ||
            event.member.key != member.key || event.session <= cutoff-RECOVERY_HISTORY || event.session > cutoff) continue;
        opportunities.insert(event.session);
        if (event.signedValid) successes.insert(event.session);
    }
    return successes.size() >= 3 && successes.size()*5 >= opportunities.size()*4 &&
        *successes.rbegin()-*successes.begin() >= 120 && cutoff-*successes.rbegin() <= 360;
}
std::vector<CRecoveryMember> RankRecoveryMembers(std::vector<CRecoveryMember> candidates, const uint256& seed) {
    auto score = [&](const CRecoveryMember& member) {
        CHashWriter h(SER_GETHASH,0);
        h << std::string("yerbas-recovery-rank-v2") << seed << member.proTxHash;
        return h.GetHash();
    };
    std::sort(candidates.begin(),candidates.end(),[&](const auto& a,const auto& b){
        auto sa=score(a), sb=score(b);
        return sa==sb ? a.proTxHash<b.proTxHash : sa<sb;
    });
    // Do not lower the threshold or choose a partial committee.
    if (candidates.size()<RECOVERY_SIZE) candidates.clear();
    else candidates.resize(RECOVERY_SIZE);
    return candidates;
}
static CRecoveryRoster SelectRecoveryRoster(const CBlockIndex* index) {
    CRecoveryRoster roster;
    roster.height=index->nHeight;
    roster.cutoff=index->nHeight-60;
    const auto& p=Params().GetConsensus();
    if (roster.cutoff < p.nPoSeQuorumActivationHeight || roster.cutoff<0) return roster;
    auto snapshot=index->GetAncestor(roster.cutoff);
    roster.cutoffHash=snapshot->GetBlockHash();
    // Eligibility is frozen 30 blocks before the seed, and the seed matures for
    // another 30 blocks before selection. This limits, but does not eliminate,
    // miner influence over block-derived randomness.
    CHashWriter seed(SER_GETHASH,0);
    seed << std::string("yerbas-recovery-seed-v2") << p.hashGenesisBlock
         << roster.cutoffHash << index->GetAncestor(index->nHeight-30)->GetBlockHash();
    roster.seed=seed.GetHash();
    std::map<uint256,std::vector<CRecoveryParticipation>> history;
    for (auto walk=snapshot; walk && walk->nHeight>roster.cutoff-RECOVERY_HISTORY &&
             p.IsLLMQEnabled(Consensus::LLMQ_100_67,walk->nHeight); walk=walk->pprev) {
        std::vector<CRecoveryParticipation> events;
        if (!evoDb->Read(std::make_pair(DB_ACTIVITY,walk->GetBlockHash()),events))
            throw std::runtime_error("Missing recovery participation history; reindex required");
        for (auto& event:events) history[event.member.proTxHash].push_back(std::move(event));
    }
    auto list=deterministicMNManager->GetListForBlock(snapshot);
    std::vector<CRecoveryMember> candidates;
    list.ForEachMN(true,roster.cutoff,[&](const CDeterministicMNCPtr& mn){
        const auto& state=*mn->pdmnState;
        if (state.confirmedHash.IsNull() || int64_t(roster.cutoff)-state.nRegisteredHeight<RECOVERY_AGE ||
            (state.nPoSeRevivedHeight>=0 && int64_t(roster.cutoff)-state.nPoSeRevivedHeight<RECOVERY_AGE)) return;
        CRecoveryMember member{mn->proTxHash,PoSeStateHash(state),state.pubKeyOperator.Get()};
        if (HasRecoveryParticipation(history[member.proTxHash],member,roster.cutoff)) candidates.push_back(member);
    });
    roster.qualified=candidates.size();
    roster.members=RankRecoveryMembers(std::move(candidates),roster.seed);
    return roster;
}
bool RecoveryEnabled(const Consensus::Params& p, int height) {
    return p.nRecoveryActivationHeight != std::numeric_limits<int>::max() &&
        height >= p.nRecoveryActivationHeight &&
        p.IsLLMQEnabled(Consensus::LLMQ_100_67, height);
}
uint256 CRecoveryCertificate::SignHash(const Consensus::Params& p) const {
    CHashWriter h(SER_GETHASH, 0);
    h << std::string("yerbas-recovery-penalty66-v2") << p.hashGenesisBlock << version
      << committee << epoch << target << stateHash << startHash << endHash << start << end << expiry;
    return h.GetHash();
}
bool CRecoveryCertificate::VerifySignatures(const Consensus::Params& p, const CRecoveryRoster& roster) const {
    if (version != 2 || committee != roster.GetHash(p) || roster.members.size()!=RECOVERY_SIZE ||
        signatures.size()<RECOVERY_THRESHOLD || signatures.size()>RECOVERY_SIZE) return false;
    std::set<uint256> registrations;
    std::set<std::string> keys;
    for (const auto& member:roster.members) {
        if (!member.key.IsValid() || !registrations.insert(member.proTxHash).second ||
            !keys.insert(member.key.ToString()).second) return false;
    }
    int last=-1;
    for (const auto& sig:signatures) {
        if (sig.first<=last || sig.first>=RECOVERY_SIZE) return false;
        last=sig.first;
        if (!sig.second.IsValid() || !sig.second.VerifyInsecure(roster.members[sig.first].key,SignHash(p))) return false;
    }
    return true;
}
void CRecoveryState::Advance(int h, const uint256& hash, bool closed, bool success, int eligible, int interval) {
    if (mode == 1 && int64_t(h) >= int64_t(trigger) + 6 * interval - 1) {
        mode = 2; failures = successes = 0;
    }
    if (!closed) return;
    if (mode == 0) {
        failures = success ? 0 : failures + 1;
        if (failures == 3) {
            mode = 1; trigger = h; epoch = hash; budget = std::min(10, eligible / 10);
            consumed.clear(); successes = 0; frozenRoster = scheduledRoster;
        }
    } else {
        successes = success ? successes + 1 : 0;
        if (successes == 2) { mode = 0; failures = successes = 0; }
    }
}
CRecoveryState GetRecoveryState(const CBlockIndex* index) {
    CRecoveryState s;
    if (!index || !RecoveryEnabled(Params().GetConsensus(), index->nHeight)) return s;
    if (!evoDb->Read(std::make_pair(DB_RECOVERY, index->GetBlockHash()), s))
        throw std::runtime_error("Missing recovery consensus state; reindex required");
    return s;
}
static bool Reject(CValidationState& s, const char* reason) {
    return s.DoS(100, false, REJECT_INVALID, reason);
}
static bool CheckCertificate(const CRecoveryCertificate& c, const CBlockIndex* prev, CValidationState& state) {
    const auto& p = Params().GetConsensus();
    if (!prev || !RecoveryEnabled(p, prev->nHeight + 1)) return Reject(state, "bad-recovery-disabled");
    auto s = GetRecoveryState(prev);
    int h = prev->nHeight + 1;
    int64_t deadline = int64_t(s.trigger) + 6 * p.llmqs.at(Consensus::LLMQ_100_67).dkgInterval;
    if (s.mode != 1 || h >= deadline || c.epoch != s.epoch) return Reject(state, "bad-recovery-epoch");
    if (s.consumed.count(c.target) || int(s.consumed.size()) >= s.budget) return Reject(state, "bad-recovery-budget");
    if (c.start <= s.trigger || c.end < c.start || int64_t(c.end) - c.start < 20 || c.end > prev->nHeight ||
        c.expiry != std::min(int64_t(c.end) + 30, deadline - 1) || h > c.expiry)
        return Reject(state, "bad-recovery-window");
    if (prev->GetAncestor(c.start)->GetBlockHash() != c.startHash || prev->GetAncestor(c.end)->GetBlockHash() != c.endHash)
        return Reject(state, "bad-recovery-branch");
    // Check every observation block, not just endpoints: changing an address away
    // and back must not reuse evidence collected for a different service identity.
    for (int i = c.start; i <= prev->nHeight; ++i) {
        auto mn = deterministicMNManager->GetListForBlock(prev->GetAncestor(i)).GetMN(c.target);
        if (!mn || mn->pdmnState->nPoSeBanHeight != -1 || PoSeStateHash(*mn->pdmnState) != c.stateHash)
            return Reject(state, "bad-recovery-target");
    }
    auto roster=GetRecoveryRoster(s.frozenRoster);
    if (roster.members.size()!=RECOVERY_SIZE || c.committee!=s.frozenRoster)
        return Reject(state,"bad-recovery-roster");
    auto current=deterministicMNManager->GetListForBlock(prev);
    for (const auto& sig:c.signatures) {
        if (sig.first>=roster.members.size()) return Reject(state,"bad-recovery-signatures");
        const auto& member=roster.members[sig.first];
        auto mn=current.GetMN(member.proTxHash);
        if (!mn || !current.IsMNValid(mn,prev->nHeight) || PoSeStateHash(*mn->pdmnState)!=member.stateHash)
            return Reject(state,"bad-recovery-member");
    }
    if (!c.VerifySignatures(p,roster)) return Reject(state, "bad-recovery-signatures");
    return true;
}
bool CheckRecoveryTx(const CTransaction& tx, const CBlockIndex* prev, CValidationState& state) {
    CRecoveryCertificate c;
    if (tx.nVersion != 3) return Reject(state, "bad-recovery-version");
    if (tx.vExtraPayload.size() > 2048 || !GetTxPayload(tx, c)) return Reject(state, "bad-recovery-payload");
    return CheckCertificate(c, prev, state);
}
bool CheckRecoveryBlock(const CBlock& block, const CBlockIndex* prev, CValidationState& state) {
    const CTransaction* recovery = nullptr;
    for (const auto& tx : block.vtx) {
        if (!tx || tx->nType != TRANSACTION_RECOVERY_PENALTY) continue;
        if (recovery) return Reject(state, "bad-recovery-block-limit");
        recovery = tx.get();
    }
    if (!recovery) return true;
    if (!CheckRecoveryTx(*recovery, prev, state)) return false;
    CRecoveryCertificate c; GetTxPayload(*recovery, c);
    auto mn = deterministicMNManager->GetListForBlock(prev).GetMN(c.target);
    for (const auto& tx : block.vtx) {
        if (!tx) continue;
        for (const auto& in : tx->vin) if (in.prevout == mn->collateralOutpoint) return Reject(state, "bad-recovery-target-spent");
        uint256 target;
        if (tx->nType == TRANSACTION_PROVIDER_UPDATE_SERVICE) { CProUpServTx v; if (GetTxPayload(*tx,v)) target=v.proTxHash; }
        if (tx->nType == TRANSACTION_PROVIDER_UPDATE_REGISTRAR) { CProUpRegTx v; if (GetTxPayload(*tx,v)) target=v.proTxHash; }
        if (tx->nType == TRANSACTION_PROVIDER_UPDATE_REVOKE) { CProUpRevTx v; if (GetTxPayload(*tx,v)) target=v.proTxHash; }
        if (target == c.target) return Reject(state, "bad-recovery-target-change");
        if (tx->nType == TRANSACTION_PROVIDER_REGISTER) {
            CProRegTx v;
            if (GetTxPayload(*tx,v) && v.collateralOutpoint == mn->collateralOutpoint) return Reject(state, "bad-recovery-target-replaced");
        }
    }
    return true;
}
void ProcessRecoveryBlock(const CBlock& block, const CBlockIndex* index) {
    const auto& p = Params().GetConsensus();
    if (!p.IsLLMQEnabled(Consensus::LLMQ_100_67,index->nHeight)) return;
    auto s = GetRecoveryState(index->pprev);
    const auto& q = p.llmqs.at(Consensus::LLMQ_100_67);
    int offset = index->nHeight % q.dkgInterval;
    if (offset == 0) s.sessionCommitted = false;
    std::vector<CRecoveryParticipation> events;
    for (const auto& tx : block.vtx) {
        if (tx->nType == TRANSACTION_QUORUM_COMMITMENT) {
            CFinalCommitmentTxPayload qc;
            if (GetTxPayload(*tx,qc) && !qc.commitment.IsNull()) {
                if (qc.commitment.llmqType==Consensus::LLMQ_100_67) s.sessionCommitted=true;
                // Production quorum commitments authenticate each credited operator
                // through membersSig. Null commitments provide no individual evidence.
                auto type=qc.commitment.llmqType;
                if (type>=Consensus::LLMQ_50_60 && type<=Consensus::LLMQ_100_67) {
                    auto quorumIndex=mapBlockIndex.at(qc.commitment.quorumHash);
                    auto list=deterministicMNManager->GetListForBlock(quorumIndex);
                    auto modifier=SerializeHash(std::make_pair(Consensus::LLMQType(type),qc.commitment.quorumHash));
                    auto members=list.CalculateQuorum(qc.commitment.validMembers.size(),modifier);
                    for (size_t i=0;i<members.size();++i) {
                        const auto& mn=members[i];
                        CRecoveryParticipation event;
                        event.member={mn->proTxHash,PoSeStateHash(*mn->pdmnState),mn->pdmnState->pubKeyOperator.Get()};
                        event.session=quorumIndex->nHeight;
                        event.signedValid=qc.commitment.validMembers[i] && qc.commitment.signers[i];
                        events.push_back(event);
                    }
                }
            }
        }
        if (tx->nType == TRANSACTION_RECOVERY_PENALTY) {
            CRecoveryCertificate c; GetTxPayload(*tx,c); s.consumed.insert(c.target);
        }
    }
    evoDb->Write(std::make_pair(DB_ACTIVITY,index->GetBlockHash()),events);
    // Index participation during the PoSe warm-up, before RC authority activates.
    if (!RecoveryEnabled(p,index->nHeight)) return;
    if (index->nHeight%RECOVERY_ROTATION==0 || !RecoveryEnabled(p,index->nHeight-1)) {
        auto roster=SelectRecoveryRoster(index);
        s.scheduledRoster=roster.GetHash(p);
        evoDb->Write(std::make_pair(DB_ROSTER,s.scheduledRoster),roster);
    }
    bool closed = offset == q.dkgMiningWindowEnd && index->nHeight - offset >= p.nRecoveryActivationHeight;
    int eligible=0;
    deterministicMNManager->GetListForBlock(index).ForEachMN(true,index->nHeight,
        [&](const CDeterministicMNCPtr&){++eligible;});
    s.Advance(index->nHeight, index->GetBlockHash(), closed, s.sessionCommitted, eligible, q.dkgInterval);
    evoDb->Write(std::make_pair(DB_RECOVERY,index->GetBlockHash()),s);
}
void UndoRecoveryBlock(const CBlockIndex* index) {
    if (RecoveryEnabled(Params().GetConsensus(),index->nHeight) && (index->nHeight%RECOVERY_ROTATION==0 || !RecoveryEnabled(Params().GetConsensus(),index->nHeight-1))) {
        auto s=GetRecoveryState(index);
        evoDb->Erase(std::make_pair(DB_ROSTER,s.scheduledRoster));
    }
    evoDb->Erase(std::make_pair(DB_ACTIVITY,index->GetBlockHash()));
    evoDb->Erase(std::make_pair(DB_RECOVERY,index->GetBlockHash()));
}

template <typename T> static std::string EncodeRecovery(const T& v) {
    CDataStream stream(SER_NETWORK, PROTOCOL_VERSION); stream << v;
    return HexStr(stream.begin(), stream.end());
}
UniValue RecoveryRPC(const JSONRPCRequest& request) {
    if (request.fHelp || request.params.empty()) throw std::runtime_error(
        "recovery status | request target start end | sign certificate | merge certificate signedcertificate | maketx certificate\n"
        "Sign only after independent reachability checks. Uses the active smartnode operator key.\n"
        "maketx returns an unfunded transaction; fundrawtransaction and signrawtransaction before submission.\n");
    LOCK(cs_main);
    try {
        const auto& p = Params().GetConsensus();
        auto tip = chainActive.Tip(); auto state = GetRecoveryState(tip);
        auto command = request.params[0].get_str();
        if (command == "status" && request.params.size() == 1) {
            UniValue ret(UniValue::VOBJ);
            ret.pushKV("enabled", UniValue(tip && RecoveryEnabled(p,tip->nHeight)));
            ret.pushKV("activationHeight",p.nRecoveryActivationHeight);
            ret.pushKV("mode", state.mode == 1 ? "recovery" : state.mode == 2 ? "locked" : "normal");
            ret.pushKV("failures",state.failures); ret.pushKV("successes",state.successes);
            ret.pushKV("triggerHeight",state.trigger); ret.pushKV("epoch",state.epoch.ToString());
            ret.pushKV("budget",state.budget); ret.pushKV("consumed",int(state.consumed.size()));
            auto roster=GetRecoveryRoster(state.mode==1 ? state.frozenRoster : state.scheduledRoster);
            ret.pushKV("committeeHash",(state.mode==1 ? state.frozenRoster : state.scheduledRoster).ToString());
            ret.pushKV("committeeSize",int(RECOVERY_SIZE)); ret.pushKV("threshold",int(RECOVERY_THRESHOLD));
            ret.pushKV("qualified",roster.qualified); ret.pushKV("selectionHeight",roster.height);
            ret.pushKV("snapshotHeight",roster.cutoff);
            auto current=deterministicMNManager->GetListForBlock(tip);
            int available=0;
            for (const auto& member:roster.members) {
                auto mn=current.GetMN(member.proTxHash);
                if (mn && current.IsMNValid(mn,tip->nHeight) && PoSeStateHash(*mn->pdmnState)==member.stateHash) ++available;
            }
            ret.pushKV("eligibleSigners",available);
            ret.pushKV("canAuthorize",UniValue(state.mode==1 && roster.members.size()==RECOVERY_SIZE && available>=int(RECOVERY_THRESHOLD)));
            UniValue members(UniValue::VARR);
            for (const auto& member:roster.members) {
                UniValue value(UniValue::VOBJ);
                value.pushKV("proTxHash",member.proTxHash.ToString()); value.pushKV("operatorPublicKey",member.key.ToString());
                members.push_back(value);
            }
            ret.pushKV("members",members);
            return ret;
        }
        if (command == "request" && request.params.size() == 4) {
            CRecoveryCertificate c;
            c.target = ParseHashV(request.params[1],"target");
            if (!ParseInt32(request.params[2].get_str(), &c.start) || !ParseInt32(request.params[3].get_str(), &c.end) ||
                c.start <= state.trigger || c.start < 0 || c.end < c.start || c.end > chainActive.Height() || state.mode != 1)
                throw std::runtime_error("Invalid recovery observation heights or inactive committee");
            auto roster=GetRecoveryRoster(state.frozenRoster);
            if (roster.members.size()!=RECOVERY_SIZE) throw std::runtime_error("Insufficient qualified smartnodes for RC");
            c.committee=state.frozenRoster; c.epoch=state.epoch;
            c.startHash=chainActive[c.start]->GetBlockHash(); c.endHash=chainActive[c.end]->GetBlockHash();
            auto mn=deterministicMNManager->GetListForBlock(tip).GetMN(c.target);
            if (!mn) throw std::runtime_error("Unknown smartnode");
            c.stateHash=PoSeStateHash(*mn->pdmnState);
            c.expiry=std::min(int64_t(c.end)+30,int64_t(state.trigger)+6*p.llmqs.at(Consensus::LLMQ_100_67).dkgInterval-1);
            return EncodeRecovery(c);
        }
        auto decode = [](const UniValue& value) {
            const auto hex=value.get_str(); CRecoveryCertificate c;
            if (hex.size()>4096 || !IsHex(hex) || !GetTxPayload(ParseHex(hex),c)) throw std::runtime_error("Invalid recovery certificate");
            return c;
        };
        if (request.params.size()<2) throw std::runtime_error("Missing certificate");
        auto c=decode(request.params[1]);
        if (command=="sign" && request.params.size()==2) {
            if (!fSmartnodeMode || activeSmartnodeInfo.proTxHash.IsNull() || !activeSmartnodeInfo.blsKeyOperator)
                throw std::runtime_error("Signing requires an active registered smartnode");
            auto roster=GetRecoveryRoster(state.frozenRoster);
            const auto& key=*activeSmartnodeInfo.blsKeyOperator;
            auto it=std::find_if(roster.members.begin(),roster.members.end(),[&](const auto& member){
                return member.proTxHash==activeSmartnodeInfo.proTxHash && member.key==key.GetPublicKey();
            });
            if (it==roster.members.end()) throw std::runtime_error("Smartnode is not in the selected RC");
            auto current=deterministicMNManager->GetListForBlock(tip);
            auto signer=current.GetMN(it->proTxHash);
            if (!signer || !current.IsMNValid(signer,tip->nHeight) || PoSeStateHash(*signer->pdmnState)!=it->stateHash)
                throw std::runtime_error("Selected smartnode is no longer eligible to sign");
            if (c.version!=2 || c.committee!=state.frozenRoster) throw std::runtime_error("Wrong recovery roster or version");
            // Refuse stale/invalid requests before signing, independently of threshold.
            auto saved=c.signatures;
            c.signatures.clear();
            CValidationState check;
            CheckCertificate(c,tip,check);
            if (check.GetRejectReason()!="bad-recovery-signatures") throw std::runtime_error("Invalid recovery request: "+check.GetRejectReason());
            c.signatures=std::move(saved);
            uint8_t id=std::distance(roster.members.begin(),it);
            for (const auto& sig:c.signatures) if (sig.first==id) throw std::runtime_error("Already signed");
            c.signatures.emplace_back(id,key.Sign(c.SignHash(p)));
            std::sort(c.signatures.begin(),c.signatures.end(),[](const auto& a,const auto& b){return a.first<b.first;});
            return EncodeRecovery(c);
        }
        if (command=="merge" && request.params.size()==3) {
            auto other=decode(request.params[2]);
            if (c.SignHash(p)!=other.SignHash(p)) throw std::runtime_error("Different recovery requests");
            std::map<uint8_t,CBLSSignature> sigs;
            for (const auto& sig:c.signatures) sigs.emplace(sig);
            for (const auto& sig:other.signatures) sigs.emplace(sig);
            c.signatures.assign(sigs.begin(),sigs.end());
            if (c.signatures.size()>RECOVERY_SIZE) throw std::runtime_error("Too many signers");
            return EncodeRecovery(c);
        }
        if (command=="maketx" && request.params.size()==2) {
            CValidationState check;
            if (!CheckCertificate(c,tip,check)) throw std::runtime_error(check.GetRejectReason());
            CMutableTransaction tx; tx.nVersion=3; tx.nType=TRANSACTION_RECOVERY_PENALTY;
            // A zero-valued data output permits the normal wallet funding path.
            tx.vout.emplace_back(0,CScript()<<OP_RETURN);
            SetTxPayload(tx,c); return EncodeHexTx(CTransaction(tx));
        }
        throw std::runtime_error("Unknown recovery command or arguments");
    } catch (const std::exception& e) { throw JSONRPCError(RPC_INVALID_PARAMETER,e.what()); }
}
}
