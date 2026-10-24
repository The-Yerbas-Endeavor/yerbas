// Copyright (c) 2018-2019 The Dash Core developers
// Copyright (c) 2020 The Yerbas developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include "test/test_yerbas.h"
#include "chainparams.h"
#include <climits>
#include <fstream>
#include <cstdlib>

#include "script/interpreter.h"
#include "script/standard.h"
#include "script/sign.h"
#include "validation.h"
#include "base58.h"
#include "netbase.h"
#include "messagesigner.h"
#include "policy/policy.h"
#include "keystore.h"
#include "spork.h"

#include "evo/specialtx.h"
#include "llmq/quorums_pose.h"
#include "llmq/quorums_recovery.h"
#include "llmq/quorums_blockprocessor.h"
#include "smartnode/smartnode-sync.h"
#include "evo/providertx.h"
#include "evo/deterministicmns.h"

#include <boost/test/unit_test.hpp>

typedef std::map<COutPoint, std::pair<int, CAmount>> SimpleUTXOMap;

static SimpleUTXOMap BuildSimpleUtxoMap(const std::vector<CTransaction>& txs, const CKey& key)
{
    SimpleUTXOMap utxos;
    const CScript ownedScript = CScript() << ToByteVector(key.GetPubKey()) << OP_CHECKSIG;
    for (size_t i = 0; i < txs.size(); i++) {
        auto& tx = txs[i];
        for (size_t j = 0; j < tx.vout.size(); j++) {
            if (tx.vout[j].scriptPubKey != ownedScript) continue;
            utxos.emplace(COutPoint(tx.GetHash(), j), std::make_pair((int)i + 1, tx.vout[j].nValue));
        }
    }
    return utxos;
}

static std::vector<COutPoint> SelectUTXOs(SimpleUTXOMap& utoxs, CAmount amount, CAmount& changeRet)
{
    changeRet = 0;

    std::vector<COutPoint> selectedUtxos;
    CAmount selectedAmount = 0;
    while (!utoxs.empty()) {
        bool found = false;
        for (auto it = utoxs.begin(); it != utoxs.end(); ++it) {
            if (chainActive.Height() - it->second.first < 101) {
                continue;
            }

            found = true;
            selectedAmount += it->second.second;
            selectedUtxos.emplace_back(it->first);
            utoxs.erase(it);
            break;
        }
        BOOST_REQUIRE(found);
        if (selectedAmount >= amount) {
            changeRet = selectedAmount - amount;
            break;
        }
    }

    return selectedUtxos;
}

static void FundTransaction(CMutableTransaction& tx, SimpleUTXOMap& utoxs, const CScript& scriptPayout, CAmount amount, const CKey& coinbaseKey)
{
    CAmount change;
    auto inputs = SelectUTXOs(utoxs, amount, change);
    for (size_t i = 0; i < inputs.size(); i++) {
        tx.vin.emplace_back(CTxIn(inputs[i]));
    }
    tx.vout.emplace_back(CTxOut(amount, scriptPayout));
    if (change != 0) {
        tx.vout.emplace_back(CTxOut(change, scriptPayout));
    }
}

static void SignTransaction(CMutableTransaction& tx, const CKey& coinbaseKey)
{
    CBasicKeyStore tempKeystore;
    tempKeystore.AddKeyPubKey(coinbaseKey, coinbaseKey.GetPubKey());

    for (size_t i = 0; i < tx.vin.size(); i++) {
        CTransactionRef txFrom;
        uint256 hashBlock;
        BOOST_REQUIRE(GetTransaction(tx.vin[i].prevout.hash, txFrom, Params().GetConsensus(), hashBlock));
        BOOST_REQUIRE_MESSAGE(SignSignature(tempKeystore, *txFrom, tx, i, SIGHASH_ALL), "prev script " << HexStr(txFrom->vout[tx.vin[i].prevout.n].scriptPubKey) << " key " << HexStr(coinbaseKey.GetPubKey()));
    }
}

static CMutableTransaction CreateProRegTx(SimpleUTXOMap& utxos, int port, const CScript& scriptPayout, const CKey& coinbaseKey, CKey& ownerKeyRet, CBLSSecretKey& operatorKeyRet, const char* host = "1.1.1.1")
{
    ownerKeyRet.MakeNewKey(true);
    operatorKeyRet.MakeNewKey();

    CAmount collateralAmount = Params().GetConsensus().nCollaterals.getCollateral(chainActive.Height() < 0 ? 1 : chainActive.Height());

    CProRegTx proTx;
    proTx.collateralOutpoint.n = 0;
    proTx.addr = LookupNumeric(host, port);
    proTx.keyIDOwner = ownerKeyRet.GetPubKey().GetID();
    proTx.pubKeyOperator = operatorKeyRet.GetPublicKey();
    proTx.keyIDVoting = ownerKeyRet.GetPubKey().GetID();
    proTx.scriptPayout = scriptPayout;

    CMutableTransaction tx;
    tx.nVersion = 3;
    tx.nType = TRANSACTION_PROVIDER_REGISTER;
    FundTransaction(tx, utxos, scriptPayout, collateralAmount, coinbaseKey);
    proTx.inputsHash = CalcTxInputsHash(tx);
    SetTxPayload(tx, proTx);
    SignTransaction(tx, coinbaseKey);

    return tx;
}

static CMutableTransaction CreateFutureTransaction(SimpleUTXOMap& utxos, const CScript& scriptPayout) {
	CMutableTransaction tx;
	tx.nVersion = 4;
	tx.nType = TRANSACTION_FUTURE;
	return tx;
}

static CMutableTransaction CreateProUpServTx(SimpleUTXOMap& utxos, const uint256& proTxHash, const CBLSSecretKey& operatorKey, int port, const CScript& scriptOperatorPayout, const CKey& coinbaseKey)
{
    CAmount change;
    auto inputs = SelectUTXOs(utxos, 1 * COIN, change);

    CProUpServTx proTx;
    proTx.proTxHash = proTxHash;
    proTx.addr = LookupNumeric("1.1.1.1", port);
    proTx.scriptOperatorPayout = scriptOperatorPayout;

    CMutableTransaction tx;
    tx.nVersion = 3;
    tx.nType = TRANSACTION_PROVIDER_UPDATE_SERVICE;
    FundTransaction(tx, utxos, GetScriptForDestination(coinbaseKey.GetPubKey().GetID()), 1 * COIN, coinbaseKey);
    proTx.inputsHash = CalcTxInputsHash(tx);
    proTx.sig = operatorKey.Sign(::SerializeHash(proTx));
    SetTxPayload(tx, proTx);
    SignTransaction(tx, coinbaseKey);

    return tx;
}

static CMutableTransaction CreateProUpRegTx(SimpleUTXOMap& utxos, const uint256& proTxHash, const CKey& mnKey, const CBLSPublicKey& pubKeyOperator, const CKeyID& keyIDVoting, const CScript& scriptPayout, const CKey& coinbaseKey)
{
    CAmount change;
    auto inputs = SelectUTXOs(utxos, 1 * COIN, change);

    CProUpRegTx proTx;
    proTx.proTxHash = proTxHash;
    proTx.pubKeyOperator = pubKeyOperator;
    proTx.keyIDVoting = keyIDVoting;
    proTx.scriptPayout = scriptPayout;

    CMutableTransaction tx;
    tx.nVersion = 3;
    tx.nType = TRANSACTION_PROVIDER_UPDATE_REGISTRAR;
    FundTransaction(tx, utxos, GetScriptForDestination(coinbaseKey.GetPubKey().GetID()), 1 * COIN, coinbaseKey);
    proTx.inputsHash = CalcTxInputsHash(tx);
    CHashSigner::SignHash(::SerializeHash(proTx), mnKey, proTx.vchSig);
    SetTxPayload(tx, proTx);
    SignTransaction(tx, coinbaseKey);

    return tx;
}

static CMutableTransaction CreateProUpRevTx(SimpleUTXOMap& utxos, const uint256& proTxHash, const CBLSSecretKey& operatorKey, const CKey& coinbaseKey)
{
    CAmount change;
    auto inputs = SelectUTXOs(utxos, 1 * COIN, change);

    CProUpRevTx proTx;
    proTx.proTxHash = proTxHash;

    CMutableTransaction tx;
    tx.nVersion = 3;
    tx.nType = TRANSACTION_PROVIDER_UPDATE_REVOKE;
    FundTransaction(tx, utxos, GetScriptForDestination(coinbaseKey.GetPubKey().GetID()), 1 * COIN, coinbaseKey);
    proTx.inputsHash = CalcTxInputsHash(tx);
    proTx.sig = operatorKey.Sign(::SerializeHash(proTx));
    SetTxPayload(tx, proTx);
    SignTransaction(tx, coinbaseKey);

    return tx;
}

template<typename ProTx>
static CMutableTransaction MalleateProTxPayout(const CMutableTransaction& tx)
{
    ProTx proTx;
    GetTxPayload(tx, proTx);

    CKey key;
    key.MakeNewKey(false);
    proTx.scriptPayout = GetScriptForDestination(key.GetPubKey().GetID());

    CMutableTransaction tx2 = tx;
    SetTxPayload(tx2, proTx);

    return tx2;
}

static CScript GenerateRandomAddress()
{
    CKey key;
    key.MakeNewKey(false);
    return GetScriptForDestination(key.GetPubKey().GetID());
}

static CDeterministicMNCPtr FindPayoutDmn(const CBlock& block)
{
    auto dmnList = deterministicMNManager->GetListAtChainTip();

    for (const auto& txout : block.vtx[0]->vout) {
        CDeterministicMNCPtr found;
        dmnList.ForEachMN(true, [&](const CDeterministicMNCPtr& dmn) {
            if (found == nullptr && txout.scriptPubKey == dmn->pdmnState->scriptPayout) {
                found = dmn;
            }
        });
        if (found != nullptr) {
            return found;
        }
    }
    return nullptr;
}

static bool CheckTransactionSignature(const CMutableTransaction& tx)
{
    for (unsigned int i = 0; i < tx.vin.size(); i++) {
        const auto& txin = tx.vin[i];
        CTransactionRef txFrom;
        uint256 hashBlock;
        BOOST_REQUIRE(GetTransaction(txin.prevout.hash, txFrom, Params().GetConsensus(), hashBlock));

        CAmount amount = txFrom->vout[txin.prevout.n].nValue;
        if (!VerifyScript(txin.scriptSig, txFrom->vout[txin.prevout.n].scriptPubKey, STANDARD_SCRIPT_VERIFY_FLAGS, MutableTransactionSignatureChecker(&tx, i, amount))) {
            return false;
        }
    }
    return true;
}

// Isolated parameters for exercising the provider-transaction lifecycle.
// Yerbas regtest enables DIP3 at genesis and has no collateral/reward schedule.
struct FundedDIP3Setup : TestChainSetup
{
    FundedDIP3Setup() : TestChainSetup(0)
    {
        auto& params = const_cast<Consensus::Params&>(Params().GetConsensus());
        params.nCollaterals = SmartnodeCollaterals({{INT_MAX, 10 * COIN}}, {{INT_MAX, 20}});
        params.nSmartnodePaymentsStartBlock = 1;
        // Keep the fixed-difficulty regtest rules throughout this synthetic chain.
        params.nPowDGWHeight = INT_MAX;
        for (int i = 0; i < 200; ++i) {
            CBlock block = CreateAndProcessBlock({}, coinbaseKey);
            BOOST_REQUIRE(chainActive.Tip()->GetBlockHash() == block.GetHash());
            coinbaseTxns.push_back(*block.vtx[0]);
        }
    }
};

BOOST_AUTO_TEST_SUITE(evo_dip3_activation_tests)

BOOST_FIXTURE_TEST_CASE(dip3_activation, FundedDIP3Setup)
{
    auto utxos = BuildSimpleUtxoMap(coinbaseTxns, coinbaseKey);
    CKey ownerKey;
    CBLSSecretKey operatorKey;
    BOOST_REQUIRE(Params().GetConsensus().DIP0003Enabled);
    auto tx = CreateProRegTx(utxos, 1, GenerateRandomAddress(), coinbaseKey, ownerKey, operatorKey);
    const int height = chainActive.Height();
    auto block = std::make_shared<CBlock>(CreateBlock({tx}, coinbaseKey));
    BOOST_REQUIRE(ProcessNewBlock(Params(), block, true, nullptr));
    deterministicMNManager->UpdatedBlockTip(chainActive.Tip());
    BOOST_REQUIRE_EQUAL(chainActive.Height(), height + 1);
    BOOST_REQUIRE(chainActive.Tip()->GetBlockHash() == block->GetHash());
    BOOST_REQUIRE(deterministicMNManager->GetListAtChainTip().HasMN(tx.GetHash()));
}

BOOST_FIXTURE_TEST_CASE(dip3_protx, FundedDIP3Setup)
{
    CKey sporkKey;
    sporkKey.MakeNewKey(false);
    CBitcoinSecret sporkSecret(sporkKey);
    CBitcoinAddress sporkAddress;
    sporkAddress.Set(sporkKey.GetPubKey().GetID());
    sporkManager.SetSporkAddress(sporkAddress.ToString());
    sporkManager.SetPrivKey(sporkSecret.ToString());

    auto utxos = BuildSimpleUtxoMap(coinbaseTxns, coinbaseKey);

    int nHeight = chainActive.Height();
    int port = 1;

    std::vector<uint256> dmnHashes;
    std::map<uint256, CKey> ownerKeys;
    std::map<uint256, CBLSSecretKey> operatorKeys;

    // GetMNPayee requires more than ten registered nodes on Yerbas.
    for (size_t i = 0; i < 11; i++) {
        CKey ownerKey;
        CBLSSecretKey operatorKey;
        auto tx = CreateProRegTx(utxos, port++, GenerateRandomAddress(), coinbaseKey, ownerKey, operatorKey);
        dmnHashes.emplace_back(tx.GetHash());
        ownerKeys.emplace(tx.GetHash(), ownerKey);
        operatorKeys.emplace(tx.GetHash(), operatorKey);

        // also verify that payloads are not malleable after they have been signed
        // the form of ProRegTx we use here is one with a collateral included, so there is no signature inside the
        // payload itself. This means, we need to rely on script verification, which takes the hash of the extra payload
        // into account
        auto tx2 = MalleateProTxPayout<CProRegTx>(tx);
        CValidationState dummyState;
        // Technically, the payload is still valid...
        BOOST_REQUIRE(CheckProRegTx(tx, chainActive.Tip(), dummyState));
        BOOST_REQUIRE(CheckProRegTx(tx2, chainActive.Tip(), dummyState));
        // But the signature should not verify anymore
        BOOST_REQUIRE(CheckTransactionSignature(tx));
        BOOST_REQUIRE(!CheckTransactionSignature(tx2));

        CreateAndProcessBlock({tx}, coinbaseKey);
        deterministicMNManager->UpdatedBlockTip(chainActive.Tip());

        BOOST_REQUIRE(chainActive.Height() == nHeight + 1);
        BOOST_REQUIRE(deterministicMNManager->GetListAtChainTip().HasMN(tx.GetHash()));

        nHeight++;
    }

    CreateAndProcessBlock({}, coinbaseKey);
    deterministicMNManager->UpdatedBlockTip(chainActive.Tip());
    nHeight++;

    // check MN reward payments
    for (size_t i = 0; i < 20; i++) {
        auto dmnExpectedPayee = deterministicMNManager->GetListAtChainTip().GetMNPayee();

        CBlock block = CreateAndProcessBlock({}, coinbaseKey);
        deterministicMNManager->UpdatedBlockTip(chainActive.Tip());
        BOOST_REQUIRE(!block.vtx.empty());

        auto dmnPayout = FindPayoutDmn(block);
        BOOST_REQUIRE_MESSAGE(dmnPayout != nullptr, "nodes=" << deterministicMNManager->GetListAtChainTip().GetAllMNsCount() << " percentage=" << Params().GetConsensus().nCollaterals.getRewardPercentage(chainActive.Height()) << " payment=" << GetSmartnodePayment(chainActive.Height(), 100 * COIN, 0) << " outputs=" << block.vtx[0]->vout.size());
        BOOST_CHECK_EQUAL(dmnPayout->proTxHash.ToString(), dmnExpectedPayee->proTxHash.ToString());

        nHeight++;
    }

    // register multiple MNs per block
    for (size_t i = 0; i < 3; i++) {
        std::vector<CMutableTransaction> txns;
        for (size_t j = 0; j < 3; j++) {
            CKey ownerKey;
            CBLSSecretKey operatorKey;
            auto tx = CreateProRegTx(utxos, port++, GenerateRandomAddress(), coinbaseKey, ownerKey, operatorKey);
            dmnHashes.emplace_back(tx.GetHash());
            ownerKeys.emplace(tx.GetHash(), ownerKey);
            operatorKeys.emplace(tx.GetHash(), operatorKey);
            txns.emplace_back(tx);
        }
        CreateAndProcessBlock(txns, coinbaseKey);
        deterministicMNManager->UpdatedBlockTip(chainActive.Tip());
        BOOST_REQUIRE(chainActive.Height() == nHeight + 1);

        for (size_t j = 0; j < 3; j++) {
            BOOST_REQUIRE(deterministicMNManager->GetListAtChainTip().HasMN(txns[j].GetHash()));
        }

        nHeight++;
    }

    // test ProUpServTx
    auto tx = CreateProUpServTx(utxos, dmnHashes[0], operatorKeys[dmnHashes[0]], 1000, CScript(), coinbaseKey);
    CreateAndProcessBlock({tx}, coinbaseKey);
    deterministicMNManager->UpdatedBlockTip(chainActive.Tip());
    BOOST_REQUIRE(chainActive.Height() == nHeight + 1);
    nHeight++;

    auto dmn = deterministicMNManager->GetListAtChainTip().GetMN(dmnHashes[0]);
    BOOST_REQUIRE(dmn != nullptr && dmn->pdmnState->addr.GetPort() == 1000);

    // test ProUpRevTx
    tx = CreateProUpRevTx(utxos, dmnHashes[0], operatorKeys[dmnHashes[0]], coinbaseKey);
    CreateAndProcessBlock({tx}, coinbaseKey);
    deterministicMNManager->UpdatedBlockTip(chainActive.Tip());
    BOOST_REQUIRE(chainActive.Height() == nHeight + 1);
    nHeight++;

    dmn = deterministicMNManager->GetListAtChainTip().GetMN(dmnHashes[0]);
    BOOST_REQUIRE(dmn != nullptr && dmn->pdmnState->nPoSeBanHeight == nHeight);

    // test that the revoked MN does not get paid anymore
    for (size_t i = 0; i < 20; i++) {
        auto dmnExpectedPayee = deterministicMNManager->GetListAtChainTip().GetMNPayee();
        BOOST_REQUIRE(dmnExpectedPayee->proTxHash != dmnHashes[0]);

        CBlock block = CreateAndProcessBlock({}, coinbaseKey);
        deterministicMNManager->UpdatedBlockTip(chainActive.Tip());
        BOOST_REQUIRE(!block.vtx.empty());

        auto dmnPayout = FindPayoutDmn(block);
        BOOST_REQUIRE_MESSAGE(dmnPayout != nullptr, "nodes=" << deterministicMNManager->GetListAtChainTip().GetAllMNsCount() << " percentage=" << Params().GetConsensus().nCollaterals.getRewardPercentage(chainActive.Height()) << " payment=" << GetSmartnodePayment(chainActive.Height(), 100 * COIN, 0) << " outputs=" << block.vtx[0]->vout.size());
        BOOST_CHECK_EQUAL(dmnPayout->proTxHash.ToString(), dmnExpectedPayee->proTxHash.ToString());

        nHeight++;
    }

    // test reviving the MN
    CBLSSecretKey newOperatorKey;
    newOperatorKey.MakeNewKey();
    dmn = deterministicMNManager->GetListAtChainTip().GetMN(dmnHashes[0]);
    tx = CreateProUpRegTx(utxos, dmnHashes[0], ownerKeys[dmnHashes[0]], newOperatorKey.GetPublicKey(), ownerKeys[dmnHashes[0]].GetPubKey().GetID(), dmn->pdmnState->scriptPayout, coinbaseKey);
    // check malleability protection again, but this time by also relying on the signature inside the ProUpRegTx
    auto tx2 = MalleateProTxPayout<CProUpRegTx>(tx);
    CValidationState dummyState;
    BOOST_REQUIRE(CheckProUpRegTx(tx, chainActive.Tip(), dummyState));
    BOOST_REQUIRE(!CheckProUpRegTx(tx2, chainActive.Tip(), dummyState));
    BOOST_REQUIRE(CheckTransactionSignature(tx));
    BOOST_REQUIRE(!CheckTransactionSignature(tx2));
    // now process the block
    CreateAndProcessBlock({tx}, coinbaseKey);
    deterministicMNManager->UpdatedBlockTip(chainActive.Tip());
    BOOST_REQUIRE(chainActive.Height() == nHeight + 1);
    nHeight++;

    tx = CreateProUpServTx(utxos, dmnHashes[0], newOperatorKey, 100, CScript(), coinbaseKey);
    CreateAndProcessBlock({tx}, coinbaseKey);
    deterministicMNManager->UpdatedBlockTip(chainActive.Tip());
    BOOST_REQUIRE(chainActive.Height() == nHeight + 1);
    nHeight++;

    dmn = deterministicMNManager->GetListAtChainTip().GetMN(dmnHashes[0]);
    BOOST_REQUIRE(dmn != nullptr && dmn->pdmnState->addr.GetPort() == 100);
    BOOST_REQUIRE(dmn != nullptr && dmn->pdmnState->nPoSeBanHeight == -1);

    // test that the revived MN gets payments again
    bool foundRevived = false;
    for (size_t i = 0; i < 20; i++) {
        auto dmnExpectedPayee = deterministicMNManager->GetListAtChainTip().GetMNPayee();
        if (dmnExpectedPayee->proTxHash == dmnHashes[0]) {
            foundRevived = true;
        }

        CBlock block = CreateAndProcessBlock({}, coinbaseKey);
        deterministicMNManager->UpdatedBlockTip(chainActive.Tip());
        BOOST_REQUIRE(!block.vtx.empty());

        auto dmnPayout = FindPayoutDmn(block);
        BOOST_REQUIRE_MESSAGE(dmnPayout != nullptr, "nodes=" << deterministicMNManager->GetListAtChainTip().GetAllMNsCount() << " percentage=" << Params().GetConsensus().nCollaterals.getRewardPercentage(chainActive.Height()) << " payment=" << GetSmartnodePayment(chainActive.Height(), 100 * COIN, 0) << " outputs=" << block.vtx[0]->vout.size());
        BOOST_CHECK_EQUAL(dmnPayout->proTxHash.ToString(), dmnExpectedPayee->proTxHash.ToString());

        nHeight++;
    }
    BOOST_REQUIRE(foundRevived);

}
BOOST_AUTO_TEST_SUITE_END()


// Exercise reports -> quorum certificate -> persisted DKG policy -> mined
// penalties -> revival using real provider transactions and commitment checks.
BOOST_FIXTURE_TEST_CASE(pose_certificate_lifecycle, FundedDIP3Setup)
{
    auto& consensus = const_cast<Consensus::Params&>(Params().GetConsensus());
    consensus.nPoSeQuorumActivationHeight = 240;
    const auto poseType = consensus.llmqTypePoSe;
    auto utxos = BuildSimpleUtxoMap(coinbaseTxns, coinbaseKey);
    std::map<uint256, CBLSSecretKey> operatorKeys;
    for (int i = 0; i < 11; ++i) {
        CKey owner; CBLSSecretKey op;
        auto tx = CreateProRegTx(utxos, i + 1, GenerateRandomAddress(), coinbaseKey, owner, op);
        operatorKeys.emplace(tx.GetHash(), op);
        auto block = CreateAndProcessBlock({tx}, coinbaseKey);
        BOOST_REQUIRE(chainActive.Tip()->GetBlockHash() == block.GetHash());
        deterministicMNManager->UpdatedBlockTip(chainActive.Tip());
    }
    auto mineTo = [&](int height) {
        while (chainActive.Height() < height) {
            auto block = CreateAndProcessBlock({}, coinbaseKey);
            BOOST_REQUIRE(chainActive.Tip()->GetBlockHash() == block.GetHash());
            deterministicMNManager->UpdatedBlockTip(chainActive.Tip());
        }
    };
    auto makeCommitment = [&](Consensus::LLMQType type, int height, const CBLSSecretKey& key, const uint256& excluded) {
        LOCK(cs_main);
        const auto& params = consensus.llmqs.at(type);
        llmq::CFinalCommitment qc(params, chainActive[height]->GetBlockHash());
        const auto members = llmq::CLLMQUtils::GetAllQuorumMembers(type, chainActive[height]);
        for (size_t i = 0; i < members.size(); ++i) {
            qc.validMembers[i] = members[i]->proTxHash != excluded;
            qc.signers[i] = qc.validMembers[i];
        }
        qc.quorumPublicKey = key.GetPublicKey(); qc.quorumVvecHash = uint256S("42");
        auto hash = llmq::CLLMQUtils::BuildCommitmentHash(type, qc.quorumHash, qc.validMembers, qc.quorumPublicKey, qc.quorumVvecHash);
        std::vector<CBLSSignature> sigs; std::vector<CBLSPublicKey> keys;
        for (size_t i = 0; i < members.size(); ++i) if (qc.signers[i]) {
            auto op = operatorKeys.at(members[i]->proTxHash);
            sigs.push_back(op.Sign(hash)); keys.push_back(op.GetPublicKey());
        }
        qc.membersSig = CBLSSignature::AggregateSecure(sigs, keys, hash);
        qc.quorumSig = key.Sign(hash);
        BOOST_REQUIRE(qc.Verify(members, true));
        return qc;
    };
    mineTo(240);
    CBLSSecretKey quorumKey; quorumKey.MakeNewKey();
    auto qc = makeCommitment(poseType, 240, quorumKey, uint256());
    llmq::quorumBlockProcessor->AddMinableCommitment(qc);
    mineTo(300);
    smartnodeSync.Reset();
    for (int i = 0; i < 3; ++i) smartnodeSync.SwitchToNextAsset(*g_connman);
    BOOST_REQUIRE(!IsInitialBlockDownload());
    auto members = llmq::CLLMQUtils::GetAllQuorumMembers(Consensus::LLMQ_50_60, chainActive[300]);
    BOOST_REQUIRE(!members.empty());
    const uint256 target = members.front()->proTxHash;
    const auto request = llmq::poseManager->MakeRequest(target, 270);
    std::vector<CBLSSecretKey> monitors(3); std::vector<std::string> pubs;
    for (auto& key : monitors) { key.MakeNewKey(); pubs.push_back(key.GetPublicKey().ToString()); }
    const auto oldKeys = gArgs.GetArgs("-posemonitorpubkey");
    struct RestoreKeys { std::vector<std::string> keys; ~RestoreKeys() {
        if (keys.empty()) gArgs.ForceRemoveArg("-posemonitorpubkey");
        else { gArgs.ForceSetArg("-posemonitorpubkey", keys.front()); gArgs.ForceSetMultiArgs("-posemonitorpubkey", keys); }
        smartnodeSync.Reset();
    }} restore{oldKeys};
    gArgs.ForceSetArg("-posemonitorpubkey", pubs.front());
    gArgs.ForceSetMultiArgs("-posemonitorpubkey", pubs);
    std::string error;
    auto early = llmq::poseManager->MakeRequest(target, 240);
    for (const auto& key : monitors) {
        llmq::CPoSeReport report; report.request = early;
        report.observer = key.GetPublicKey(); report.signature = key.Sign(report.GetSignHash());
        BOOST_REQUIRE_MESSAGE(llmq::poseManager->SubmitReport(report, error, nullptr), error);
    }
    BOOST_CHECK(!llmq::poseManager->Approve(early.GetId(), error));
    BOOST_CHECK(error.find("No eligible PoSe quorum") != std::string::npos);
    BOOST_CHECK(!llmq::poseManager->ShouldVoteBad(target));
    for (const auto& key : monitors) {
        llmq::CPoSeReport report; report.request = request;
        report.observer = key.GetPublicKey(); report.signature = key.Sign(report.GetSignHash());
        BOOST_REQUIRE_MESSAGE(llmq::poseManager->SubmitReport(report, error, nullptr), error);
        BOOST_REQUIRE(llmq::poseManager->SubmitReport(report, error, nullptr)); // deduplicated
        BOOST_CHECK(!llmq::poseManager->ShouldVoteBad(target));
    }
    auto status = llmq::poseManager->Status();
    BOOST_REQUIRE_EQUAL(status["pending"].size(), 2U);
    BOOST_CHECK_EQUAL(status["pending"][0]["observers"].get_int(), 3);
    BOOST_CHECK(!llmq::poseManager->Approve(request.GetId(), error)); // full node is not a signer
    llmq::CPoSeCertificate cert; cert.request = request; cert.quorumHash = qc.quorumHash;
    auto signHash = llmq::CLLMQUtils::BuildSignHash(poseType, cert.quorumHash, request.GetId(), request.GetSignHash());
    cert.signature = monitors[0].Sign(signHash);
    BOOST_CHECK(!llmq::poseManager->SubmitCertificate(cert, error, nullptr));
    cert.signature = quorumKey.Sign(signHash);
    BOOST_REQUIRE_MESSAGE(llmq::poseManager->SubmitCertificate(cert, error, nullptr), error);
    BOOST_CHECK(llmq::poseManager->ShouldVoteBad(target));
    BOOST_CHECK(llmq::quorumSigningManager->VerifyRecoveredSig(poseType, request.height, request.GetId(), request.GetSignHash(), cert.signature));
    BOOST_CHECK(!llmq::quorumSigningManager->VerifyRecoveredSig(consensus.llmqTypeChainLocks, request.height, request.GetId(), request.GetSignHash(), cert.signature));
    auto changed = cert; changed.request.blockHash = uint256S("ff");
    BOOST_CHECK(!llmq::poseManager->SubmitCertificate(changed, error, nullptr));
    // A fresh manager reads the certificate from the same persistent database.
    CDBWrapper disk("", 1 << 20, true);
    llmq::CPoSeManager restarted(disk);
    BOOST_REQUIRE(restarted.SubmitCertificate(cert, error, nullptr));
    llmq::CPoSeManager restartedAgain(disk);
    BOOST_CHECK(restartedAgain.ShouldVoteBad(target));
    // Applying the certificate itself has not changed consensus eligibility.
    BOOST_CHECK_EQUAL(deterministicMNManager->GetListAtChainTip().GetMN(target)->pdmnState->nPoSePenalty, 0);
    for (int height = 300; height <= 420; height += 30) {
        mineTo(height);
        if (deterministicMNManager->GetListAtChainTip().IsMNPoSeBanned(target)) break;
        const auto candidates = llmq::CLLMQUtils::GetAllQuorumMembers(Consensus::LLMQ_50_60, chainActive[height]);
        if (std::none_of(candidates.begin(), candidates.end(), [&](const auto& mn) { return mn->proTxHash == target; })) continue;
        BOOST_REQUIRE(restartedAgain.ShouldVoteBad(target));
        auto penalty = makeCommitment(Consensus::LLMQ_50_60, height, quorumKey, target);
        llmq::quorumBlockProcessor->AddMinableCommitment(penalty);
        mineTo(height + 10);
    }
    BOOST_REQUIRE(deterministicMNManager->GetListAtChainTip().IsMNPoSeBanned(target));
    auto revive = CreateProUpServTx(utxos, target, operatorKeys.at(target), 100, CScript(), coinbaseKey);
    auto revived = CreateAndProcessBlock({revive}, coinbaseKey);
    BOOST_REQUIRE(chainActive.Tip()->GetBlockHash() == revived.GetHash());
    deterministicMNManager->UpdatedBlockTip(chainActive.Tip());
    BOOST_CHECK(!deterministicMNManager->GetListAtChainTip().IsMNPoSeBanned(target));
    BOOST_CHECK(!restartedAgain.ShouldVoteBad(target));
    BOOST_CHECK(!restartedAgain.SubmitCertificate(cert, error, nullptr));
}


BOOST_FIXTURE_TEST_CASE(recovery_consensus_lifecycle, FundedDIP3Setup)
{
    auto& p=const_cast<Consensus::Params&>(Params().GetConsensus());
    struct Restore { Consensus::Params& ref; Consensus::Params old; ~Restore(){ref=old;} } restore{p,p};
    auto q=p.llmqs.at(Consensus::LLMQ_POSE_TEST);
    q.type=Consensus::LLMQ_100_67; q.size=100; q.minSize=80; q.threshold=67;
    q.dkgBadVotesThreshold=80; q.dkgInterval=60;
    p.llmqs.erase(Consensus::LLMQ_POSE_TEST); p.llmqs[Consensus::LLMQ_100_67]=q;
    p.llmqTypePoSe=Consensus::LLMQ_100_67;
    p.nPoSeQuorumActivationHeight=600; p.nRecoveryActivationHeight=600;
    // Supply enough mature coinbase inputs for all 80 registrations.
    for (int i=0;i<279;++i) {
        auto block=CreateAndProcessBlock({},coinbaseKey);
        BOOST_REQUIRE(chainActive.Tip()->GetBlockHash()==block.GetHash());
        coinbaseTxns.push_back(*block.vtx[0]);
    }
    std::map<uint256,CBLSSecretKey> operatorKeys;
    auto utxos=BuildSimpleUtxoMap(coinbaseTxns,coinbaseKey);
    uint256 target;
    std::vector<CMutableTransaction> registrations;
    for(int i=0;i<80;++i){
        CKey owner; CBLSSecretKey op;
        auto tx=CreateProRegTx(utxos,25000+i,GenerateRandomAddress(),coinbaseKey,owner,op,"127.0.0.1");
        target=tx.GetHash();operatorKeys.emplace(target,op);
        CValidationState registrationState;
        BOOST_REQUIRE_MESSAGE(CheckSpecialTx(CTransaction(tx),chainActive.Tip(),registrationState),
            "registration " << i << ": " << registrationState.GetRejectReason());
        registrations.push_back(tx);
    }
    // Register at a session boundary, outside legacy quorum mining windows.
    // Legacy quorum parameters are updated by the deterministic-list builder.
    auto registrationBlock=CreateAndProcessBlock(registrations,coinbaseKey);
    BOOST_REQUIRE(chainActive.Tip()->GetBlockHash()==registrationBlock.GetHash());
    deterministicMNManager->UpdatedBlockTip(chainActive.Tip());
    auto mineTo=[&](int h){while(chainActive.Height()<h){
        auto block=CreateAndProcessBlock({},coinbaseKey);
        BOOST_REQUIRE(chainActive.Tip()->GetBlockHash()==block.GetHash());
        deterministicMNManager->UpdatedBlockTip(chainActive.Tip());
    }};
    mineTo(738);
    auto early=llmq::GetRecoveryState(chainActive.Tip());
    BOOST_REQUIRE_EQUAL(early.mode,1);
    BOOST_CHECK(llmq::GetRecoveryRoster(early.frozenRoster).members.empty());
    // Three cryptographically valid production commitments establish history.
    // This fixture constructs commitments; it does not simulate distributed DKG.
    for(int height:{1200,1260,1320}) {
        mineTo(height);
        const auto& params=p.llmqs.at(Consensus::LLMQ_100_67);
        auto members=llmq::CLLMQUtils::GetAllQuorumMembers(Consensus::LLMQ_100_67,chainActive[height]);
        BOOST_REQUIRE_EQUAL(members.size(),80U);
        llmq::CFinalCommitment qc(params,chainActive[height]->GetBlockHash());
        CBLSSecretKey quorumKey;quorumKey.MakeNewKey();
        qc.quorumPublicKey=quorumKey.GetPublicKey();qc.quorumVvecHash=uint256S("42");
        for(size_t i=0;i<members.size();++i)qc.validMembers[i]=qc.signers[i]=true;
        auto hash=llmq::CLLMQUtils::BuildCommitmentHash(Consensus::LLMQ_100_67,qc.quorumHash,qc.validMembers,qc.quorumPublicKey,qc.quorumVvecHash);
        std::vector<CBLSSignature> sigs;std::vector<CBLSPublicKey> pubs;
        for(const auto& member:members){auto key=operatorKeys.at(member->proTxHash);sigs.push_back(key.Sign(hash));pubs.push_back(key.GetPublicKey());}
        qc.membersSig=CBLSSignature::AggregateSecure(sigs,pubs,hash);qc.quorumSig=quorumKey.Sign(hash);
        BOOST_REQUIRE(qc.Verify(members,true));llmq::quorumBlockProcessor->AddMinableCommitment(qc);
        mineTo(height+18);
    }
    BOOST_CHECK_EQUAL(llmq::GetRecoveryState(chainActive.Tip()).mode,0);
    mineTo(1440);
    auto scheduled=llmq::GetRecoveryState(chainActive.Tip());
    auto roster=llmq::GetRecoveryRoster(scheduled.scheduledRoster);
    BOOST_REQUIRE_EQUAL(roster.qualified,80);BOOST_REQUIRE_EQUAL(roster.members.size(),15U);
    mineTo(1518);
    auto state=llmq::GetRecoveryState(chainActive.Tip());
    BOOST_REQUIRE_EQUAL(state.mode,1);BOOST_REQUIRE_EQUAL(state.budget,8);
    BOOST_REQUIRE(state.frozenRoster==scheduled.scheduledRoster);
    // Exclude the penalized target from the signing roster to keep role assertions clear.
    for(const auto& item:operatorKeys){
        bool selected=false;for(const auto& member:roster.members)selected |= member.proTxHash==item.first;
        if(!selected){target=item.first;break;}
    }
    std::vector<CBLSSecretKey> keys;
    for(const auto& member:roster.members)keys.push_back(operatorKeys.at(member.proTxHash));
    mineTo(1539);
    llmq::CRecoveryCertificate c;
    c.committee=state.frozenRoster;c.epoch=state.epoch;c.target=target;
    c.start=1519;c.end=1539;c.expiry=1569;
    c.startHash=chainActive[c.start]->GetBlockHash();c.endHash=chainActive[c.end]->GetBlockHash();
    auto mn=deterministicMNManager->GetListForBlock(chainActive.Tip()).GetMN(target);
    c.stateHash=llmq::PoSeStateHash(*mn->pdmnState);
    for(int i=0;i<10;++i)c.signatures.emplace_back(i,keys[i].Sign(c.SignHash(p)));
    CMutableTransaction tx;tx.nVersion=3;tx.nType=TRANSACTION_RECOVERY_PENALTY;
    SetTxPayload(tx,c);
    {CValidationState invalid;BOOST_CHECK(!llmq::CheckRecoveryTx(CTransaction(tx),chainActive.Tip(),invalid));}
    c.signatures.emplace_back(10,keys[10].Sign(c.SignHash(p)));SetTxPayload(tx,c);
    {CValidationState valid;BOOST_REQUIRE(llmq::CheckRecoveryTx(CTransaction(tx),chainActive.Tip(),valid));}
    {
        CBlock duplicate; duplicate.vtx={MakeTransactionRef(tx),MakeTransactionRef(tx)};
        CValidationState check;
        BOOST_CHECK(!llmq::CheckRecoveryBlock(duplicate,chainActive.Tip(),check));
        BOOST_CHECK_EQUAL(check.GetRejectReason(),"bad-recovery-block-limit");
    }
    {
        CMutableTransaction update;update.nVersion=3;update.nType=TRANSACTION_PROVIDER_UPDATE_SERVICE;
        CProUpServTx payload;payload.proTxHash=target;SetTxPayload(update,payload);
        CBlock conflict;conflict.vtx={MakeTransactionRef(update),MakeTransactionRef(tx)};
        CValidationState check;
        BOOST_CHECK(!llmq::CheckRecoveryBlock(conflict,chainActive.Tip(),check));
        BOOST_CHECK_EQUAL(check.GetRejectReason(),"bad-recovery-target-change");
    }
    for(bool reversed:{false,true}) {
        CMutableTransaction spend;spend.vin.emplace_back(mn->collateralOutpoint);
        CBlock conflict;conflict.vtx={MakeTransactionRef(spend),MakeTransactionRef(tx)};
        if(reversed)std::reverse(conflict.vtx.begin(),conflict.vtx.end());
        CValidationState check;
        BOOST_CHECK(!llmq::CheckRecoveryBlock(conflict,chainActive.Tip(),check));
        BOOST_CHECK_EQUAL(check.GetRejectReason(),"bad-recovery-target-spent");
    }
    {
        CMutableTransaction replacement;replacement.nVersion=3;replacement.nType=TRANSACTION_PROVIDER_REGISTER;
        CProRegTx payload;payload.collateralOutpoint=mn->collateralOutpoint;SetTxPayload(replacement,payload);
        CBlock conflict;conflict.vtx={MakeTransactionRef(tx),MakeTransactionRef(replacement)};
        CValidationState check;
        BOOST_CHECK(!llmq::CheckRecoveryBlock(conflict,chainActive.Tip(),check));
        BOOST_CHECK_EQUAL(check.GetRejectReason(),"bad-recovery-target-replaced");
    }
    {
        auto invalid=tx;invalid.nVersion=4;CValidationState check;
        BOOST_CHECK(!llmq::CheckRecoveryTx(CTransaction(invalid),chainActive.Tip(),check));
    }
    auto rejectedCertificate = [&](const llmq::CRecoveryCertificate& invalid, const std::string& reason) {
        CMutableTransaction wrapper=tx; SetTxPayload(wrapper,invalid);
        CValidationState check;
        BOOST_CHECK(!llmq::CheckRecoveryTx(CTransaction(wrapper),chainActive.Tip(),check));
        BOOST_CHECK_EQUAL(check.GetRejectReason(),reason);
    };
    auto invalid=c;invalid.expiry++;rejectedCertificate(invalid,"bad-recovery-window");
    invalid=c;invalid.start=1518;rejectedCertificate(invalid,"bad-recovery-window");
    invalid=c;invalid.end=1540;rejectedCertificate(invalid,"bad-recovery-window");
    invalid=c;invalid.endHash=uint256S("ff");rejectedCertificate(invalid,"bad-recovery-branch");
    invalid=c;invalid.stateHash=uint256S("ff");rejectedCertificate(invalid,"bad-recovery-target");
    invalid=c;invalid.epoch=uint256S("ff");rejectedCertificate(invalid,"bad-recovery-epoch");
    CScript payout=CScript()<<ToByteVector(coinbaseKey.GetPubKey())<<OP_CHECKSIG;
    FundTransaction(tx,utxos,payout,COIN,coinbaseKey); SignTransaction(tx,coinbaseKey);
    auto block=CreateAndProcessBlock({tx},coinbaseKey);
    BOOST_REQUIRE(chainActive.Tip()->GetBlockHash()==block.GetHash());
    deterministicMNManager->UpdatedBlockTip(chainActive.Tip());
    auto after=deterministicMNManager->GetListForBlock(chainActive.Tip());
    BOOST_CHECK(after.GetMN(target)->pdmnState->nPoSePenalty>0);
    BOOST_CHECK_EQUAL(llmq::GetRecoveryState(chainActive.Tip()).consumed.size(),1U);
    {CValidationState replay;BOOST_CHECK(!llmq::CheckRecoveryTx(CTransaction(tx),chainActive.Tip(),replay));}
    if (const char* path=std::getenv("YERBAS_RC_FIXTURE")) {
        std::ofstream out(path);
        BOOST_REQUIRE(out.good());
        out << "{\"committee\":\"" << state.frozenRoster.ToString()
            << "\",\"target\":\"" << target.ToString()
            << "\",\"penalty\":" << after.GetMN(target)->pdmnState->nPoSePenalty << "}\n";
        for (int height=1;height<=1540;++height) {
            CBlock saved;
            BOOST_REQUIRE(ReadBlockFromDisk(saved,chainActive[height],p));
            CDataStream data(SER_NETWORK,PROTOCOL_VERSION);data<<saved;
            out<<HexStr(data.begin(),data.end())<<"\n";
        }
        BOOST_REQUIRE(out.good());
    }
    // Optional local-only RPC fixture secrets. Never use these generated keys
    // outside the isolated regtest campaign or publish the resulting file.
    if (const char* path=std::getenv("YERBAS_RC_RPC_KEYS")) {
        UniValue metadata(UniValue::VOBJ), signers(UniValue::VARR);
        metadata.pushKV("fundingKey", CBitcoinSecret(coinbaseKey).ToString());
        auto addIdentity = [&](const uint256& id) {
            UniValue identity(UniValue::VOBJ);
            identity.pushKV("proTxHash", id.ToString());
            identity.pushKV("key", operatorKeys.at(id).ToString());
            identity.pushKV("service", after.GetMN(id)->pdmnState->addr.ToString());
            return identity;
        };
        for (const auto& member : roster.members) signers.push_back(addIdentity(member.proTxHash));
        metadata.pushKV("signers", signers);
        metadata.pushKV("nonmember", addIdentity(target));
        std::ofstream out(path);
        BOOST_REQUIRE(out.good());
        out << metadata.write() << '\n';
        BOOST_REQUIRE(out.good());
    }
    // Exhaust the epoch's eight-target budget using distinct, fully signed,
    // funded transactions. The ninth certificate must fail even with 11 approvals.
    int penalized=1;
    for(const auto& item:operatorKeys) {
        if(item.first==target)continue;
        auto cert=c;cert.target=item.first;
        auto candidate=deterministicMNManager->GetListForBlock(chainActive.Tip()).GetMN(cert.target);
        cert.stateHash=llmq::PoSeStateHash(*candidate->pdmnState);
        cert.signatures.clear();
        for(int i=0;i<11;++i)cert.signatures.emplace_back(i,keys[i].Sign(cert.SignHash(p)));
        CMutableTransaction penalty;penalty.nVersion=3;penalty.nType=TRANSACTION_RECOVERY_PENALTY;
        SetTxPayload(penalty,cert);
        CValidationState check;
        if(penalized==state.budget) {
            BOOST_CHECK(!llmq::CheckRecoveryTx(CTransaction(penalty),chainActive.Tip(),check));
            BOOST_CHECK_EQUAL(check.GetRejectReason(),"bad-recovery-budget");
            break;
        }
        BOOST_REQUIRE(llmq::CheckRecoveryTx(CTransaction(penalty),chainActive.Tip(),check));
        FundTransaction(penalty,utxos,payout,COIN,coinbaseKey);SignTransaction(penalty,coinbaseKey);
        auto mined=CreateAndProcessBlock({penalty},coinbaseKey);
        BOOST_REQUIRE(chainActive.Tip()->GetBlockHash()==mined.GetHash());
        deterministicMNManager->UpdatedBlockTip(chainActive.Tip());
        ++penalized;
        BOOST_CHECK_EQUAL(llmq::GetRecoveryState(chainActive.Tip()).consumed.size(),size_t(penalized));
    }
    BOOST_CHECK_EQUAL(penalized,8);
    mineTo(1800);
    BOOST_CHECK(llmq::GetRecoveryState(chainActive.Tip()).frozenRoster==state.frozenRoster);
    mineTo(1878);
    BOOST_CHECK_EQUAL(llmq::GetRecoveryState(chainActive.Tip()).mode,2);
}
