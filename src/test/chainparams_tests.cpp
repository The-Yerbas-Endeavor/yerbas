// Copyright (c) 2026 The Yerbas developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include "chainparams.h"
#include "llmq/quorums_commitment.h"
#include "llmq/quorums_recovery.h"
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

BOOST_AUTO_TEST_CASE(mainnet_pose_recovery_activation_schedule)
{
    const auto main = CreateChainParams(CBaseChainParams::MAIN);
    const auto& p = main->GetConsensus();
    const auto& q = p.llmqs.at(Consensus::LLMQ_100_67);
    BOOST_CHECK_EQUAL(q.size, 100);
    BOOST_CHECK_EQUAL(q.minSize, 80);
    BOOST_CHECK_EQUAL(q.threshold, 67);
    BOOST_CHECK_EQUAL(p.llmqTypePoSe, Consensus::LLMQ_100_67);
    BOOST_CHECK_EQUAL(p.nPoSeQuorumActivationHeight, 1212840);
    BOOST_CHECK_EQUAL(p.nRecoveryActivationHeight, 1214280);
    BOOST_CHECK_EQUAL(p.nRecoveryActivationHeight-p.nPoSeQuorumActivationHeight, llmq::RECOVERY_HISTORY);
    BOOST_CHECK_EQUAL(p.nRecoveryActivationHeight % llmq::RECOVERY_ROTATION, 0);
    BOOST_CHECK(!p.IsLLMQEnabled(Consensus::LLMQ_100_67, 1212839));
    BOOST_CHECK(p.IsLLMQEnabled(Consensus::LLMQ_100_67, 1212840));
    BOOST_CHECK(!llmq::RecoveryEnabled(p, 1214279));
    BOOST_CHECK(llmq::RecoveryEnabled(p, 1214280));
    BOOST_CHECK_EQUAL(llmq::RECOVERY_SIZE, 15U);
    BOOST_CHECK_EQUAL(llmq::RECOVERY_THRESHOLD, 11U);

}

BOOST_AUTO_TEST_CASE(testnet_pose_recovery_activation_schedule)
{
    const auto test = CreateChainParams(CBaseChainParams::TESTNET);
    const auto& p = test->GetConsensus();
    const auto& q = p.llmqs.at(Consensus::LLMQ_100_67);
    BOOST_CHECK_EQUAL(q.size, 100);
    BOOST_CHECK_EQUAL(q.minSize, 80);
    BOOST_CHECK_EQUAL(q.threshold, 67);
    BOOST_CHECK_EQUAL(p.nPoSeQuorumActivationHeight, 4320);
    BOOST_CHECK_EQUAL(p.nRecoveryActivationHeight, 8640);
    BOOST_CHECK(!p.IsLLMQEnabled(Consensus::LLMQ_100_67, 4319));
    BOOST_CHECK(p.IsLLMQEnabled(Consensus::LLMQ_100_67, 4320));
    BOOST_CHECK(!llmq::RecoveryEnabled(p, 8639));
    BOOST_CHECK(llmq::RecoveryEnabled(p, 8640));
    BOOST_CHECK_EQUAL(p.nRecoveryActivationHeight % llmq::RECOVERY_ROTATION, 0);
    BOOST_CHECK_GE(p.nRecoveryActivationHeight-p.nPoSeQuorumActivationHeight, llmq::RECOVERY_HISTORY);
    BOOST_CHECK_EQUAL(p.nPowTargetSpacing, 60);
    BOOST_CHECK_EQUAL(p.nCollaterals.getCollateral(4320), 4000 * COIN);
}

BOOST_AUTO_TEST_SUITE_END()
