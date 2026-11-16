// Copyright (c) 2018-2019 The Dash Core developers
// Copyright (c) 2020 The Yerbas developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include "test/test_yerbas.h"
#include "chainparams.h"
#include <climits>

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

static CMutableTransaction CreateProRegTx(SimpleUTXOMap& utxos, int port, const CScript& scriptPayout, const CKey& coinbaseKey, CKey& ownerKeyRet, CBLSSecretKey& operatorKeyRet)
{
    ownerKeyRet.MakeNewKey(true);
    operatorKeyRet.MakeNewKey();

    CAmount collateralAmount = Params().GetConsensus().nCollaterals.getCollateral(chainActive.Height() < 0 ? 1 : chainActive.Height());

    CProRegTx proTx;
    proTx.collateralOutpoint.n = 0;
    proTx.addr = LookupNumeric("1.1.1.1", port);
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
