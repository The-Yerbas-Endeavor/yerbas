// Copyright (c) 2017-2020 The Dash Core developers
// Copyright (c) 2020 The Yerbas developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include "chainparams.h"
#include "core_io.h"
#include "txmempool.h"
#include <limits>
#ifdef ENABLE_WALLET
#include "wallet/rpcwallet.h"
#include "wallet/wallet.h"
#endif
#include "server.h"
#include "validation.h"
#include "base58.h"
#include "evo/evodb.h"
#include "evo/specialtx.h"
#include "llmq/quorums_recovery.h"

#include "llmq/quorums.h"
#include "llmq/quorums_blockprocessor.h"
#include "llmq/quorums_debug.h"
#include "llmq/quorums_dkgsession.h"
#include "llmq/quorums_signing.h"

void quorum_list_help()
{
    throw std::runtime_error(
            "quorum list ( count )\n"
            "List of on-chain quorums\n"
            "\nArguments:\n"
            "1. count           (number, optional) Number of quorums to list. Will list active quorums\n"
            "                   if \"count\" is not specified.\n"
            "\nResult:\n"
            "{\n"
            "  \"quorumName\" : [                    (array of strings) List of quorum hashes per some quorum type.\n"
            "     \"quorumHash\"                     (string) Quorum hash. Note: most recent quorums come first.\n"
            "     ,...\n"
            "  ],\n"
            "}\n"
            "\nExamples:\n"
            + HelpExampleCli("quorum", "list")
            + HelpExampleCli("quorum", "list 10")
            + HelpExampleRpc("quorum", "list, 10")
    );
}

UniValue quorum_list(const JSONRPCRequest& request)
{
    if (request.fHelp || (request.params.size() != 1 && request.params.size() != 2))
        quorum_list_help();

    LOCK(cs_main);

    int count = -1;
    if (request.params.size() > 1) {
        count = ParseInt32V(request.params[1], "count");
        if (count < 0) {
            throw JSONRPCError(RPC_INVALID_PARAMETER, "count can't be negative");
        }
    }

    UniValue ret(UniValue::VOBJ);

    for (auto& p : Params().GetConsensus().llmqs) {
        UniValue v(UniValue::VARR);

        auto quorums = llmq::quorumManager->ScanQuorums(p.first, chainActive.Tip(), count > -1 ? count : p.second.signingActiveQuorumCount);
        for (auto& q : quorums) {
            v.push_back(q->qc.quorumHash.ToString());
        }

        ret.push_back(Pair(p.second.name, v));
    }


    return ret;
}

void quorum_info_help()
{
    throw std::runtime_error(
            "quorum info llmqType \"quorumHash\" ( includeSkShare )\n"
            "Return information about a quorum\n"
            "\nArguments:\n"
            "1. llmqType              (int, required) LLMQ type.\n"
            "2. \"quorumHash\"          (string, required) Block hash of quorum.\n"
            "3. includeSkShare        (boolean, optional) Include secret key share in output.\n"
    );
}

UniValue BuildQuorumInfo(const llmq::CQuorumCPtr& quorum, bool includeMembers, bool includeSkShare)
{
    UniValue ret(UniValue::VOBJ);

    ret.push_back(Pair("height", quorum->pindexQuorum->nHeight));
    ret.push_back(Pair("type", quorum->params.name));
    ret.push_back(Pair("quorumHash", quorum->qc.quorumHash.ToString()));
    ret.push_back(Pair("minedBlock", quorum->minedBlockHash.ToString()));

    if (includeMembers) {
        UniValue membersArr(UniValue::VARR);
        for (size_t i = 0; i < quorum->members.size(); i++) {
            auto& dmn = quorum->members[i];
            UniValue mo(UniValue::VOBJ);
            mo.push_back(Pair("proTxHash", dmn->proTxHash.ToString()));
            mo.push_back(Pair("pubKeyOperator", dmn->pdmnState->pubKeyOperator.Get().ToString()));
            mo.push_back(Pair("valid", quorum->qc.validMembers[i]));
            if (quorum->qc.validMembers[i]) {
                CBLSPublicKey pubKey = quorum->GetPubKeyShare(i);
                if (pubKey.IsValid()) {
                    mo.push_back(Pair("pubKeyShare", pubKey.ToString()));
                }
            }
            membersArr.push_back(mo);
        }

        ret.push_back(Pair("members", membersArr));
    }
    ret.push_back(Pair("quorumPublicKey", quorum->qc.quorumPublicKey.ToString()));
    CBLSSecretKey skShare = quorum->GetSkShare();
    if (includeSkShare && skShare.IsValid()) {
        ret.push_back(Pair("secretKeyShare", skShare.ToString()));
    }
    return ret;
}

UniValue quorum_info(const JSONRPCRequest& request)
{
    if (request.fHelp || (request.params.size() != 3 && request.params.size() != 4))
        quorum_info_help();

    LOCK(cs_main);

    Consensus::LLMQType llmqType = (Consensus::LLMQType)ParseInt32V(request.params[1], "llmqType");
    if (!Params().GetConsensus().llmqs.count(llmqType)) {
        throw JSONRPCError(RPC_INVALID_PARAMETER, "invalid LLMQ type");
    }

    const auto& llmqParams = Params().GetConsensus().llmqs.at(llmqType);

    uint256 quorumHash = ParseHashV(request.params[2], "quorumHash");
    bool includeSkShare = false;
    if (request.params.size() > 3) {
        includeSkShare = ParseBoolV(request.params[3], "includeSkShare");
    }

    auto quorum = llmq::quorumManager->GetQuorum(llmqType, quorumHash);
    if (!quorum) {
        throw JSONRPCError(RPC_INVALID_PARAMETER, "quorum not found");
    }

    return BuildQuorumInfo(quorum, true, includeSkShare);
}

void quorum_dkgstatus_help()
{
    throw std::runtime_error(
            "quorum dkgstatus ( detail_level )\n"
            "Return the status of the current DKG process.\n"
            "Works only when SPORK_17_QUORUM_DKG_ENABLED spork is ON.\n"
            "\nArguments:\n"
            "1. detail_level         (number, optional, default=0) Detail level of output.\n"
            "                        0=Only show counts. 1=Show member indexes. 2=Show member's ProTxHashes.\n"
    );
}

UniValue quorum_dkgstatus(const JSONRPCRequest& request)
{
    if (request.fHelp || (request.params.size() < 1 || request.params.size() > 2)) {
        quorum_dkgstatus_help();
    }

    int detailLevel = 0;
    if (request.params.size() > 1) {
        detailLevel = ParseInt32V(request.params[1], "detail_level");
        if (detailLevel < 0 || detailLevel > 2) {
            throw JSONRPCError(RPC_INVALID_PARAMETER, "invalid detail_level");
        }
    }

    llmq::CDKGDebugStatus status;
    llmq::quorumDKGDebugManager->GetLocalDebugStatus(status);

    auto ret = status.ToJson(detailLevel);

    LOCK(cs_main);
    int tipHeight = chainActive.Height();

    UniValue minableCommitments(UniValue::VOBJ);
    for (const auto& p : Params().GetConsensus().llmqs) {
        auto& params = p.second;
        llmq::CFinalCommitment fqc;
        if (llmq::quorumBlockProcessor->GetMinableCommitment(params.type, tipHeight, fqc)) {
            UniValue obj(UniValue::VOBJ);
            fqc.ToJson(obj);
            minableCommitments.push_back(Pair(params.name, obj));
        }
    }

    ret.push_back(Pair("minableCommitments", minableCommitments));

    return ret;
}

void quorum_memberof_help()
{
    throw std::runtime_error(
            "quorum memberof \"proTxHash\" (quorumCount)\n"
            "Checks which quorums the given smartnode is a member of.\n"
            "\nArguments:\n"
            "1. \"proTxHash\"                (string, required) ProTxHash of the smartnode.\n"
            "2. scanQuorumsCount           (number, optional) Number of quorums to scan for. If not specified,\n"
            "                              the active quorum count for each specific quorum type is used."
    );
}

UniValue quorum_memberof(const JSONRPCRequest& request)
{
    if (request.fHelp || (request.params.size() < 2 || request.params.size() > 3)) {
        quorum_memberof_help();
    }

    uint256 protxHash = ParseHashV(request.params[1], "proTxHash");
    int scanQuorumsCount = -1;
    if (request.params.size() >= 3) {
        scanQuorumsCount = ParseInt32V(request.params[2], "scanQuorumsCount");
        if (scanQuorumsCount <= 0) {
            throw JSONRPCError(RPC_INVALID_PARAMETER, "invalid scanQuorumsCount parameter");
        }
    }

    const CBlockIndex* pindexTip;
    {
        LOCK(cs_main);
        pindexTip = chainActive.Tip();
    }

    auto mnList = deterministicMNManager->GetListForBlock(pindexTip);
    auto dmn = mnList.GetMN(protxHash);
    if (!dmn) {
        throw JSONRPCError(RPC_INVALID_PARAMETER, "smartnode not found");
    }

    UniValue result(UniValue::VARR);

    for (const auto& p : Params().GetConsensus().llmqs) {
        auto& params = p.second;
        size_t count = params.signingActiveQuorumCount;
        if (scanQuorumsCount != -1) {
            count = (size_t)scanQuorumsCount;
        }
        auto quorums = llmq::quorumManager->ScanQuorums(params.type, count);
        for (auto& quorum : quorums) {
            if (quorum->IsMember(dmn->proTxHash)) {
                auto json = BuildQuorumInfo(quorum, false, false);
                json.push_back(Pair("isValidMember", quorum->IsValidMember(dmn->proTxHash)));
                json.push_back(Pair("memberIndex", quorum->GetMemberIndex(dmn->proTxHash)));
                result.push_back(json);
            }
        }
    }

    return result;
}

void quorum_sign_help()
{
    throw std::runtime_error(
            "quorum sign llmqType \"id\" \"msgHash\"\n"
            "Threshold-sign a message\n"
            "\nArguments:\n"
            "1. llmqType              (int, required) LLMQ type.\n"
            "2. \"id\"                  (string, required) Request id.\n"
            "3. \"msgHash\"             (string, required) Message hash.\n"
    );
}

void quorum_hasrecsig_help()
{
    throw std::runtime_error(
            "quorum hasrecsig llmqType \"id\" \"msgHash\"\n"
            "Test if a valid recovered signature is present\n"
            "\nArguments:\n"
            "1. llmqType              (int, required) LLMQ type.\n"
            "2. \"id\"                  (string, required) Request id.\n"
            "3. \"msgHash\"             (string, required) Message hash.\n"
    );
}

void quorum_getrecsig_help()
{
    throw std::runtime_error(
            "quorum getrecsig llmqType \"id\" \"msgHash\"\n"
            "Get a recovered signature\n"
            "\nArguments:\n"
            "1. llmqType              (int, required) LLMQ type.\n"
            "2. \"id\"                  (string, required) Request id.\n"
            "3. \"msgHash\"             (string, required) Message hash.\n"
    );
}

void quorum_isconflicting_help()
{
    throw std::runtime_error(
            "quorum isconflicting llmqType \"id\" \"msgHash\"\n"
            "Test if a conflict exists\n"
            "\nArguments:\n"
            "1. llmqType              (int, required) LLMQ type.\n"
            "2. \"id\"                  (string, required) Request id.\n"
            "3. \"msgHash\"             (string, required) Message hash.\n"
    );
}

UniValue quorum_sigs_cmd(const JSONRPCRequest& request)
{
    auto cmd = request.params[0].get_str();
    if (request.fHelp || (request.params.size() != 4)) {
        if (cmd == "sign") {
            quorum_sign_help();
        } else if (cmd == "hasrecsig") {
            quorum_hasrecsig_help();
        } else if (cmd == "getrecsig") {
            quorum_getrecsig_help();
        } else if (cmd == "isconflicting") {
            quorum_isconflicting_help();
        } else {
            // shouldn't happen as it's already handled by the caller
            throw JSONRPCError(RPC_INVALID_PARAMETER, "invalid cmd");
        }
    }

    Consensus::LLMQType llmqType = (Consensus::LLMQType)ParseInt32V(request.params[1], "llmqType");
    if (!Params().GetConsensus().llmqs.count(llmqType)) {
        throw JSONRPCError(RPC_INVALID_PARAMETER, "invalid LLMQ type");
    }

    uint256 id = ParseHashV(request.params[2], "id");
    uint256 msgHash = ParseHashV(request.params[3], "msgHash");

    if (cmd == "sign") {
        return llmq::quorumSigningManager->AsyncSignIfMember(llmqType, id, msgHash);
    } else if (cmd == "hasrecsig") {
        return llmq::quorumSigningManager->HasRecoveredSig(llmqType, id, msgHash);
    } else if (cmd == "getrecsig") {
        llmq::CRecoveredSig recSig;
        if (!llmq::quorumSigningManager->GetRecoveredSigForId(llmqType, id, recSig)) {
            throw JSONRPCError(RPC_INVALID_PARAMETER, "recovered signature not found");
        }
        if (recSig.msgHash != msgHash) {
            throw JSONRPCError(RPC_INVALID_PARAMETER, "recovered signature not found");
        }
        return recSig.ToJson();
    } else if (cmd == "isconflicting") {
        return llmq::quorumSigningManager->IsConflicting(llmqType, id, msgHash);
    } else {
        // shouldn't happen as it's already handled by the caller
        throw JSONRPCError(RPC_INVALID_PARAMETER, "invalid cmd");
    }
}

void quorum_dkgsimerror_help()
{
    throw std::runtime_error(
            "quorum dkgsimerror \"type\" rate\n"
            "This enables simulation of errors and malicious behaviour in the DKG. Do NOT use this on mainnet\n"
            "as you will get yourself very likely PoSe banned for this.\n"
            "\nArguments:\n"
            "1. \"type\"                (string, required) Error type.\n"
            "2. rate                  (number, required) Rate at which to simulate this error type.\n"
    );
}

UniValue quorum_dkgsimerror(const JSONRPCRequest& request)
{
    auto cmd = request.params[0].get_str();
    if (request.fHelp || (request.params.size() != 3)) {
        quorum_dkgsimerror_help();
    }

    std::string type = request.params[1].get_str();
    double rate = ParseDoubleV(request.params[2], "rate");

    if (rate < 0 || rate > 1) {
        throw JSONRPCError(RPC_INVALID_PARAMETER, "invalid rate. Must be between 0 and 1");
    }

    llmq::SetSimulatedDKGErrorRate(type, rate);

    return UniValue();
}


[[ noreturn ]] void quorum_help()
{
    throw std::runtime_error(
            "quorum \"command\" ...\n"
            "Set of commands for quorums/LLMQs.\n"
            "To get help on individual commands, use \"help quorum command\".\n"
            "\nArguments:\n"
            "1. \"command\"        (string, required) The command to execute\n"
            "\nAvailable commands:\n"
            "  list              - List of on-chain quorums\n"
            "  info              - Return information about a quorum\n"
            "  dkgsimerror       - Simulates DKG errors and malicious behavior\n"
            "  recovery          - Manually turn LOW_LLMQ on/off or inspect recorded status\n"
            "  dkgstatus         - Return the status of the current DKG process\n"
            "  memberof          - Checks which quorums the given smartnode is a member of\n"
            "  sign              - Threshold-sign a message\n"
            "  hasrecsig         - Test if a valid recovered signature is present\n"
            "  getrecsig         - Get a recovered signature\n"
            "  isconflicting     - Test if a conflict exists\n"
    );
}

static UniValue quorum_recovery_test(const JSONRPCRequest& request, bool create)
{
    if (!llmq::RecoveryProtocolEnabled()) throw JSONRPCError(RPC_INVALID_PARAMETER, "Signed recovery is not configured on this network");
    if (request.fHelp || (create ? (request.params.size() != 3 && request.params.size() != 4) : request.params.size() > 2)) {
        throw std::runtime_error("quorum recoveryrequest start_height end_height ( version ) | quorum recoverystate ( block_hash )\nSigned recovery record and historical state interface.");
    }
    LOCK(cs_main);
    const CBlockIndex* index = chainActive.Tip();
    if (!create && request.params.size() == 2) {
        const auto hash = ParseHashV(request.params[1], "block_hash");
        auto it = mapBlockIndex.find(hash);
        if (it == mapBlockIndex.end()) throw JSONRPCError(RPC_INVALID_PARAMETER, "Unknown block");
        index = it->second;
    }
    const auto policy = llmq::GetRecoveryPolicy();
    llmq::RecoveryStateStore store(*evoDb, policy);
    llmq::RecoveryState previous;
    if (!index || !store.ReadState(*index, previous)) throw JSONRPCError(RPC_INTERNAL_ERROR, "Recovery state missing; rebuild with -reindex-chainstate or -reindex");
    UniValue result(UniValue::VOBJ);
    if (!create) {
        result.pushKV("height", index->nHeight);
        result.pushKV("authorization", previous.lastAuthorization.ToString());
        result.pushKV("startHeight", previous.startHeight);
        result.pushKV("endHeight", previous.endHeight);
        result.pushKV("active", previous.IsLowAt(index->nHeight));
        return result;
    }
    llmq::RecoveryRequest record;
    record.genesisHash = policy.genesisHash;
    record.previousAuthorization = previous.lastAuthorization;
    record.anchorHeight = index->nHeight;
    record.anchorHash = index->GetBlockHash();
    record.startHeight = ParseInt32V(request.params[1], "start_height");
    record.endHeight = ParseInt32V(request.params[2], "end_height");
    if (request.params.size() == 4) {
        const int version = ParseInt32V(request.params[3], "version");
        if (version != 1 && version != 2) throw JSONRPCError(RPC_INVALID_PARAMETER, "Unsupported recovery version");
        record.version = version;
    }
    CBitcoinSecret secret;
    if (!secret.SetString(gArgs.GetArg("-sporkkey", ""))) throw JSONRPCError(RPC_INVALID_PARAMETER, "No spork signing key configured");
    std::vector<unsigned char> signature;
    if (!secret.GetKey().SignCompact(record.GetAuthorizationHash(), signature) || signature.size() != 65) {
        throw JSONRPCError(RPC_INTERNAL_ERROR, "Could not sign recovery request");
    }
    record.signatures.emplace_back();
    std::copy(signature.begin(), signature.end(), record.signatures.back().begin());
    llmq::RecoveryState next;
    std::string error;
    if (!llmq::ApplyRecoveryRequest(record, policy, *index, previous, next, error)) throw JSONRPCError(RPC_INVALID_PARAMETER, error);
    CDataStream payload(SER_NETWORK, PROTOCOL_VERSION);
    payload << record;
    result.pushKV("payload", HexStr(payload));
    result.pushKV("authorization", record.GetAuthorizationHash().ToString());
    return result;
}

// Operator-facing interface. Wallet routing is preserved for every nested RPC,
// and cs_main serializes concurrent recovery requests through submission.
static UniValue quorum_recovery(const JSONRPCRequest& request)
{
    if (request.fHelp || request.params.size() != 2) {
        throw std::runtime_error(
            "quorum recovery on|off|status\n"
            "Manually enable or disable LOW_LLMQ with a signed chain record.\n"
            "Uses sporkkey from yerbas.conf and the selected wallet for transaction fees.\n"
            "ON has no automatic expiry. Confirmation precedes activation at a quorum boundary.\n"
            "An unconfirmed request must be included by last_inclusion_height or resubmitted.\n"
            "Status reports confirmed authorization separately from pending_authorization.\n"
            "Requires release-defined activation or an isolated recovery test profile.\n");
    }
    const std::string action = request.params[1].get_str();
    if (action != "on" && action != "off" && action != "status")
        throw JSONRPCError(RPC_INVALID_PARAMETER, "Expected on, off, or status");
    if (!llmq::RecoveryProtocolEnabled())
        throw JSONRPCError(RPC_INVALID_PARAMETER, "Signed LOW_LLMQ history is not activated on this network");
    LOCK(cs_main);
    const auto* tip = chainActive.Tip();
    const auto policy = llmq::GetRecoveryPolicy();
    if (tip && tip->nHeight < policy.activationHeight) {
        if (action != "status")
            throw JSONRPCError(RPC_INVALID_PARAMETER, "Signed recovery has not activated yet");
        UniValue pending(UniValue::VOBJ);
        pending.pushKV("status", "not_activated");
        pending.pushKV("active", false);
        pending.pushKV("height", tip->nHeight);
        pending.pushKV("activation_height", policy.activationHeight);
        pending.pushKV("submitted", false);
        return pending;
    }
    llmq::RecoveryState current;
    if (!tip || !llmq::RecoveryStateStore(*evoDb, policy).ReadState(*tip, current))
        throw JSONRPCError(RPC_INTERNAL_ERROR, "Recovery history is unavailable");
    UniValue result(UniValue::VOBJ);
    const bool active = current.IsLowAt(tip->nHeight);
    result.pushKV("active", active);
    result.pushKV("height", tip->nHeight);
    result.pushKV("authorization", current.lastAuthorization.ToString());
    result.pushKV("automatic_expiry", false);

    // Report unconfirmed authorizations before accepting another request.
    std::vector<uint256> hashes;
    mempool.queryHashes(hashes);
    for (const auto& hash : hashes) {
        const auto tx = mempool.get(hash);
        llmq::RecoveryRequest pending;
        if (!tx || tx->nVersion != 3 || tx->nType != TRANSACTION_LLMQ_RECOVERY ||
            !GetTxPayload(*tx, pending) || pending.previousAuthorization != current.lastAuthorization) continue;
        CValidationState pendingState;
        if (!llmq::CheckRecoveryTransaction(*tx, tip, pendingState)) continue;
        const std::string pendingAction = pending.endHeight == 0 ? "on" : "off";
        if (action != "status" && (pending.version != 2 || action != pendingAction))
            throw JSONRPCError(RPC_INVALID_PARAMETER, "Another recovery transition is awaiting confirmation");
        result.pushKV("status", "awaiting_confirmation");
        result.pushKV("requested_action", pendingAction);
        result.pushKV("txid", hash.ToString());
        result.pushKV("pending_authorization", pending.GetAuthorizationHash().ToString());
        result.pushKV("last_inclusion_height", pending.startHeight - 1);
        result.pushKV("effective_height", pending.startHeight);
        result.pushKV("submitted", false);
        return result;
    }
    const int pendingHeight = current.startHeight > tip->nHeight ? current.startHeight :
        (current.endHeight > tip->nHeight ? current.endHeight : 0);
    if (pendingHeight) {
        const std::string pendingAction = current.startHeight > tip->nHeight ? "on" : "off";
        if (action != "status" && action != pendingAction)
            throw JSONRPCError(RPC_INVALID_PARAMETER, "Another recovery transition is confirmed and awaiting its effective height");
        result.pushKV("status", "scheduled");
        result.pushKV("requested_action", pendingAction);
        result.pushKV("effective_height", pendingHeight);
        result.pushKV("submitted", false);
        return result;
    }
    if (action == "status" || (action == "on") == active) {
        result.pushKV("status", active ? "on" : "off");
        result.pushKV("submitted", false);
        return result;
    }
#ifndef ENABLE_WALLET
    throw JSONRPCError(RPC_METHOD_NOT_FOUND, "A wallet-enabled build is required to submit recovery transitions");
#else
    CWallet* const wallet = GetWalletForJSONRPCRequest(request);
    if (!EnsureWalletIsAvailable(wallet, false)) return NullUniValue;
    LOCK(wallet->cs_wallet);
    EnsureWalletIsUnlocked(wallet);
    // Allow at least one full DKG interval for inclusion. Never expire an ON.
    const int64_t effective = (int64_t(tip->nHeight) / policy.dkgInterval + 2) * policy.dkgInterval;
    if (effective > std::numeric_limits<int32_t>::max())
        throw JSONRPCError(RPC_INVALID_PARAMETER, "Recovery height exceeds the supported range");
    JSONRPCRequest signing = request;
    signing.params = UniValue(UniValue::VARR);
    signing.params.push_back("recoveryrequest");
    signing.params.push_back(effective);
    signing.params.push_back(action == "on" ? int64_t(0) : effective);
    signing.params.push_back(2);
    const auto record = quorum_recovery_test(signing, true);
    CMutableTransaction tx;
    tx.nVersion = 3;
    tx.nType = TRANSACTION_LLMQ_RECOVERY;
    tx.vExtraPayload = ParseHex(record["payload"].get_str());
    tx.vout.emplace_back(0, CScript() << OP_RETURN);
    auto call = [&](const std::string& method, const UniValue& value) {
        JSONRPCRequest nested = request;
        nested.strMethod = method;
        nested.params = UniValue(UniValue::VARR);
        nested.params.push_back(value);
        return tableRPC.execute(nested);
    };
    const auto funded = call("fundrawtransaction", UniValue(EncodeHexTx(tx)));
    const auto signedTx = call("signrawtransaction", funded["hex"]);
    if (!signedTx["complete"].get_bool())
        throw JSONRPCError(RPC_WALLET_ERROR, "Wallet could not sign the recovery transaction");
    const auto txid = call("sendrawtransaction", signedTx["hex"]);
    result.pushKV("status", "awaiting_confirmation");
    result.pushKV("requested_action", action);
    result.pushKV("txid", txid.get_str());
    result.pushKV("pending_authorization", record["authorization"]);
    result.pushKV("last_inclusion_height", effective - 1);
    result.pushKV("effective_height", effective);
    result.pushKV("fee", funded["fee"]);
    result.pushKV("submitted", true);
    return result;
#endif
}

UniValue quorum(const JSONRPCRequest& request)
{
    if (request.fHelp && request.params.empty()) {
        quorum_help();
    }

    std::string command;
    if (request.params.size() >= 1) {
        command = request.params[0].get_str();
    }

    if (command == "recovery") {
        return quorum_recovery(request);
    } else if (command == "recoveryrequest" || command == "recoverystate") {
        return quorum_recovery_test(request, command == "recoveryrequest");
    } else if (command == "list") {
        return quorum_list(request);
    } else if (command == "info") {
        return quorum_info(request);
    } else if (command == "dkgstatus") {
        return quorum_dkgstatus(request);
    } else if (command == "memberof") {
        return quorum_memberof(request);
    } else if (command == "sign" || command == "hasrecsig" || command == "getrecsig" || command == "isconflicting") {
        return quorum_sigs_cmd(request);
    } else if (command == "dkgsimerror") {
        return quorum_dkgsimerror(request);
    } else {
        quorum_help();
    }
}

static const CRPCCommand commands[] =
{ //  category              name                      actor (function)         okSafeMode
  //  --------------------- ------------------------  -----------------------  ----------
    { "evo",                "quorum",                 &quorum,                 false, {}  },
};

void RegisterQuorumsRPCCommands(CRPCTable &tableRPC)
{
    for (unsigned int vcidx = 0; vcidx < ARRAYLEN(commands); vcidx++)
        tableRPC.appendCommand(commands[vcidx].name, &commands[vcidx]);
}
