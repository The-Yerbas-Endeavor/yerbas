// Copyright (c) 2026 The Yerbas developers
// Distributed under the MIT software license, see COPYING.
#include "quorums_pose.h"
#include "quorums_utils.h"
#include "rpc/server.h"
#include "smartnode/smartnode-sync.h"
#include "util.h"
#include "validation.h"
#include "netmessagemaker.h"

#include <set>

namespace llmq {
CPoSeManager* poseManager{nullptr};
static const std::string CERT_DB = "pose_cert_v1";

uint256 PoSeStateHash(const CDeterministicMNState& state)
{
    CHashWriter h(SER_GETHASH, 0);
    h << state.addr << state.pubKeyOperator.Get() << state.nRegisteredHeight << state.nPoSeRevivedHeight;
    return h.GetHash();
}
bool CheckPoSeWindow(int height, int tip, int lifetime)
{
    return height >= POSE_WINDOW && height % POSE_WINDOW == 0 &&
           height <= tip && int64_t(tip) - height <= lifetime;
}
uint256 CPoSeRequest::GetId() const
{
    CHashWriter h(SER_GETHASH, 0);
    h << std::string("yerbas-pose-request-v1") << Params().GetConsensus().hashGenesisBlock
      << target << height << blockHash << stateHash;
    return h.GetHash();
}
uint256 CPoSeRequest::GetSignHash() const
{
    CHashWriter h(SER_GETHASH, 0);
    h << std::string("yerbas-pose-unresponsive-v1") << GetId();
    return h.GetHash();
}
uint256 CPoSeReport::GetSignHash() const
{
    CHashWriter h(SER_GETHASH, 0);
    h << std::string("yerbas-pose-observation-v1") << request.GetSignHash() << observer;
    return h.GetHash();
}
bool VerifyPoSeCertificateSignature(const CPoSeCertificate& cert, Consensus::LLMQType type,
                                   const CBLSPublicKey& quorumKey)
{
    return cert.signature.IsValid() && quorumKey.IsValid() &&
           cert.signature.VerifyInsecure(quorumKey, CLLMQUtils::BuildSignHash(
               type, cert.quorumHash, cert.request.GetId(), cert.request.GetSignHash()));
}
static std::set<std::string> MonitorKeys()
{
    std::set<std::string> keys;
    for (const auto& hex : gArgs.GetArgs("-posemonitorpubkey")) {
        CBLSPublicKey key;
        if (!key.SetHexStr(hex)) throw std::runtime_error("Invalid posemonitorpubkey");
        keys.insert(key.ToString());
    }
    return keys;
}
static bool Fail(std::string& error, const char* reason)
{
    error = reason;
    return false;
}
bool CPoSeManager::ValidateRequest(const CPoSeRequest& r, int lifetime, std::string& error) const
{
    AssertLockHeld(cs_main);
    const auto& consensus = Params().GetConsensus();
    if (!consensus.IsLLMQEnabled(consensus.llmqTypePoSe, r.height))
        return Fail(error, "PoSe quorum is not activated");
    if (!CheckPoSeWindow(r.height, chainActive.Height(), lifetime))
        return Fail(error, "Invalid, future, or expired observation window");
    if (chainActive[r.height]->GetBlockHash() != r.blockHash)
        return Fail(error, "Observation is not on the active chain");
    auto historical = deterministicMNManager->GetListForBlock(chainActive[r.height]).GetMN(r.target);
    auto current = deterministicMNManager->GetListAtChainTip().GetMN(r.target);
    if (!historical || !current || historical->pdmnState->nPoSeBanHeight != -1 || current->pdmnState->nPoSeBanHeight != -1)
        return Fail(error, "Unknown or already banned smartnode");
    if (PoSeStateHash(*historical->pdmnState) != r.stateHash || PoSeStateHash(*current->pdmnState) != r.stateHash)
        return Fail(error, "Smartnode service, operator, or revival state changed");
    // Reports cover three probes at window-20, window-10 and window.
    auto start = deterministicMNManager->GetListForBlock(chainActive[r.height - 20]).GetMN(r.target);
    if (!start || PoSeStateHash(*start->pdmnState) != r.stateHash)
        return Fail(error, "Smartnode changed during observation window");
    return true;
}
CPoSeRequest CPoSeManager::MakeRequest(const uint256& target, int height) const
{
    LOCK(cs_main);
    if (!CheckPoSeWindow(height, chainActive.Height(), POSE_REPORT_LIFETIME))
        throw std::runtime_error("Invalid observation window");
    auto mn = deterministicMNManager->GetListForBlock(chainActive[height]).GetMN(target);
    if (!mn) throw std::runtime_error("Unknown smartnode");
    CPoSeRequest r;
    r.target = target; r.height = height;
    r.blockHash = chainActive[height]->GetBlockHash();
    r.stateHash = PoSeStateHash(*mn->pdmnState);
    std::string error;
    if (!ValidateRequest(r, POSE_REPORT_LIFETIME, error)) throw std::runtime_error(error);
    return r;
}
void CPoSeManager::Prune()
{
    for (auto it = pending.begin(); it != pending.end();) {
        std::string error;
        if (it->second.empty() || !ValidateRequest(it->second.front().request, POSE_REPORT_LIFETIME, error))
            it = pending.erase(it);
        else ++it;
    }
}
template <typename T>
static void Relay(CConnman* connman, const char* command, const T& payload)
{
    if (!connman) return;
    connman->ForEachNode([&](CNode* node) {
        connman->PushMessage(node, CNetMsgMaker(node->GetSendVersion()).Make(command, payload));
    });
}
bool CPoSeManager::SubmitReport(const CPoSeReport& report, std::string& error, CConnman* connman)
{
    {
        LOCK(cs_main);
        if (IsInitialBlockDownload() || !smartnodeSync.IsSynced()) return Fail(error, "Node is not synced");
        if (!ValidateRequest(report.request, POSE_REPORT_LIFETIME, error)) return false;
        const auto keys = MonitorKeys();
        if (!report.observer.IsValid() || !keys.count(report.observer.ToString()))
            return Fail(error, "Observer is not in the local evidence allowlist");
        if (!report.signature.IsValid() || !report.signature.VerifyInsecure(report.observer, report.GetSignHash()))
            return Fail(error, "Invalid observer signature");
        LOCK(cs);
        Prune();
        const auto id = report.request.GetId();
        auto it = pending.find(id);
        if (it == pending.end() && pending.size() >= POSE_MAX_PENDING)
            return Fail(error, "Pending evidence limit reached");
        auto& reports = pending[id];
        for (const auto& old : reports) if (old.observer == report.observer) return true;
        // Bound storage even if the allowlist is configured with many keys.
        if (reports.size() >= 16) return Fail(error, "Observer limit reached");
        reports.push_back(report);
    }
    Relay(connman, "posereport", report);
    return true;
}
bool CPoSeManager::Approve(const uint256& id, std::string& error)
{
    LOCK(cs_main);
    if (IsInitialBlockDownload() || !smartnodeSync.IsSynced()) return Fail(error, "Node is not synced");
    CPoSeRequest request;
    {
        LOCK(cs);
        Prune();
        auto it = pending.find(id);
        if (it == pending.end()) return Fail(error, "No current evidence for this request");
        const auto keys = MonitorKeys();
        size_t trusted = 0;
        for (const auto& report : it->second) trusted += keys.count(report.observer.ToString());
        if (trusted < POSE_MIN_MONITORS) return Fail(error, "At least three distinct trusted monitors are required");
        request = it->second.front().request;
    }
    if (!ValidateRequest(request, POSE_REPORT_LIFETIME, error)) return false;
    const auto type = Params().GetConsensus().llmqTypePoSe;
    auto quorum = quorumSigningManager->SelectQuorumForSigning(type, request.height, id);
    if (!quorum) return Fail(error, "No eligible PoSe quorum; evidence remains pending");
    // No automatic signing on receipt of an official report. The operator must
    // explicitly approve after independently reviewing the reported outage.
    if (!quorumSigningManager->AsyncSignIfMember(type, id, request.GetSignHash(), true, request.height))
        return Fail(error, "This node cannot sign for the selected PoSe quorum");
    CRecoveredSig recovered;
    if (quorumSigningManager->GetRecoveredSigForId(type, id, recovered)) HandleNewRecoveredSig(recovered);
    return true;
}
bool CPoSeManager::SubmitCertificate(const CPoSeCertificate& cert, std::string& error, CConnman* connman)
{
    {
        LOCK(cs_main);
        if (IsInitialBlockDownload() || !smartnodeSync.IsSynced()) return Fail(error, "Node is not synced");
        if (!ValidateRequest(cert.request, POSE_CERT_LIFETIME, error)) return false;
        auto type = Params().GetConsensus().llmqTypePoSe;
        auto quorum = quorumSigningManager->SelectQuorumForSigning(type, cert.request.height, cert.request.GetId());
        if (!quorum || quorum->qc.quorumHash != cert.quorumHash)
            return Fail(error, "Certificate uses the wrong or unavailable quorum");
        if (!VerifyPoSeCertificateSignature(cert, type, quorum->qc.quorumPublicKey))
            return Fail(error, "Invalid PoSe quorum signature");
        LOCK(cs);
        CPoSeCertificate old;
        const auto key = std::make_pair(CERT_DB, cert.request.target);
        std::string oldError;
        if (db.Read(key, old) && ValidateRequest(old.request, POSE_CERT_LIFETIME, oldError) &&
            old.request.height >= cert.request.height) return true;
        // Only a verified quorum certificate is persisted. This is DKG policy,
        // never a direct mutation of the deterministic smartnode list.
        db.Write(key, cert);
    }
    Relay(connman, "posecert", cert);
    return true;
}
bool CPoSeManager::ShouldVoteBad(const uint256& target)
{
    LOCK(cs_main);
    if (IsInitialBlockDownload()) return false;
    CPoSeCertificate cert;
    {
        LOCK(cs);
        if (!db.Read(std::make_pair(CERT_DB, target), cert)) return false;
    }
    std::string error;
    if (!ValidateRequest(cert.request, POSE_CERT_LIFETIME, error)) return false;
    // Recheck quorum ancestry after reorgs, including across process restarts.
    auto type = Params().GetConsensus().llmqTypePoSe;
    auto quorum = quorumSigningManager->SelectQuorumForSigning(type, cert.request.height, cert.request.GetId());
    return quorum && quorum->qc.quorumHash == cert.quorumHash &&
           VerifyPoSeCertificateSignature(cert, type, quorum->qc.quorumPublicKey);
}
void CPoSeManager::HandleNewRecoveredSig(const CRecoveredSig& sig)
{
    if (sig.llmqType != Params().GetConsensus().llmqTypePoSe) return;
    CPoSeCertificate cert;
    {
        LOCK(cs);
        auto it = pending.find(sig.id);
        if (it == pending.end() || it->second.empty()) return;
        cert.request = it->second.front().request;
    }
    if (cert.request.GetSignHash() != sig.msgHash) return;
    cert.quorumHash = sig.quorumHash; cert.signature = sig.sig.Get();
    std::string error;
    SubmitCertificate(cert, error, g_connman.get());
}
void CPoSeManager::ProcessMessage(CNode* from, const std::string& command, CDataStream& data, CConnman& connman)
{
    if (command != "posereport" && command != "posecert") return;
    if (data.size() > 512) return;
    {
        LOCK(cs);
        const int64_t now = GetTime();
        for (auto it = peerRate.begin(); it != peerRate.end();) {
            if (now - it->second.first >= 60) it = peerRate.erase(it); else ++it;
        }
        if (!peerRate.count(from->GetId()) && peerRate.size() >= 256) return;
        auto& rate = peerRate[from->GetId()];
        if (rate.first == 0) rate.first = now;
        if (++rate.second > 32) return;
    }
    std::string error;
    try {
        if (command == "posereport") {
            CPoSeReport report; data >> report;
            if (!data.empty()) return;
            SubmitReport(report, error, &connman);
        } else {
            CPoSeCertificate cert; data >> cert;
            if (!data.empty()) return;
            SubmitCertificate(cert, error, &connman);
        }
    } catch (const std::exception&) {
        // Malformed or locally untrusted observations never ban a smartnode.
    }
}
std::string CPoSeManager::GetCertificate(const uint256& target)
{
    LOCK(cs);
    CPoSeCertificate cert;
    if (!db.Read(std::make_pair(CERT_DB, target), cert)) throw std::runtime_error("No certificate for target");
    CDataStream stream(SER_NETWORK, PROTOCOL_VERSION); stream << cert;
    return HexStr(stream.begin(), stream.end());
}
UniValue CPoSeManager::Status()
{
    LOCK(cs_main);
    LOCK(cs);
    Prune();
    const auto& consensus = Params().GetConsensus();
    UniValue result(UniValue::VOBJ), items(UniValue::VARR);
    result.pushKV("active", UniValue(consensus.IsLLMQEnabled(consensus.llmqTypePoSe, chainActive.Height())));
    result.pushKV("quorumType", int(consensus.llmqTypePoSe));
    result.pushKV("activationHeight", consensus.nPoSeQuorumActivationHeight);
    result.pushKV("minimumMonitors", int(POSE_MIN_MONITORS));
    result.pushKV("approvalMode", "explicit quorum-member approval; monitors cannot authorize bans");
    for (const auto& entry : pending) {
        UniValue item(UniValue::VOBJ);
        const auto& r = entry.second.front().request;
        item.pushKV("id", entry.first.ToString()); item.pushKV("target", r.target.ToString());
        item.pushKV("height", r.height); item.pushKV("observers", int(entry.second.size()));
        item.pushKV("blockHash", r.blockHash.ToString()); item.pushKV("stateHash", r.stateHash.ToString());
        UniValue observers(UniValue::VARR);
        for (const auto& report : entry.second) observers.push_back(report.observer.ToString());
        item.pushKV("observerPublicKeys", observers);
        item.pushKV("quorumAvailable", UniValue(bool(quorumSigningManager->SelectQuorumForSigning(consensus.llmqTypePoSe, r.height, entry.first))));
        items.push_back(item);
    }
    result.pushKV("pending", items);
    return result;
}
template <typename T> static std::string Encode(const T& value)
{
    CDataStream s(SER_NETWORK, PROTOCOL_VERSION); s << value;
    return HexStr(s.begin(), s.end());
}
template <typename T> static T Decode(const UniValue& value)
{
    const auto hex = value.get_str();
    if (hex.size() > 1024 || !IsHex(hex)) throw std::runtime_error("Invalid PoSe payload");
    CDataStream s(ParseHex(hex), SER_NETWORK, PROTOCOL_VERSION);
    T result; s >> result;
    if (!s.empty()) throw std::runtime_error("Trailing PoSe payload data");
    return result;
}
UniValue PoSeRPC(const JSONRPCRequest& rpc)
{
    if (rpc.fHelp || rpc.params.empty()) throw std::runtime_error(
        "pose status | request target height | createreport target height | submitreport hex | approve id | getcertificate target | submitcertificate hex\n"
        "Monitor reports require three failed authenticated probes over 20 blocks, at height-20, height-10, height.\n"
        "createreport uses posemonitorprivkey from the configuration file; it attests to those observations.\n"
        "approve is an explicit quorum operator decision after independent review, never an observer action.\n"
        "Pending reports expire after 120 blocks; quorum certificates expire after 1440 blocks.\n"
        "Only a quorum certificate affects subsequent DKG votes; penalties require mined commitments.\n");
    try {
        auto command = rpc.params[0].get_str();
        if (command == "status" && rpc.params.size() == 1) return poseManager->Status();
        if (command == "request" && rpc.params.size() == 3) {
            auto request = poseManager->MakeRequest(ParseHashV(rpc.params[1], "target"), ParseInt32V(rpc.params[2], "height"));
            UniValue result(UniValue::VOBJ);
            result.pushKV("id", request.GetId().ToString()); result.pushKV("height", request.height);
            result.pushKV("blockHash", request.blockHash.ToString()); result.pushKV("stateHash", request.stateHash.ToString());
            return result;
        }
        if (command == "createreport" && rpc.params.size() == 3) {
            CPoSeReport report;
            report.request = poseManager->MakeRequest(ParseHashV(rpc.params[1], "target"), ParseInt32V(rpc.params[2], "height"));
            CBLSSecretKey key;
            if (!key.SetHexStr(gArgs.GetArg("-posemonitorprivkey", ""))) throw std::runtime_error("No valid evidence monitor key configured");
            report.observer = key.GetPublicKey(); report.signature = key.Sign(report.GetSignHash());
            UniValue result(UniValue::VOBJ);
            result.pushKV("id", report.request.GetId().ToString()); result.pushKV("hex", Encode(report));
            return result;
        }
        if (command == "getcertificate" && rpc.params.size() == 2)
            return poseManager->GetCertificate(ParseHashV(rpc.params[1], "target"));
        std::string error;
        bool ok = false;
        if (command == "submitreport" && rpc.params.size() == 2)
            ok = poseManager->SubmitReport(Decode<CPoSeReport>(rpc.params[1]), error, g_connman.get());
        else if (command == "submitcertificate" && rpc.params.size() == 2)
            ok = poseManager->SubmitCertificate(Decode<CPoSeCertificate>(rpc.params[1]), error, g_connman.get());
        else if (command == "approve" && rpc.params.size() == 2)
            ok = poseManager->Approve(ParseHashV(rpc.params[1], "id"), error);
        else throw std::runtime_error("Unknown pose command or invalid argument count");
        if (!ok) throw std::runtime_error(error);
        return true;
    } catch (const std::exception& e) {
        throw JSONRPCError(RPC_INVALID_PARAMETER, e.what());
    }
}
}
