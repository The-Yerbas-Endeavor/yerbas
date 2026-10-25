// Copyright (c) 2026 The Yerbas developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include "chainparams.h"
#include "coins.h"
#include "consensus/consensus.h"
#include "consensus/tx_verify.h"
#include "consensus/validation.h"
#include "evo/deterministicmns.h"
#include "key.h"
#include "util.h"
#include "llmq/quorums_commitment.h"
#include "llmq/quorums_dkgsessionhandler.h"
#include "llmq/quorums_utils.h"
#include "primitives/block.h"
#include "streams.h"
#include "version.h"

#include "test/test_yerbas.h"

#include <boost/test/unit_test.hpp>

struct RegtestChainParamsSetup : BasicTestingSetup {
    RegtestChainParamsSetup() : BasicTestingSetup(CBaseChainParams::REGTEST) {}
};

BOOST_FIXTURE_TEST_SUITE(chainparams_tests, RegtestChainParamsSetup)

BOOST_AUTO_TEST_CASE(regtest_null_quorum_commitments)
{
    const auto& consensus = Params().GetConsensus();
    // First-registration block assembly must start with the adaptive zero-node size.
    BOOST_CHECK_EQUAL(consensus.llmqs.at(Consensus::LLMQ_50_60).size, 3);
    BOOST_CHECK_EQUAL(consensus.llmqTypeChainLocks, Consensus::LLMQ_5_60);
    BOOST_CHECK_EQUAL(consensus.llmqTypeInstantSend, Consensus::LLMQ_5_60);
    BOOST_CHECK_EQUAL(consensus.llmqs.at(Consensus::LLMQ_5_60).size, 3);
    BOOST_CHECK_EQUAL(consensus.llmqs.at(Consensus::LLMQ_5_60).minSize, 2);
    BOOST_CHECK_EQUAL(consensus.llmqs.at(Consensus::LLMQ_5_60).threshold, 2);

    for (const auto& entry : consensus.llmqs) {
        BOOST_TEST_CONTEXT("registered quorum type=" << static_cast<int>(entry.first)) {
            // The serialized commitment must identify the same parameter set
            // that sized its signer/member vectors, including null commitments.
            BOOST_CHECK_EQUAL(static_cast<int>(entry.first), static_cast<int>(entry.second.type));
            const llmq::CFinalCommitment commitment(entry.second, uint256S("01"));
            BOOST_CHECK_EQUAL(static_cast<int>(commitment.llmqType), static_cast<int>(entry.first));
            BOOST_CHECK(commitment.IsNull());
            BOOST_CHECK(commitment.VerifyNull());

            CDataStream stream(SER_NETWORK, PROTOCOL_VERSION);
            stream << commitment;
            llmq::CFinalCommitment decoded;
            stream >> decoded;
            BOOST_CHECK_EQUAL(static_cast<int>(decoded.llmqType), static_cast<int>(entry.first));
            BOOST_CHECK(decoded.IsNull());
            BOOST_CHECK(decoded.VerifyNull());
        }
    }
}

BOOST_AUTO_TEST_CASE(real_dkg_fixture_is_explicit_and_regtest_only)
{
    const auto ordinary = CreateChainParams(CBaseChainParams::REGTEST);
    BOOST_CHECK_EQUAL(ordinary->GetConsensus().nPowDGWHeight, 60);
    BOOST_CHECK_EQUAL(ordinary->GetConsensus().nCollaterals.getCollateral(1), 0);
    gArgs.ForceSetArg("-llmqtestfixture", "1");
    const auto fixture = CreateChainParams(CBaseChainParams::REGTEST);
    BOOST_CHECK_EQUAL(fixture->GetConsensus().nPowDGWHeight, INT_MAX);
    BOOST_CHECK_EQUAL(fixture->GetConsensus().nCollaterals.getCollateral(1), 10 * COIN);
    BOOST_CHECK_EQUAL(fixture->GetConsensus().nSmartnodePaymentsStartBlock, 1);
    for (const auto& network : {CBaseChainParams::MAIN, CBaseChainParams::TESTNET, CBaseChainParams::DEVNET}) {
        BOOST_CHECK_THROW(SelectParams(network), std::runtime_error);
    }
    gArgs.ForceRemoveArg("-llmqtestfixture");
}

BOOST_AUTO_TEST_CASE(public_network_small_quorum_parameters)
{
    // Regtest needs its own type ID. The shared three-member parameters used
    // on mainnet/testnet must keep their existing ID, sizes, and thresholds.
    for (const auto& network : {CBaseChainParams::MAIN, CBaseChainParams::TESTNET}) {
        const auto params = CreateChainParams(network);
        const auto& quorum = params->GetConsensus().llmqs.at(Consensus::LLMQ_50_60);
        BOOST_TEST_CONTEXT("network=" << network) {
            BOOST_CHECK_EQUAL(quorum.type, Consensus::LLMQ_50_60);
            BOOST_CHECK_EQUAL(quorum.size, 3);
            BOOST_CHECK_EQUAL(quorum.minSize, 2);
            BOOST_CHECK_EQUAL(quorum.threshold, 2);
        }
    }
}

BOOST_AUTO_TEST_CASE(mainnet_checkpoint_matches_archived_block_header)
{
    // Header at height 1078436, independently corroborated by the public
    // explorer. Derive its hash so a mistyped checkpoint cannot self-validate.
    CBlockHeader header;
    header.nVersion = 0x20000000;
    header.hashPrevBlock = uint256S("34eb0b7b0e120d89a0855c81a3c5f748712c8173dd1f828287fdd57f42dbe3ce");
    header.hashMerkleRoot = uint256S("689d68d08e26208d915192b9028ed549b08a930511d91278e5e197db73231d1f");
    header.nTime = 1784431314;
    header.nBits = 0x1e01dc6e;
    header.nNonce = 1731;
    const auto main = CreateChainParams(CBaseChainParams::MAIN);
    BOOST_CHECK(main->Checkpoints().mapCheckpoints.at(1078436) == header.GetHash());
}

BOOST_AUTO_TEST_CASE(explicit_quorum_context_checks_signatures_and_membership)
{
    const auto params = Params().GetConsensus().llmqs.at(Consensus::LLMQ_50_60);
    llmq::CFinalCommitment qc(params, uint256S("01"));
    CBLSSecretKey quorumKey;
    quorumKey.MakeNewKey();
    qc.quorumPublicKey = quorumKey.GetPublicKey();
    qc.quorumVvecHash = uint256S("02");
    std::vector<CBLSSecretKey> keys(2);
    std::vector<CBLSPublicKey> publicKeys;
    std::vector<CDeterministicMNCPtr> members;
    for (size_t i = 0; i < keys.size(); ++i) {
        keys[i].MakeNewKey();
        publicKeys.emplace_back(keys[i].GetPublicKey());
        auto state = std::make_shared<CDeterministicMNState>();
        state->pubKeyOperator.Set(publicKeys.back());
        auto mn = std::make_shared<CDeterministicMN>();
        mn->pdmnState = state;
        members.emplace_back(mn);
        qc.signers[i] = qc.validMembers[i] = true;
    }
    const auto hash = llmq::CLLMQUtils::BuildCommitmentHash(params.type, qc.quorumHash,
                                                         qc.validMembers, qc.quorumPublicKey, qc.quorumVvecHash);
    qc.membersSig = CBLSSignature::AggregateSecure({keys[0].Sign(hash), keys[1].Sign(hash)}, publicKeys, hash);
    qc.quorumSig = quorumKey.Sign(hash);
    BOOST_REQUIRE(qc.Verify(params, members, true));
    BOOST_CHECK(qc.Verify(members, true));
    BOOST_CHECK(!qc.VerifyNull(params));

    auto wrong = params;
    wrong.type = Consensus::LLMQ_400_60;
    BOOST_CHECK(!qc.Verify(wrong, members, true));
    BOOST_CHECK(!llmq::CFinalCommitment(params, uint256S("01")).VerifyNull(wrong));
    wrong = params;
    wrong.size = 200;
    BOOST_CHECK(!qc.Verify(wrong, members, true));
    wrong = params;
    wrong.minSize = 3;
    BOOST_CHECK(!qc.Verify(wrong, members, true));

    auto damaged = qc;
    damaged.quorumSig = quorumKey.Sign(uint256S("03"));
    BOOST_CHECK(!damaged.Verify(params, members, true));
    damaged = qc;
    damaged.membersSig = keys[0].Sign(hash);
    BOOST_CHECK(!damaged.Verify(params, members, true));
    damaged = qc;
    damaged.validMembers[2] = true;
    BOOST_CHECK(!damaged.Verify(params, members, false));
    damaged = qc;
    damaged.signers[2] = true;
    BOOST_CHECK(!damaged.Verify(params, members, false));
    damaged = qc;
    damaged.nVersion = 0;
    BOOST_CHECK(!damaged.Verify(params, members, true));
    auto tooMany = members;
    tooMany.resize(params.size + 1, members[0]);
    BOOST_CHECK(!qc.Verify(params, tooMany, true));
}

BOOST_AUTO_TEST_CASE(private_testnet_collateral_and_maturity_boundaries)
{
    struct Restore {
        ~Restore() { gArgs.ForceSetArg("-testnetfastcollateral", "0"); SelectParams(CBaseChainParams::REGTEST); }
    } restore;
    auto checkMaturity = [](int maturity) {
        CCoinsView base;
        CCoinsViewCache view(&base);
        COutPoint out(uint256S("1234"), 0);
        view.AddCoin(out, Coin(CTxOut(COIN, CScript() << OP_TRUE), 1, true), false);
        CMutableTransaction mtx;
        mtx.vin.emplace_back(out);
        mtx.vout.emplace_back(COIN - 1000, CScript() << OP_TRUE);
        CTransaction tx(mtx);
        CAmount fee = 0, specialFee = 0;
        CValidationState early;
        BOOST_CHECK(!Consensus::CheckTxInputs(tx, early, view, maturity, fee, specialFee, false));
        BOOST_CHECK_EQUAL(early.GetRejectReason(), "bad-txns-premature-spend-of-coinbase");
        CValidationState mature;
        BOOST_CHECK(Consensus::CheckTxInputs(tx, mature, view, maturity + 1, fee, specialFee, false));
        BOOST_CHECK_EQUAL(fee, 1000);
    };
    gArgs.ForceSetArg("-testnetfastcollateral", "0");
    SelectParams(CBaseChainParams::MAIN);
    BOOST_CHECK_EQUAL(GetCoinbaseMaturity(), 100);
    checkMaturity(100);
    SelectParams(CBaseChainParams::TESTNET);
    auto ordinary = CreateChainParams(CBaseChainParams::TESTNET);
    BOOST_CHECK_EQUAL(GetCoinbaseMaturity(), 100);
    BOOST_CHECK_EQUAL(Params().GetConsensus().nCollaterals.getCollateral(100), 4000 * COIN);
    checkMaturity(100);
    gArgs.ForceSetArg("-testnetfastcollateral", "1");
    BOOST_CHECK_THROW(SelectParams(CBaseChainParams::MAIN), std::runtime_error);
    BOOST_CHECK_THROW(SelectParams(CBaseChainParams::REGTEST), std::runtime_error);
    SelectParams(CBaseChainParams::TESTNET);
    BOOST_CHECK_EQUAL(GetCoinbaseMaturity(), 10);
    BOOST_CHECK_EQUAL(Params().GetConsensus().nCollaterals.getCollateral(100), 4 * COIN);
    BOOST_CHECK_EQUAL(Params().GetConsensus().nPowTargetSpacing, 60);
    BOOST_CHECK(!Params().GetConsensus().fPowNoRetargeting);
    BOOST_CHECK(Params().MessageStart()[0] != ordinary->MessageStart()[0]);
    BOOST_CHECK(Params().GetConsensus().hashGenesisBlock == ordinary->GetConsensus().hashGenesisBlock);
    checkMaturity(10);
}

BOOST_AUTO_TEST_SUITE_END()

// Characterization probes, not desired consensus behavior. Run EACH case in a
// separate process: UpdateLLMQParams has process-global caches that SelectParams
// does not reset. Disabled by default to avoid contaminating unrelated tests.
BOOST_FIXTURE_TEST_SUITE(low_llmq_characterization, RegtestChainParamsSetup, *boost::unit_test::disabled())

BOOST_AUTO_TEST_CASE(continuous_historical_windows)
{
    SelectParams(CBaseChainParams::MAIN);
    for (int height = 1; height <= 37651; ++height) {
        UpdateLLMQParams(100, height, false);
        const bool low = (height >= 6759 && height < 8319) ||
                         (height >= 15908 && height < 16401) ||
                         (height >= 22771 && height < 37650);
        BOOST_REQUIRE_EQUAL(Params().GetConsensus().llmqs.at(Consensus::LLMQ_50_60).size, low ? 200 : 50);
    }
}

BOOST_AUTO_TEST_CASE(fresh_historical_boundary)
{
    SelectParams(CBaseChainParams::MAIN);
    UpdateLLMQParams(100, 8319, false);
    // The continuous probe above selects size 50 at this same height/count.
    BOOST_CHECK_EQUAL(Params().GetConsensus().llmqs.at(Consensus::LLMQ_50_60).size, 200);
}

BOOST_AUTO_TEST_CASE(spork_transition_and_backward_lookup)
{
    UpdateLLMQParams(100, 60, false);
    const auto normal = Params().GetConsensus().llmqs.at(Consensus::LLMQ_50_60);
    const llmq::CFinalCommitment historical(normal, uint256S("01"));
    BOOST_REQUIRE(historical.VerifyNull());
    UpdateLLMQParams(100, 61, true);
    BOOST_REQUIRE_EQUAL(Params().GetConsensus().llmqs.at(Consensus::LLMQ_50_60).size, 200);
    // Explicit historical context remains stable after live parameters change.
    BOOST_CHECK(historical.VerifyNull(normal));
    // Exactly the same serialized commitment now fails size validation.
    BOOST_CHECK(!historical.VerifyNull());
    UpdateLLMQParams(100, 60, false);
    BOOST_CHECK_EQUAL(Params().GetConsensus().llmqs.at(Consensus::LLMQ_50_60).size, 200);
    BOOST_CHECK(!historical.VerifyNull());
    UpdateLLMQParams(100, 62, false);
    BOOST_CHECK(historical.VerifyNull(normal));
    BOOST_CHECK(historical.VerifyNull());
}

BOOST_AUTO_TEST_SUITE_END()

BOOST_FIXTURE_TEST_SUITE(low_llmq_pose_tests, RegtestChainParamsSetup)

BOOST_AUTO_TEST_CASE(selected_member_penalties_ban_and_payment_exclusion)
{
    // Regtest has no collateral schedule in this branch. Use the real schedule
    // in an in-memory list, without connecting to a network.
    SelectParams(CBaseChainParams::MAIN);
    CDeterministicMNList list(uint256S("01"), 1, 11);
    for (int i = 0; i < 11; ++i) {
        auto mn = std::make_shared<CDeterministicMN>();
        mn->proTxHash = uint256S(strprintf("%064x", i + 1));
        mn->internalId = i;
        mn->collateralOutpoint = COutPoint(mn->proTxHash, 0);
        mn->nOperatorReward = 0;
        auto state = std::make_shared<CDeterministicMNState>();
        CKey key;
        key.MakeNewKey(true);
        state->keyIDOwner = key.GetPubKey().GetID();
        state->nCollateralAmount = Params().GetConsensus().nCollaterals.getCollateral(0);
        state->UpdateConfirmedHash(mn->proTxHash, uint256S("02"));
        mn->pdmnState = state;
        list.AddMN(mn);
    }
    // Selection has no online/offline input. All confirmed eligible entries fit.
    BOOST_REQUIRE_EQUAL(list.CalculateQuorum(200, uint256S("03")).size(), 11);
    const auto payee = list.GetMNPayee();
    BOOST_REQUIRE(payee);
    const auto target = payee->proTxHash;
    list.PoSePunish(target, list.CalcPenalty(66), false);
    BOOST_CHECK_EQUAL(list.GetMN(target)->pdmnState->nPoSePenalty, 66);
    BOOST_CHECK(!list.IsMNPoSeBanned(target));
    list.PoSeDecrease(target);
    list.PoSePunish(target, list.CalcPenalty(66), false);
    BOOST_CHECK(list.IsMNPoSeBanned(target));
    BOOST_CHECK(!list.IsMNValid(target));
    BOOST_REQUIRE(list.GetMNPayee());
    BOOST_CHECK(list.GetMNPayee()->proTxHash != target);
    BOOST_CHECK_EQUAL(list.CalculateQuorum(200, uint256S("03")).size(), 10);
    // Banning does not remove the registration: an explorer may still list it.
    BOOST_CHECK_EQUAL(list.GetAllMNsCount(), 11);
}

BOOST_AUTO_TEST_SUITE_END()

BOOST_FIXTURE_TEST_SUITE(legacy_dkg_queue_tests, TestingSetup)

BOOST_AUTO_TEST_CASE(resize_across_low_llmq_sessions_retains_peer_limits)
{
    llmq::CDKGPendingMessages queue(6); // Startup 3-member quorum.
    auto push = [&](NodeId peer, int first, int count) {
        for (int i = first; i < first + count; ++i) {
            CDataStream message(SER_NETWORK, PROTOCOL_VERSION);
            message << i;
            queue.PushPendingMessage(peer, message);
        }
    };
    push(1, 0, 7);
    BOOST_CHECK_EQUAL(queue.PopPendingMessages(1000).size(), 6);
    queue.Clear();
    queue.SetMaxMessagesPerNode(400); // LOW_LLMQ: 200 members, two messages each.
    push(1, 1000, 401);
    BOOST_CHECK_EQUAL(queue.PopPendingMessages(1000).size(), 400);
    push(1, 2000, 1); // Popping must not reset this peer's per-session allowance.
    BOOST_CHECK(queue.PopPendingMessages(1000).empty());
    push(2, 2001, 1); // Another peer has an independent allowance.
    BOOST_CHECK_EQUAL(queue.PopPendingMessages(1000).size(), 1);
    queue.Clear();
    queue.SetMaxMessagesPerNode(20); // Return to a normal 10-member quorum.
    push(1, 3000, 21);
    BOOST_CHECK_EQUAL(queue.PopPendingMessages(1000).size(), 20);
}

BOOST_AUTO_TEST_SUITE_END()
