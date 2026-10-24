// Copyright (c) 2026 The Yerbas developers
// Distributed under the MIT software license, see COPYING.
#ifndef YERBAS_QUORUMS_POSE_H
#define YERBAS_QUORUMS_POSE_H

#include "llmq/quorums_signing.h"
#include <map>

class JSONRPCRequest;
namespace llmq {
// Monitoring claims are policy input, never consensus evidence of unreachability.
// Approvals are explicit local RPC actions by quorum operators.
static constexpr int POSE_WINDOW = 30;
static constexpr int POSE_REPORT_LIFETIME = 120;
static constexpr int POSE_CERT_LIFETIME = 1440;
static constexpr size_t POSE_MIN_MONITORS = 3;
static constexpr size_t POSE_MAX_PENDING = 256;

struct CPoSeRequest {
    uint256 target;
    int32_t height{0};
    uint256 blockHash;
    uint256 stateHash;
    ADD_SERIALIZE_METHODS;
    template <typename Stream, typename Operation>
    void SerializationOp(Stream& s, Operation ser_action) {
        READWRITE(target); READWRITE(height); READWRITE(blockHash); READWRITE(stateHash);
    }
    uint256 GetId() const;
    uint256 GetSignHash() const;
};
struct CPoSeReport {
    CPoSeRequest request;
    CBLSPublicKey observer;
    CBLSSignature signature;
    ADD_SERIALIZE_METHODS;
    template <typename Stream, typename Operation>
    void SerializationOp(Stream& s, Operation ser_action) {
        READWRITE(request); READWRITE(observer); READWRITE(signature);
    }
    uint256 GetSignHash() const;
};
struct CPoSeCertificate {
    CPoSeRequest request;
    uint256 quorumHash;
    CBLSSignature signature;
    ADD_SERIALIZE_METHODS;
    template <typename Stream, typename Operation>
    void SerializationOp(Stream& s, Operation ser_action) {
        READWRITE(request); READWRITE(quorumHash); READWRITE(signature);
    }
};
uint256 PoSeStateHash(const CDeterministicMNState& state);
bool CheckPoSeWindow(int height, int tip, int lifetime);
bool VerifyPoSeCertificateSignature(const CPoSeCertificate& cert, Consensus::LLMQType type,
                                  const CBLSPublicKey& quorumKey);

class CPoSeManager : public CRecoveredSigsListener {
    CDBWrapper& db;
    CCriticalSection cs;
    std::map<uint256, std::vector<CPoSeReport>> pending;
    std::map<NodeId, std::pair<int64_t, int>> peerRate;
    bool ValidateRequest(const CPoSeRequest& request, int lifetime, std::string& error) const;
    void Prune(); // caller holds cs_main, then cs
public:
    explicit CPoSeManager(CDBWrapper& dbIn) : db(dbIn) {}
    CPoSeRequest MakeRequest(const uint256& target, int height) const;
    bool SubmitReport(const CPoSeReport& report, std::string& error, CConnman* connman);
    bool SubmitCertificate(const CPoSeCertificate& cert, std::string& error, CConnman* connman);
    bool Approve(const uint256& id, std::string& error);
    UniValue Status();
    std::string GetCertificate(const uint256& target);
    bool ShouldVoteBad(const uint256& target);
    void ProcessMessage(CNode* from, const std::string& command, CDataStream& data, CConnman& connman);
    void HandleNewRecoveredSig(const CRecoveredSig& sig) override;
};
extern CPoSeManager* poseManager;
UniValue PoSeRPC(const JSONRPCRequest& request);
}
#endif
