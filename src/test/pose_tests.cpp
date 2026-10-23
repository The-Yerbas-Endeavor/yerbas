// Copyright (c) 2026 The Yerbas developers
// Distributed under the MIT software license, see COPYING.
#include "test/test_yerbas.h"
#include "llmq/quorums_pose.h"
#include "llmq/quorums_recovery.h"
#include "llmq/quorums_utils.h"
#include "netbase.h"
#include "arith_uint256.h"
#include <boost/test/unit_test.hpp>
#include <limits>

BOOST_FIXTURE_TEST_SUITE(pose_tests, BasicTestingSetup)

BOOST_AUTO_TEST_CASE(activation_and_fixed_threshold)
{
    auto consensus = Params().GetConsensus();
    const auto& q = consensus.llmqs.at(Consensus::LLMQ_100_67);
    BOOST_CHECK_EQUAL(q.size, 100);
    BOOST_CHECK_EQUAL(q.minSize, 80);
    BOOST_CHECK_EQUAL(q.threshold, 67);
    BOOST_CHECK(!consensus.IsLLMQEnabled(Consensus::LLMQ_100_67, 1000000));
    // The disabled sentinel remains valid for networks without a schedule.
    auto disabled = consensus;
    disabled.nPoSeQuorumActivationHeight = std::numeric_limits<int>::max();
    BOOST_CHECK(!disabled.IsLLMQEnabled(Consensus::LLMQ_100_67, std::numeric_limits<int>::max()));
    BOOST_CHECK(consensus.IsLLMQEnabled(Consensus::LLMQ_50_60, 0));
    consensus.nPoSeQuorumActivationHeight = 61;
    BOOST_CHECK(!consensus.IsLLMQEnabled(Consensus::LLMQ_100_67, 119));
    BOOST_CHECK(consensus.IsLLMQEnabled(Consensus::LLMQ_100_67, 120));
    BOOST_CHECK(!consensus.IsLLMQEnabled(Consensus::LLMQ_100_67, -1));
    BOOST_CHECK(!consensus.IsLLMQEnabled(Consensus::LLMQ_POSE_TEST, 120));
}

BOOST_AUTO_TEST_CASE(observation_windows)
{
    BOOST_CHECK(llmq::CheckPoSeWindow(30, 30, 120));
    BOOST_CHECK(llmq::CheckPoSeWindow(30, 150, 120));
    BOOST_CHECK(!llmq::CheckPoSeWindow(30, 151, 120));
    BOOST_CHECK(!llmq::CheckPoSeWindow(60, 59, 120));
    BOOST_CHECK(!llmq::CheckPoSeWindow(0, 100, 120));
    BOOST_CHECK(!llmq::CheckPoSeWindow(-30, 100, 120));
    BOOST_CHECK(!llmq::CheckPoSeWindow(31, 100, 120));
    BOOST_CHECK(!llmq::CheckPoSeWindow(30, std::numeric_limits<int>::max(), 120));
}

BOOST_AUTO_TEST_CASE(state_binding_ignores_payments_but_invalidates_revival)
{
    CDeterministicMNState state;
    CBLSSecretKey key; key.MakeNewKey();
    state.pubKeyOperator.Set(key.GetPublicKey());
    state.addr = LookupNumeric("1.2.3.4", 15420);
    state.nRegisteredHeight = 10;
    auto hash = llmq::PoSeStateHash(state);
    state.nLastPaidHeight = 20; state.nPoSePenalty = 66;
    BOOST_CHECK(hash == llmq::PoSeStateHash(state));
    auto revived = state; revived.nPoSeRevivedHeight = 30;
    BOOST_CHECK(hash != llmq::PoSeStateHash(revived));
    auto moved = state; moved.addr = LookupNumeric("1.2.3.5", 15420);
    BOOST_CHECK(hash != llmq::PoSeStateHash(moved));
    key.MakeNewKey(); state.pubKeyOperator.Set(key.GetPublicKey());
    BOOST_CHECK(hash != llmq::PoSeStateHash(state));
}

BOOST_AUTO_TEST_CASE(monitor_signature_is_not_quorum_authorization)
{
    llmq::CPoSeReport report;
    report.request.target = uint256S("01"); report.request.height = 60;
    report.request.blockHash = uint256S("02"); report.request.stateHash = uint256S("03");
    CBLSSecretKey monitor; monitor.MakeNewKey();
    report.observer = monitor.GetPublicKey();
    report.signature = monitor.Sign(report.GetSignHash());
    BOOST_CHECK(report.signature.VerifyInsecure(report.observer, report.GetSignHash()));
    llmq::CPoSeCertificate cert;
    cert.request = report.request; cert.quorumHash = uint256S("04"); cert.signature = report.signature;
    BOOST_CHECK(!llmq::VerifyPoSeCertificateSignature(cert, Consensus::LLMQ_100_67, monitor.GetPublicKey()));
    auto altered = report; altered.request.blockHash = uint256S("05");
    BOOST_CHECK(!report.signature.VerifyInsecure(report.observer, altered.GetSignHash()));
}

BOOST_AUTO_TEST_CASE(sixty_seven_shares_required_and_domains_bound)
{
    std::vector<CBLSSecretKey> polynomial(67);
    for (auto& key : polynomial) key.MakeNewKey();
    llmq::CPoSeCertificate cert;
    cert.request.target = uint256S("01"); cert.request.height = 60;
    cert.request.blockHash = uint256S("02"); cert.request.stateHash = uint256S("03");
    cert.quorumHash = uint256S("04");
    auto hash = llmq::CLLMQUtils::BuildSignHash(Consensus::LLMQ_100_67, cert.quorumHash,
                                             cert.request.GetId(), cert.request.GetSignHash());
    std::vector<CBLSSignature> shares;
    std::vector<CBLSId> ids;
    for (int i = 1; i <= 67; ++i) {
        CBLSId id; id.SetInt(i);
        CBLSSecretKey share;
        BOOST_REQUIRE(share.SecretKeyShare(polynomial, id));
        shares.push_back(share.Sign(hash)); ids.push_back(id);
        if (i == 66) {
            cert.signature.Recover(shares, ids);
            BOOST_CHECK(!llmq::VerifyPoSeCertificateSignature(cert, Consensus::LLMQ_100_67, polynomial[0].GetPublicKey()));
        }
    }
    BOOST_REQUIRE(cert.signature.Recover(shares, ids));
    auto pk = polynomial[0].GetPublicKey();
    BOOST_CHECK(llmq::VerifyPoSeCertificateSignature(cert, Consensus::LLMQ_100_67, pk));
    BOOST_CHECK(!llmq::VerifyPoSeCertificateSignature(cert, Consensus::LLMQ_400_60, pk));
    for (int field = 0; field < 5; ++field) {
        auto changed = cert;
        if (field == 0) changed.request.target = uint256S("10");
        if (field == 1) changed.request.height = 90;
        if (field == 2) changed.request.blockHash = uint256S("20");
        if (field == 3) changed.request.stateHash = uint256S("30");
        if (field == 4) changed.quorumHash = uint256S("40");
        BOOST_CHECK(!llmq::VerifyPoSeCertificateSignature(changed, Consensus::LLMQ_100_67, pk));
    }
    // The persisted certificate round trips without weakening verification.
    CDataStream stream(SER_DISK, PROTOCOL_VERSION); stream << cert;
    llmq::CPoSeCertificate restored; stream >> restored;
    BOOST_CHECK(llmq::VerifyPoSeCertificateSignature(restored, Consensus::LLMQ_100_67, pk));
}


BOOST_AUTO_TEST_CASE(recovery_threshold_and_replay_domains)
{
    auto p=Params().GetConsensus();
    llmq::CRecoveryRoster roster;
    std::vector<CBLSSecretKey> keys(15);
    for (int i=0;i<15;++i) {
        keys[i].MakeNewKey();
        roster.members.push_back({ArithToUint256(arith_uint256(i+1)),uint256S("01"),keys[i].GetPublicKey()});
    }
    llmq::CRecoveryCertificate c;
    c.committee=roster.GetHash(p); c.epoch=uint256S("01"); c.target=uint256S("02");
    for (int i=0;i<10;++i) c.signatures.emplace_back(i,keys[i].Sign(c.SignHash(p)));
    BOOST_CHECK(!c.VerifySignatures(p,roster));
    c.signatures.emplace_back(10,keys[10].Sign(c.SignHash(p)));
    BOOST_CHECK(c.VerifySignatures(p,roster));
    auto bad=c; bad.signatures[10].first=9; BOOST_CHECK(!bad.VerifySignatures(p,roster));
    bad=c; bad.target=uint256S("03"); BOOST_CHECK(!bad.VerifySignatures(p,roster));
    bad=c; bad.version=1; BOOST_CHECK(!bad.VerifySignatures(p,roster));
    for(auto field:{&llmq::CRecoveryCertificate::committee,&llmq::CRecoveryCertificate::epoch,
                    &llmq::CRecoveryCertificate::stateHash,&llmq::CRecoveryCertificate::startHash,
                    &llmq::CRecoveryCertificate::endHash}) {
        bad=c;bad.*field=uint256S("99");BOOST_CHECK(!bad.VerifySignatures(p,roster));
    }
    for(auto field:{&llmq::CRecoveryCertificate::start,&llmq::CRecoveryCertificate::end,
                    &llmq::CRecoveryCertificate::expiry}) {
        bad=c;++(bad.*field);BOOST_CHECK(!bad.VerifySignatures(p,roster));
    }
    bad=c;bad.signatures.back().first=255;BOOST_CHECK(!bad.VerifySignatures(p,roster));
    bad=c;std::reverse(bad.signatures.begin(),bad.signatures.end());BOOST_CHECK(!bad.VerifySignatures(p,roster));
    auto other=p; other.hashGenesisBlock=uint256S("05"); BOOST_CHECK(!c.VerifySignatures(other,roster));
    auto changed=roster; changed.members[14]=changed.members[0];
    bad=c;bad.committee=changed.GetHash(p);bad.signatures.clear();
    for(int i=0;i<11;++i)bad.signatures.emplace_back(i,keys[i].Sign(bad.SignHash(p)));
    BOOST_CHECK(!bad.VerifySignatures(p,changed));
    CDataStream stream(SER_NETWORK,PROTOCOL_VERSION); stream<<c;
    llmq::CRecoveryCertificate roundtrip; stream>>roundtrip; BOOST_CHECK(roundtrip.VerifySignatures(p,roster));
}
BOOST_AUTO_TEST_CASE(recovery_recorded_participation)
{
    CBLSSecretKey key;key.MakeNewKey();
    llmq::CRecoveryMember member{uint256S("01"),uint256S("02"),key.GetPublicKey()};
    std::vector<llmq::CRecoveryParticipation> events;
    BOOST_CHECK(!llmq::HasRecoveryParticipation(events,member,1000));
    for(int h:{720,780,840})events.push_back({member,h,true});
    BOOST_CHECK(llmq::HasRecoveryParticipation(events,member,1000));
    // Repeated commitments from the same session do not manufacture history.
    auto duplicates=events;for(auto& event:duplicates)event.session=840;
    BOOST_CHECK(!llmq::HasRecoveryParticipation(duplicates,member,1000));
    BOOST_CHECK(!llmq::HasRecoveryParticipation(events,member,1201));
    auto changed=member;changed.stateHash=uint256S("03");
    BOOST_CHECK(!llmq::HasRecoveryParticipation(events,changed,1000));
    events.push_back({member,900,false});
    BOOST_CHECK(!llmq::HasRecoveryParticipation(events,member,1000)); // 3/4 < 80%
    events.push_back({member,960,true});
    BOOST_CHECK(llmq::HasRecoveryParticipation(events,member,1000)); // 4/5
    auto unrelated=member;unrelated.proTxHash=uint256S("99");
    events.push_back({unrelated,980,false});
    BOOST_CHECK(llmq::HasRecoveryParticipation(events,member,1000));
}
BOOST_AUTO_TEST_CASE(recovery_selection_reproducible_and_fail_closed)
{
    CBLSSecretKey key;key.MakeNewKey();
    std::vector<llmq::CRecoveryMember> candidates;
    for(int i=0;i<30;++i)candidates.push_back({ArithToUint256(arith_uint256(i+1)),uint256S("01"),key.GetPublicKey()});
    auto first=llmq::RankRecoveryMembers(candidates,uint256S("01"));
    std::reverse(candidates.begin(),candidates.end());
    auto second=llmq::RankRecoveryMembers(candidates,uint256S("01"));
    BOOST_REQUIRE_EQUAL(first.size(),15U);BOOST_REQUIRE_EQUAL(second.size(),15U);
    for(size_t i=0;i<15;++i)BOOST_CHECK(first[i].proTxHash==second[i].proTxHash);
    auto rotated=llmq::RankRecoveryMembers(candidates,uint256S("02"));
    bool differs=false;for(size_t i=0;i<15;++i)differs |= first[i].proTxHash!=rotated[i].proTxHash;
    BOOST_CHECK(differs);
    candidates.resize(14);BOOST_CHECK(llmq::RankRecoveryMembers(candidates,uint256S("01")).empty());
}
BOOST_AUTO_TEST_CASE(recovery_state_boundaries)
{
    llmq::CRecoveryState s;
    s.Advance(77,uint256S("01"),false,false,100,60); BOOST_CHECK_EQUAL(s.failures,0);
    s.Advance(78,uint256S("01"),true,false,100,60);
    s.Advance(138,uint256S("02"),true,false,100,60); BOOST_CHECK_EQUAL(s.mode,0);
    s.Advance(198,uint256S("03"),true,false,100,60);
    BOOST_CHECK_EQUAL(s.mode,1); BOOST_CHECK_EQUAL(s.budget,10);
    auto timeout=s;
    timeout.Advance(557,uint256(),false,false,100,60); BOOST_CHECK_EQUAL(timeout.mode,2);
    timeout.Advance(618,uint256(),true,false,100,60); BOOST_CHECK_EQUAL(timeout.mode,2);
    timeout.Advance(678,uint256(),true,true,100,60); BOOST_CHECK_EQUAL(timeout.mode,2);
    timeout.Advance(738,uint256(),true,true,100,60); BOOST_CHECK_EQUAL(timeout.mode,0);
    s.Advance(258,uint256(),true,true,100,60); BOOST_CHECK_EQUAL(s.mode,1);
    s.Advance(318,uint256(),true,true,100,60); BOOST_CHECK_EQUAL(s.mode,0);
}
// A successful session between failures must break both consecutive counters.
BOOST_AUTO_TEST_CASE(recovery_interrupted_sessions_and_frozen_authority)
{
    llmq::CRecoveryState s;
    s.scheduledRoster=uint256S("11");
    s.Advance(78,uint256S("01"),true,false,79,60);
    s.Advance(138,uint256S("02"),true,false,79,60);
    s.Advance(198,uint256S("03"),true,true,79,60);
    BOOST_CHECK_EQUAL(s.failures,0);
    for(int h:{258,318,378})s.Advance(h,uint256S("04"),true,false,79,60);
    BOOST_REQUIRE_EQUAL(s.mode,1);
    BOOST_CHECK_EQUAL(s.budget,7);
    auto epoch=s.epoch;auto roster=s.frozenRoster;
    s.consumed.insert(uint256S("55"));
    s.scheduledRoster=uint256S("22");
    s.Advance(438,uint256(),true,true,200,60);
    BOOST_CHECK_EQUAL(s.successes,1);
    s.Advance(498,uint256(),true,false,200,60);
    BOOST_CHECK_EQUAL(s.successes,0);
    BOOST_CHECK_EQUAL(s.mode,1);
    BOOST_CHECK_EQUAL(s.budget,7);
    BOOST_CHECK(s.frozenRoster==roster && s.epoch==epoch);
    BOOST_CHECK_EQUAL(s.consumed.size(),1U);
    s.Advance(558,uint256(),false,true,200,60);
    BOOST_CHECK_EQUAL(s.successes,0); // Only completed sessions count.
    s.Advance(558,uint256(),true,true,200,60);
    BOOST_CHECK_EQUAL(s.mode,1);
    s.Advance(618,uint256(),true,true,200,60);
    BOOST_CHECK_EQUAL(s.mode,0);
    for(int h:{678,738,798})s.Advance(h,uint256S("06"),true,false,200,60);
    BOOST_CHECK_EQUAL(s.mode,1);
    BOOST_CHECK_EQUAL(s.budget,10);
    BOOST_CHECK(s.consumed.empty());
    BOOST_CHECK(s.frozenRoster==s.scheduledRoster && s.epoch!=epoch);
}

BOOST_AUTO_TEST_CASE(recovery_timeout_cannot_renew_authority)
{
    llmq::CRecoveryState s;
    for(int h:{78,138,198})s.Advance(h,uint256S("01"),true,false,9,60);
    BOOST_REQUIRE_EQUAL(s.mode,1);
    BOOST_CHECK_EQUAL(s.budget,0);
    s.Advance(556,uint256(),false,false,100,60);
    BOOST_CHECK_EQUAL(s.mode,1);
    s.Advance(557,uint256(),false,false,100,60);
    BOOST_CHECK_EQUAL(s.mode,2);
    for(int h:{618,678,738})s.Advance(h,uint256(),true,false,100,60);
    BOOST_CHECK_EQUAL(s.mode,2);
    BOOST_CHECK_EQUAL(s.trigger,198);
    s.Advance(798,uint256(),true,true,100,60);
    s.Advance(858,uint256(),true,false,100,60);
    s.Advance(918,uint256(),true,true,100,60);
    BOOST_CHECK_EQUAL(s.mode,2);
    s.Advance(978,uint256(),true,true,100,60);
    BOOST_CHECK_EQUAL(s.mode,0);
}
BOOST_AUTO_TEST_SUITE_END()
