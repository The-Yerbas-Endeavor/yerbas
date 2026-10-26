// Copyright (c) 2026 The Yerbas developers
// Distributed under the MIT software license, see the accompanying COPYING file.
#include "llmq/quorums_recovery.h"
#include "chain.h"
#include "chainparams.h"
#include "base58.h"
#include "evo/evodb.h"
#include "hash.h"
#include "key.h"
#include "streams.h"
#include "test/test_yerbas.h"

#include <boost/test/unit_test.hpp>
#include <limits>

struct RecoverySetup : BasicTestingSetup {
    std::vector<CBlockIndex> chain{181};
    std::vector<uint256> hashes{181};
    std::vector<CKey> keys{3};
    llmq::RecoveryPolicy policy;
    llmq::RecoveryRequest request;
    RecoverySetup()
    {
        for (size_t i = 0; i < chain.size(); ++i) {
            hashes[i] = uint256S(strprintf("%064x", i + 1));
            chain[i].nHeight = i;
            chain[i].phashBlock = &hashes[i];
            if (i) chain[i].pprev = &chain[i - 1];
        }
        policy.enabled = true;
        policy.genesisHash = hashes[0];
        for (auto& key : keys) {
            key.MakeNewKey(true);
            policy.authorities.emplace(key.GetPubKey().GetID());
        }
        policy.requiredSignatures = 2;
        policy.dkgInterval = 30;
        policy.maxDuration = 60;
        policy.maxStartDelay = 60;
        policy.maxAnchorAge = 10;
        request.genesisHash = hashes[0];
        request.anchorHeight = 55;
        request.anchorHash = hashes[55];
        request.startHeight = 90;
        request.endHeight = 150;
        Sign(request);
    }
    void Sign(llmq::RecoveryRequest& r)
    {
        r.signatures.clear();
        for (size_t i = 0; i < 2; ++i) {
            std::vector<unsigned char> sig;
            BOOST_REQUIRE(keys[i].SignCompact(r.GetAuthorizationHash(), sig));
            std::array<unsigned char, 65> bytes;
            BOOST_REQUIRE_EQUAL(sig.size(), bytes.size());
            std::copy(sig.begin(), sig.end(), bytes.begin());
            r.signatures.push_back(bytes);
        }
    }
    bool Apply(const llmq::RecoveryRequest& r, llmq::RecoveryState& out, std::string& error)
    {
        return llmq::ApplyRecoveryRequest(r, policy, chain[60], {}, out, error);
    }
};

BOOST_FIXTURE_TEST_SUITE(llmq_recovery_tests, RecoverySetup)

BOOST_AUTO_TEST_CASE(isolated_devnet_identity_and_network_guards)
{
    gArgs.ForceSetArg("-llmqrecoverydevnet", "1");
    for (const auto& network : {CBaseChainParams::MAIN, CBaseChainParams::TESTNET, CBaseChainParams::REGTEST}) {
        BOOST_CHECK_THROW(SelectParams(network), std::runtime_error);
    }
    BOOST_CHECK_THROW(SelectParams(CBaseChainParams::DEVNET), std::runtime_error);
    gArgs.ForceSetArg("-devnet", "recovery-unit-a");
    BOOST_CHECK_THROW(CreateChainParams(CBaseChainParams::DEVNET), std::runtime_error);
    const auto address = CBitcoinAddress(keys[0].GetPubKey().GetID()).ToString();
    gArgs.ForceSetArg("-llmqrecoveryauthority", address);
    auto first = CreateChainParams(CBaseChainParams::DEVNET);
    gArgs.ForceSetArg("-devnet", "recovery-unit-b");
    auto second = CreateChainParams(CBaseChainParams::DEVNET);
    BOOST_CHECK(first->GetConsensus().hashDevnetGenesisBlock != second->GetConsensus().hashDevnetGenesisBlock);
    BOOST_CHECK(!std::equal(first->MessageStart(), first->MessageStart() + 4, second->MessageStart()));
    BOOST_CHECK(first->MineBlocksOnDemand());
    BOOST_CHECK_EQUAL(first->GetConsensus().nCollaterals.getCollateral(1), 4000 * COIN);
    gArgs.ForceRemoveArg("-llmqrecoverydevnet");
    gArgs.ForceRemoveArg("-llmqrecoveryauthority");
    gArgs.ForceRemoveArg("-devnet");
}

BOOST_AUTO_TEST_CASE(parameter_templates_are_owned_and_do_not_mutate_live_consensus)
{
    const auto original = Params().GetConsensus().llmqs.at(Consensus::LLMQ_50_60);
    auto normal = RecoveryType1Params(10, false);
    const auto low = RecoveryType1Params(10, true);
    BOOST_CHECK_EQUAL(normal.size, 10);
    BOOST_CHECK_EQUAL(normal.threshold, 7);
    BOOST_CHECK_EQUAL(low.size, 200);
    BOOST_CHECK_EQUAL(low.threshold, 2);
    normal.size = 123;
    BOOST_CHECK_EQUAL(RecoveryType1Params(10, false).size, 10);
    BOOST_CHECK_EQUAL(RecoveryType1Params(100, false).threshold, 30);
    BOOST_CHECK_EQUAL(RecoveryType1Params(3, false).size, 3);
    BOOST_CHECK_EQUAL(Params().GetConsensus().llmqs.at(Consensus::LLMQ_50_60).size, original.size);
}

BOOST_AUTO_TEST_CASE(recorded_profiles_cover_every_dynamic_type)
{
    for (bool testnet : {false, true}) {
        for (size_t count : {0U, 4U, 5U, 99U, 100U, 599U, 600U, 1000U}) {
            for (auto type : {Consensus::LLMQ_50_60, Consensus::LLMQ_400_60, Consensus::LLMQ_400_85}) {
                Consensus::LLMQParams normal, low;
                BOOST_REQUIRE(RecoveryDynamicParams(type, count, false, testnet, normal));
                BOOST_REQUIRE(RecoveryDynamicParams(type, count, true, testnet, low));
                BOOST_CHECK_EQUAL(normal.type, type);
                BOOST_CHECK_EQUAL(low.type, type);
                if (type == Consensus::LLMQ_50_60) {
                    BOOST_CHECK_EQUAL(normal.size, count < 5 ? 3 : (count < 100 ? 10 : 50));
                    BOOST_CHECK_EQUAL(low.size, 200);
                    BOOST_CHECK_EQUAL(low.threshold, 2);
                } else {
                    BOOST_CHECK_EQUAL(normal.size, count < 5 && testnet ? 5 : (count < 100 ? 20 : (count < 600 ? 40 : 400)));
                    BOOST_CHECK_EQUAL(normal.size, low.size);
                    BOOST_CHECK_EQUAL(normal.threshold, low.threshold);
                }
                BOOST_CHECK_EQUAL(normal.dkgInterval, low.dkgInterval);
                BOOST_CHECK_EQUAL(normal.dkgInterval, type == Consensus::LLMQ_50_60 ? 30 : (type == Consensus::LLMQ_400_60 ? 360 : 720));
                const auto expected = normal.size;
                normal.size = 9999;
                BOOST_REQUIRE(RecoveryDynamicParams(type, count, false, testnet, normal));
                BOOST_CHECK_EQUAL(normal.size, expected);
            }
        }
    }
    auto fixed = RecoveryType1Params(0, false);
    BOOST_CHECK(!RecoveryDynamicParams(Consensus::LLMQ_5_60, 1000, true, false, fixed));
    BOOST_CHECK_EQUAL(fixed.size, 3);
}

BOOST_AUTO_TEST_CASE(authenticated_window_expiry_and_serialization)
{
    llmq::RecoveryState state;
    std::string error;
    BOOST_REQUIRE(Apply(request, state, error));
    BOOST_CHECK(error.empty());
    BOOST_CHECK(!state.IsLowAt(89));
    BOOST_CHECK(state.IsLowAt(90));
    BOOST_CHECK(state.IsLowAt(149));
    BOOST_CHECK(!state.IsLowAt(150));
    BOOST_CHECK(!state.IsLowAt(180));
    BOOST_CHECK(state.AllowsRecoverySigning(120, 149));
    BOOST_CHECK(!state.AllowsRecoverySigning(120, 150));
    BOOST_CHECK(!state.AllowsRecoverySigning(60, 100));
    BOOST_CHECK(!state.AllowsRecoverySigning(120, 119));
    CDataStream stream(SER_DISK, PROTOCOL_VERSION);
    stream << request << state;
    llmq::RecoveryRequest decoded;
    llmq::RecoveryState restored, applied;
    stream >> decoded >> restored;
    BOOST_CHECK(stream.empty());
    BOOST_CHECK(decoded.GetAuthorizationHash() == request.GetAuthorizationHash());
    BOOST_REQUIRE(Apply(decoded, applied, error));
    BOOST_CHECK(restored.lastAuthorization == applied.lastAuthorization);
    BOOST_CHECK_EQUAL(restored.startHeight, applied.startHeight);
    BOOST_CHECK_EQUAL(restored.endHeight, applied.endHeight);
    BOOST_CHECK(restored.IsLowAt(90));
    BOOST_CHECK(!restored.IsLowAt(150));
}

BOOST_AUTO_TEST_CASE(manual_authorization_requires_explicit_off_and_new_on)
{
    auto on = request;
    on.version = 2;
    on.endHeight = 0;
    Sign(on);
    llmq::RecoveryState active;
    std::string error;
    BOOST_REQUIRE(Apply(on, active, error));
    BOOST_CHECK(!active.IsLowAt(89));
    BOOST_CHECK(active.IsLowAt(90));
    BOOST_CHECK(active.IsLowAt(std::numeric_limits<int>::max()));
    BOOST_CHECK(active.AllowsRecoverySigning(90, 1000000));
    auto off = on;
    off.previousAuthorization = active.lastAuthorization;
    off.anchorHeight = 120;
    off.anchorHash = hashes[120];
    off.startHeight = off.endHeight = 150;
    Sign(off);
    llmq::RecoveryState closed;
    BOOST_REQUIRE(llmq::ApplyRecoveryRequest(off, policy, chain[120], active, closed, error));
    BOOST_CHECK_EQUAL(closed.startHeight, 90);
    BOOST_CHECK(closed.IsLowAt(149));
    BOOST_CHECK(!closed.IsLowAt(150));
    BOOST_CHECK(!closed.AllowsRecoverySigning(90, 150));
    llmq::RecoveryState ignored;
    BOOST_CHECK(!llmq::ApplyRecoveryRequest(off, policy, chain[120], closed, ignored, error));
    BOOST_CHECK_EQUAL(error, "recovery-sequence");
    auto again = on;
    again.previousAuthorization = closed.lastAuthorization;
    again.anchorHeight = 150;
    again.anchorHash = hashes[150];
    again.startHeight = 180;
    Sign(again);
    BOOST_REQUIRE(llmq::ApplyRecoveryRequest(again, policy, chain[150], closed, ignored, error));
    BOOST_CHECK(!ignored.IsLowAt(179));
    BOOST_CHECK(ignored.IsLowAt(180));
    BOOST_CHECK(!ignored.AllowsRecoverySigning(90, 180));
}

BOOST_AUTO_TEST_CASE(manual_records_reject_unauthorized_and_ambiguous_transitions)
{
    auto on = request;
    on.version = 2;
    on.endHeight = 0;
    Sign(on);
    llmq::RecoveryState active, output;
    std::string error;
    BOOST_REQUIRE(Apply(on, active, error));
    auto bad = on;
    bad.signatures[0].fill(0);
    BOOST_CHECK(!Apply(bad, output, error));
    BOOST_CHECK_EQUAL(error, "recovery-signature");
    bad = on;
    bad.endHeight = bad.startHeight;
    Sign(bad);
    BOOST_CHECK(!Apply(bad, output, error));
    BOOST_CHECK_EQUAL(error, "recovery-manual-state");
    bad = on;
    bad.previousAuthorization = active.lastAuthorization;
    bad.startHeight = bad.endHeight = 120;
    Sign(bad);
    BOOST_CHECK(!llmq::ApplyRecoveryRequest(bad, policy, chain[60], active, output, error));
    BOOST_CHECK_EQUAL(error, "recovery-window-outstanding");
    bad.anchorHeight = 90;
    bad.anchorHash = hashes[90];
    bad.endHeight = 0; // redundant ON after the first ON became effective
    Sign(bad);
    BOOST_CHECK(!llmq::ApplyRecoveryRequest(bad, policy, chain[90], active, output, error));
    BOOST_CHECK_EQUAL(error, "recovery-manual-state");
    bad.version = 1;
    bad.endHeight = 150;
    Sign(bad);
    BOOST_CHECK(!llmq::ApplyRecoveryRequest(bad, policy, chain[90], active, output, error));
    BOOST_CHECK_EQUAL(error, "recovery-window-outstanding");
}

BOOST_AUTO_TEST_CASE(reject_untrusted_authorizations_without_state_mutation)
{
    llmq::RecoveryState sentinel;
    sentinel.lastAuthorization = uint256S("ff");
    sentinel.startHeight = 300;
    sentinel.endHeight = 330;
    auto reject = [&](const llmq::RecoveryRequest& r, const std::string& reason) {
        auto output = sentinel;
        std::string error;
        BOOST_CHECK(!Apply(r, output, error));
        BOOST_CHECK_EQUAL(error, reason);
        BOOST_CHECK(output.lastAuthorization == sentinel.lastAuthorization);
        BOOST_CHECK_EQUAL(output.startHeight, sentinel.startHeight);
        BOOST_CHECK_EQUAL(output.endHeight, sentinel.endHeight);
    };
    auto bad = request;
    bad.genesisHash = uint256S("02"); reject(bad, "recovery-network");
    bad = request; bad.version = 3; reject(bad, "recovery-version");
    bad = request; bad.previousAuthorization = uint256S("03"); reject(bad, "recovery-sequence");
    bad = request; bad.anchorHash = uint256S("04"); reject(bad, "recovery-anchor");
    bad = request; bad.anchorHeight = -1; reject(bad, "recovery-anchor-height");
    policy.minAnchorHeight = 56; reject(request, "recovery-anchor-height");
    policy.minAnchorHeight = 0;
    bad = request; bad.anchorHeight = 61; reject(bad, "recovery-anchor-height");
    bad = request; bad.anchorHeight = 49; reject(bad, "recovery-anchor-height");
    bad = request; bad.signatures.resize(1); reject(bad, "recovery-signature-count");
    bad = request; bad.signatures[1] = bad.signatures[0]; reject(bad, "recovery-duplicate-signer");
    bad = request; bad.signatures[0].fill(0); reject(bad, "recovery-signature");
    bad = request; bad.endHeight = 120; reject(bad, "recovery-signature"); // tampered signed field
    bad = request;
    CKey outsider; outsider.MakeNewKey(true);
    std::vector<unsigned char> sig;
    BOOST_REQUIRE(outsider.SignCompact(bad.GetAuthorizationHash(), sig));
    std::copy(sig.begin(), sig.end(), bad.signatures[0].begin());
    reject(bad, "recovery-signature");
    bad = request;
    // A signature over the serialized unsigned fields lacks our domain prefix.
    CHashWriter writer(SER_GETHASH, PROTOCOL_VERSION);
    writer << bad.version << bad.genesisHash << bad.previousAuthorization << bad.anchorHeight
           << bad.anchorHash << bad.startHeight << bad.endHeight;
    BOOST_REQUIRE(keys[0].SignCompact(writer.GetHash(), sig));
    std::copy(sig.begin(), sig.end(), bad.signatures[0].begin());
    reject(bad, "recovery-signature");
    policy.enabled = false; reject(request, "recovery-disabled");
}

BOOST_AUTO_TEST_CASE(bounded_windows_and_authority_policy)
{
    llmq::RecoveryState output;
    std::string error;
    for (const auto& bounds : std::vector<std::pair<int, int>>{
             {60, 120}, {61, 120}, {91, 150}, {90, 149}, {90, 90}, {90, 180},
             {150, 180}, {-30, 30}, {std::numeric_limits<int>::max(), std::numeric_limits<int>::max()}}) {
        auto bad = request;
        bad.startHeight = bounds.first; bad.endHeight = bounds.second;
        BOOST_CHECK(!Apply(bad, output, error));
        BOOST_CHECK_EQUAL(error, "recovery-window");
    }
    for (size_t required : {size_t(0), size_t(1), size_t(4)}) {
        policy.requiredSignatures = required;
        BOOST_CHECK(!Apply(request, output, error));
        BOOST_CHECK_EQUAL(error, "recovery-invalid-policy");
    }
    policy.requiredSignatures = 2;
    policy.dkgInterval = 0;
    BOOST_CHECK(!Apply(request, output, error));
    BOOST_CHECK_EQUAL(error, "recovery-invalid-policy");
}

BOOST_AUTO_TEST_CASE(branch_binding_and_reauthorization_after_expiry)
{
    llmq::RecoveryState state, output;
    std::string error;
    BOOST_REQUIRE(Apply(request, state, error));
    BOOST_CHECK(!llmq::ApplyRecoveryRequest(request, policy, chain[60], state, output, error));
    BOOST_CHECK_EQUAL(error, "recovery-sequence");
    auto fork = chain;
    uint256 forkHash = uint256S("ffff");
    fork[55].phashBlock = &forkHash;
    for (size_t i = 1; i < fork.size(); ++i) fork[i].pprev = &fork[i - 1];
    BOOST_CHECK(!llmq::ApplyRecoveryRequest(request, policy, fork[60], {}, output, error));
    BOOST_CHECK_EQUAL(error, "recovery-anchor");
    // A separate branch's parent state has no authorization. Replaying the
    // valid branch remains deterministic, without process-global state.
    BOOST_REQUIRE(llmq::ApplyRecoveryRequest(request, policy, chain[60], {}, output, error));
    BOOST_CHECK(output.lastAuthorization == state.lastAuthorization);
    auto subsequent = request;
    subsequent.previousAuthorization = state.lastAuthorization;
    subsequent.startHeight = 150; subsequent.endHeight = 180;
    subsequent.anchorHeight = 115; subsequent.anchorHash = hashes[115];
    Sign(subsequent);
    BOOST_CHECK(!llmq::ApplyRecoveryRequest(subsequent, policy, chain[120], state, output, error));
    BOOST_CHECK_EQUAL(error, "recovery-window-outstanding");
    subsequent.startHeight = 180; subsequent.endHeight = 210;
    subsequent.anchorHeight = 145; subsequent.anchorHash = hashes[145];
    Sign(subsequent);
    BOOST_REQUIRE(llmq::ApplyRecoveryRequest(subsequent, policy, chain[150], state, output, error));
    BOOST_CHECK(!output.IsLowAt(150));
    BOOST_CHECK(output.IsLowAt(180));
    BOOST_CHECK(!output.IsLowAt(210));
    // The old quorum remains expired even after another window is authorized.
    BOOST_CHECK(!state.AllowsRecoverySigning(120, 180));
    BOOST_CHECK(!output.AllowsRecoverySigning(120, 180));
}

BOOST_AUTO_TEST_CASE(signature_serialization_is_bounded)
{
    auto excessive = request;
    excessive.signatures.resize(llmq::RecoveryRequest::MAX_SIGNERS + 1);
    CDataStream stream(SER_NETWORK, PROTOCOL_VERSION);
    BOOST_CHECK_THROW(stream << excessive, std::ios_base::failure);
    // The oversized count was written, but its signatures were not. Reading
    // must reject before allocating or consuming arbitrary signature vectors.
    llmq::RecoveryRequest decoded;
    BOOST_CHECK_THROW(stream >> decoded, std::ios_base::failure);
    BOOST_CHECK(decoded.signatures.empty());
}

BOOST_AUTO_TEST_CASE(experimental_protocol_is_opt_in_and_regtest_only)
{
    SelectParams(CBaseChainParams::MAIN);
    BOOST_CHECK(llmq::GetRecoveryPolicy().activationByRecord);
    gArgs.ForceSetArg("-llmqrecoverytest", "1");
    BOOST_CHECK(llmq::GetRecoveryPolicy().activationByRecord);
    for (const auto& network : {CBaseChainParams::MAIN, CBaseChainParams::TESTNET, CBaseChainParams::DEVNET}) {
        BOOST_CHECK_THROW(SelectParams(network), std::runtime_error);
    }
    SelectParams(CBaseChainParams::REGTEST);
    BOOST_CHECK(llmq::RecoveryProtocolEnabled());
    BOOST_CHECK(llmq::GetRecoveryPolicy().enabled);
    gArgs.ForceRemoveArg("-llmqrecoverytest");
    BOOST_CHECK(!llmq::RecoveryProtocolEnabled());
}

BOOST_AUTO_TEST_CASE(database_replay_forks_and_atomic_rollback)
{
    llmq::RecoveryStateStore store(*evoDb, policy);
    std::string error;
    llmq::RecoveryState state;
    BOOST_CHECK(!store.ConnectBlock(chain[61], &request, error));
    BOOST_CHECK_EQUAL(error, "recovery-parent-state-missing");
    {
        auto transaction = evoDb->BeginTransaction();
        for (size_t i = 1; i < chain.size(); ++i) {
            BOOST_REQUIRE(store.ConnectBlock(chain[i], i == 61 ? &request : nullptr, error));
        }
        transaction->Commit();
    }
    BOOST_REQUIRE(evoDb->CommitRootTransaction());
    // A new manager reads only serialized database state, with no live cache.
    llmq::RecoveryStateStore reopened(*evoDb, policy);
    BOOST_REQUIRE(reopened.ReadState(chain[89], state));
    BOOST_CHECK(!state.IsLowAt(89));
    BOOST_REQUIRE(reopened.ReadState(chain[90], state));
    BOOST_CHECK(state.IsLowAt(90));
    BOOST_REQUIRE(reopened.ReadState(chain[150], state));
    BOOST_CHECK(!state.IsLowAt(150));
    BOOST_CHECK(!state.AllowsRecoverySigning(120, 150));
    BOOST_CHECK(!reopened.ConnectBlock(chain[61], nullptr, error));
    BOOST_CHECK_EQUAL(error, "recovery-state-conflict");
    CBlockIndex fork = chain[61];
    uint256 forkHash = uint256S("abc");
    fork.phashBlock = &forkHash;
    {
        auto transaction = evoDb->BeginTransaction();
        BOOST_REQUIRE(reopened.ConnectBlock(fork, nullptr, error));
        BOOST_REQUIRE(reopened.ReadState(fork, state));
        BOOST_CHECK(!state.IsLowAt(90));
        // No commit: the candidate branch's state must disappear atomically.
    }
    BOOST_CHECK(!reopened.ReadState(fork, state));
    {
        auto transaction = evoDb->BeginTransaction();
        BOOST_REQUIRE(reopened.ConnectBlock(fork, nullptr, error));
        transaction->Commit();
    }
    BOOST_REQUIRE(reopened.ReadState(fork, state));
    BOOST_CHECK(!state.IsLowAt(90));
    BOOST_REQUIRE(reopened.ReadState(chain[61], state));
    BOOST_CHECK(state.IsLowAt(90));
    {
        auto transaction = evoDb->BeginTransaction();
        BOOST_REQUIRE(reopened.DisconnectBlock(chain[180]));
        BOOST_CHECK(!reopened.ReadState(chain[180], state));
        // Failed disconnect rolls back without losing the old branch state.
    }
    BOOST_REQUIRE(reopened.ReadState(chain[180], state));
    {
        auto transaction = evoDb->BeginTransaction();
        BOOST_REQUIRE(reopened.DisconnectBlock(chain[180]));
        transaction->Commit();
    }
    BOOST_CHECK(!reopened.ReadState(chain[180], state));
    BOOST_REQUIRE(reopened.ReadState(chain[179], state));
    BOOST_REQUIRE(reopened.ConnectBlock(chain[180], nullptr, error));
    BOOST_REQUIRE(reopened.ReadState(chain[180], state));
    BOOST_CHECK_EQUAL(state.endHeight, 150);
    auto disabled = policy;
    disabled.enabled = false;
    llmq::RecoveryStateStore inactive(*evoDb, disabled);
    BOOST_CHECK(!inactive.ReadState(chain[180], state));
    BOOST_CHECK(!inactive.ConnectBlock(chain[180], nullptr, error));
    BOOST_CHECK_EQUAL(error, "recovery-disabled");
}

BOOST_AUTO_TEST_CASE(cutover_bootstrap_is_anchored_and_never_masks_missing_history)
{
    policy.activationHeight = 60;
    policy.legacyAnchorHeight = 30;
    policy.legacyAnchorHash = hashes[30];
    llmq::RecoveryStateStore store(*evoDb, policy);
    llmq::RecoveryState state, next;
    std::string error;
    BOOST_CHECK(!store.ReadState(chain[58], state));
    BOOST_REQUIRE(store.ReadState(chain[59], state));
    BOOST_CHECK(state.lastAuthorization.IsNull());
    BOOST_CHECK(!state.IsLowAt(90));
    BOOST_CHECK(!store.ReadState(chain[60], state));
    BOOST_CHECK(!store.ConnectBlock(chain[59], nullptr, error));
    BOOST_CHECK_EQUAL(error, "recovery-before-activation");
    BOOST_CHECK(!store.DisconnectBlock(chain[59]));

    auto on = request;
    on.version = 2;
    on.anchorHeight = 59;
    on.anchorHash = hashes[59];
    on.endHeight = 0;
    Sign(on);
    BOOST_CHECK(!llmq::ApplyRecoveryRequest(on, policy, chain[58], {}, next, error));
    BOOST_CHECK_EQUAL(error, "recovery-before-activation");
    auto old = request;
    old.anchorHeight = 59;
    old.anchorHash = hashes[59];
    Sign(old);
    BOOST_CHECK(!llmq::ApplyRecoveryRequest(old, policy, chain[59], {}, next, error));
    BOOST_CHECK_EQUAL(error, "recovery-version");
    auto stale = on;
    stale.anchorHeight = 55;
    stale.anchorHash = hashes[55];
    Sign(stale);
    BOOST_CHECK(!llmq::ApplyRecoveryRequest(stale, policy, chain[59], {}, next, error));
    BOOST_CHECK_EQUAL(error, "recovery-anchor-height");
    auto wrongPolicy = policy;
    wrongPolicy.legacyAnchorHash = uint256S("dead");
    llmq::RecoveryStateStore wrong(*evoDb, wrongPolicy);
    BOOST_CHECK(!wrong.ReadState(chain[59], state));
    BOOST_CHECK(!llmq::ApplyRecoveryRequest(on, wrongPolicy, chain[59], {}, next, error));
    BOOST_CHECK_EQUAL(error, "recovery-legacy-anchor");
    {
        auto transaction = evoDb->BeginTransaction();
        BOOST_REQUIRE(store.ConnectBlock(chain[60], &on, error));
        BOOST_REQUIRE(store.ReadState(chain[60], state));
        BOOST_CHECK(!state.IsLowAt(89));
        BOOST_CHECK(state.IsLowAt(90));
        // Abandoning candidate validation must not persist authorization.
    }
    BOOST_CHECK(!store.ReadState(chain[60], state));
    {
        auto transaction = evoDb->BeginTransaction();
        BOOST_REQUIRE(store.ConnectBlock(chain[60], &on, error));
        transaction->Commit();
    }
    BOOST_REQUIRE(evoDb->CommitRootTransaction());
    llmq::RecoveryStateStore reopened(*evoDb, policy);
    BOOST_REQUIRE(reopened.ReadState(chain[60], state));
    BOOST_CHECK(state.lastAuthorization == on.GetAuthorizationHash());
    BOOST_CHECK(!reopened.ConnectBlock(chain[62], nullptr, error));
    BOOST_CHECK_EQUAL(error, "recovery-parent-state-missing");
    BOOST_REQUIRE(reopened.ConnectBlock(chain[61], nullptr, error));
    BOOST_REQUIRE(reopened.DisconnectBlock(chain[61]));
    BOOST_REQUIRE(reopened.DisconnectBlock(chain[60]));
    BOOST_CHECK(!reopened.ReadState(chain[60], state));
    BOOST_REQUIRE(reopened.ReadState(chain[59], state));
    BOOST_CHECK(!state.IsLowAt(90));
    // A different branch can cross activation without inheriting the ON record.
    CBlockIndex fork = chain[60];
    uint256 forkHash = uint256S("abcd");
    fork.phashBlock = &forkHash;
    BOOST_REQUIRE(reopened.ConnectBlock(fork, nullptr, error));
    BOOST_REQUIRE(reopened.ReadState(fork, state));
    BOOST_CHECK(!state.IsLowAt(90));
    BOOST_CHECK(state.lastAuthorization.IsNull());
}

BOOST_AUTO_TEST_CASE(deferred_cutover_override_is_regtest_only)
{
    gArgs.ForceSetArg("-llmqrecoveryactivationheight", "90");
    for (const auto& network : {CBaseChainParams::MAIN, CBaseChainParams::TESTNET, CBaseChainParams::DEVNET, CBaseChainParams::REGTEST})
        BOOST_CHECK_THROW(SelectParams(network), std::runtime_error);
    gArgs.ForceSetArg("-llmqrecoverytest", "1");
    for (const auto& height : {"-30", "31", "2147483648"}) {
        gArgs.ForceSetArg("-llmqrecoveryactivationheight", height);
        BOOST_CHECK_THROW(SelectParams(CBaseChainParams::REGTEST), std::runtime_error);
    }
    gArgs.ForceSetArg("-llmqrecoveryactivationheight", "90");
    SelectParams(CBaseChainParams::REGTEST);
    const auto rules = llmq::GetRecoveryPolicy();
    BOOST_CHECK(rules.enabled);
    BOOST_CHECK_EQUAL(rules.activationHeight, 90);
    BOOST_CHECK_EQUAL(rules.legacyAnchorHeight, 0);
    BOOST_CHECK(rules.legacyAnchorHash == rules.genesisHash);
    gArgs.ForceRemoveArg("-llmqrecoveryactivationheight");
    gArgs.ForceRemoveArg("-llmqrecoverytest");
}

BOOST_AUTO_TEST_CASE(release_cutover_guards_and_legacy_retirement)
{
    gArgs.ForceSetArg("-llmqrecoverycutoverheight", "720");
    for (const auto& network : {CBaseChainParams::MAIN, CBaseChainParams::TESTNET, CBaseChainParams::DEVNET})
        BOOST_CHECK_THROW(SelectParams(network), std::runtime_error);
    for (const auto& height : {"-1", "0", "30", "721", "2147483648"}) {
        gArgs.ForceSetArg("-llmqrecoverycutoverheight", height);
        BOOST_CHECK_THROW(SelectParams(CBaseChainParams::REGTEST), std::runtime_error);
    }
    gArgs.ForceSetArg("-llmqrecoverycutoverheight", "720");
    SelectParams(CBaseChainParams::REGTEST);
    BOOST_CHECK(llmq::RecoveryProtocolEnabled());
    BOOST_CHECK(!llmq::RecoveryUsesRecordedParams(719));
    BOOST_CHECK(llmq::RecoveryUsesRecordedParams(720));
    BOOST_CHECK_EQUAL(llmq::GetRecoveryPolicy().activationHeight, 720);
    BOOST_CHECK(!llmq::RecoveryLegacyQuorumRetired(690, 719));
    BOOST_CHECK(llmq::RecoveryLegacyQuorumRetired(690, 720));
    BOOST_CHECK(llmq::RecoveryLegacyQuorumRetired(690, 1000));
    BOOST_CHECK(!llmq::RecoveryLegacyQuorumRetired(720, 1000));
    gArgs.ForceRemoveArg("-llmqrecoverycutoverheight");
    for (const auto& network : {CBaseChainParams::MAIN, CBaseChainParams::TESTNET}) {
        SelectParams(network);
        BOOST_CHECK_EQUAL(Params().GetConsensus().nLLMQRecoveryHeight, -1);
        BOOST_CHECK(llmq::RecoveryProtocolEnabled());
        BOOST_CHECK(llmq::GetRecoveryPolicy().activationByRecord);
        BOOST_CHECK(!llmq::RecoveryUsesRecordedParams(1000000));
    }
    SelectParams(CBaseChainParams::REGTEST);
}

BOOST_AUTO_TEST_CASE(record_activation_override_is_isolated)
{
    gArgs.ForceSetArg("-llmqrecoverybyrecord", "1");
    for (const auto& network : {CBaseChainParams::MAIN, CBaseChainParams::TESTNET, CBaseChainParams::DEVNET})
        BOOST_CHECK_THROW(SelectParams(network), std::runtime_error);
    SelectParams(CBaseChainParams::REGTEST);
    BOOST_CHECK(llmq::GetRecoveryPolicy().activationByRecord);
    BOOST_CHECK_EQUAL(Params().GetConsensus().nLLMQRecoveryHeight, -1);
    gArgs.ForceRemoveArg("-llmqrecoverybyrecord");
    SelectParams(CBaseChainParams::REGTEST);
}

BOOST_AUTO_TEST_CASE(first_signed_record_selects_cutover)
{
    policy.activationByRecord = true;
    policy.maxAnchorAge = 750;
    request.version = 2;
    request.startHeight = 720;
    request.endHeight = 0;
    Sign(request);
    llmq::RecoveryState selected;
    std::string error;
    BOOST_REQUIRE(Apply(request, selected, error));
    BOOST_CHECK_EQUAL(selected.cutoverHeight, 720);
    BOOST_CHECK(!selected.IsLowAt(719));
    BOOST_CHECK(selected.IsLowAt(720));
    auto bad = request;
    bad.startHeight = 90;
    Sign(bad);
    llmq::RecoveryState output;
    BOOST_CHECK(!Apply(bad, output, error));
    BOOST_CHECK_EQUAL(error, "recovery-first-cutover");
    bad = request;
    bad.endHeight = bad.startHeight;
    Sign(bad);
    BOOST_CHECK(!Apply(bad, output, error));
    BOOST_CHECK_EQUAL(error, "recovery-first-cutover");
    bad = request;
    bad.version = 1;
    Sign(bad);
    BOOST_CHECK(!Apply(bad, output, error));
    BOOST_CHECK_EQUAL(error, "recovery-version");
    CDataStream encoded(SER_DISK, PROTOCOL_VERSION);
    encoded << selected;
    encoded >> output;
    BOOST_CHECK_EQUAL(output.cutoverHeight, 720);

    std::vector<CBlockIndex> extended(721);
    std::vector<uint256> extendedHashes(721);
    for (size_t i = 0; i < extended.size(); ++i) {
        extendedHashes[i] = uint256S(strprintf("%064x", i + 1));
        extended[i].nHeight = i;
        extended[i].phashBlock = &extendedHashes[i];
        if (i) extended[i].pprev = &extended[i - 1];
    }
    const auto& parent = extended.back();
    auto off = request;
    off.previousAuthorization = selected.lastAuthorization;
    off.anchorHeight = 720;
    off.anchorHash = parent.GetBlockHash();
    off.startHeight = off.endHeight = 750;
    Sign(off);
    BOOST_REQUIRE(llmq::ApplyRecoveryRequest(off, policy, parent, selected, output, error));
    BOOST_CHECK_EQUAL(output.cutoverHeight, 720);
    BOOST_CHECK(output.IsLowAt(749));
    BOOST_CHECK(!output.IsLowAt(750));
}

BOOST_AUTO_TEST_SUITE_END()
