#include "base58.h"
#include "chainparams.h"
#include "consensus/merkle.h"
#include "consensus/validation.h"
#include "primitives/block.h"
#include "script/standard.h"
#include "test/test_yerbas.h"
#include "validation.h"
#include <boost/test/unit_test.hpp>

struct FounderPaymentSetup : BasicTestingSetup {
    FounderPaymentSetup() : BasicTestingSetup(CBaseChainParams::REGTEST) {}
};

BOOST_FIXTURE_TEST_SUITE(founder_payment_tests, FounderPaymentSetup)

BOOST_AUTO_TEST_CASE(context_free_check_does_not_use_tip_height)
{
    auto consensus = Params().GetConsensus();
    CKey key;
    key.MakeNewKey(true);
    consensus.nFounderPayment = FounderPayment({{INT_MAX, 5}}, 200, CBitcoinAddress(key.GetPubKey().GetID()).ToString());
    CMutableTransaction cb;
    cb.vin.resize(1);
    cb.vin[0].scriptSig = CScript() << 201 << OP_0;
    cb.vout.emplace_back(1, CScript() << OP_TRUE);
    CBlock block;
    block.vtx.push_back(MakeTransactionRef(cb));
    block.hashMerkleRoot = BlockMerkleRoot(block);
    for (int guessedHeight : {0, 201, 202, 420, 739}) {
        CValidationState state;
        BOOST_CHECK(CheckBlock(block, state, consensus, guessedHeight, false, true));
    }
    CValidationState before;
    BOOST_CHECK(CheckBlockFounderPayment(block, before, consensus, 201));
    // A context-free cache hit must never suppress payment validation.
    block.fChecked = true;
    CValidationState missing;
    BOOST_CHECK(!CheckBlockFounderPayment(block, missing, consensus, 202));
    BOOST_CHECK_EQUAL(missing.GetRejectReason(), "bad-cb-founder-payment-not-found");

    const CAmount subsidy = GetBlockSubsidy(1, 201, consensus, false);
    const CAmount reward = consensus.nFounderPayment.getFounderPaymentAmount(201, subsidy);
    BOOST_REQUIRE(reward > 0);
    cb.vout.emplace_back(reward, GetScriptForDestination(key.GetPubKey().GetID()));
    block.vtx[0] = MakeTransactionRef(cb);
    CValidationState valid;
    BOOST_CHECK(CheckBlockFounderPayment(block, valid, consensus, 202));
    cb.vout.back().nValue--;
    block.vtx[0] = MakeTransactionRef(cb);
    CValidationState underpaid;
    BOOST_CHECK(!CheckBlockFounderPayment(block, underpaid, consensus, 202));
    cb.vout.back().nValue++;
    cb.vout.back().scriptPubKey = CScript() << OP_TRUE;
    block.vtx[0] = MakeTransactionRef(cb);
    CValidationState wrongPayee;
    BOOST_CHECK(!CheckBlockFounderPayment(block, wrongPayee, consensus, 202));
}

BOOST_AUTO_TEST_SUITE_END()
