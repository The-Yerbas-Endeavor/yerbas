// Copyright (c) 2014-2018 The Dash Core developers
// Copyright (c) 2020 The Yerbas developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include "chainparams.h"
#include "validation.h"

#include "test/test_yerbas.h"

#include <boost/test/unit_test.hpp>

// Expected rewards are literal base units, independent of GetBlockSubsidy.
// Heights are PREVIOUS block heights, as required by the consensus API.
// In particular, height 1,000,000 still pays 100 YERB; 80 starts at 1,000,001.
BOOST_FIXTURE_TEST_SUITE(subsidy_tests, BasicTestingSetup)

BOOST_AUTO_TEST_CASE(block_subsidy_test)
{
    const struct {
        int previousHeight;
        CAmount reward;
    } cases[] = {
        {0, 420000000LL},
        {418, 420000000LL},
        {419, 420000000LL},
        {420, 10000000000LL},
        {421, 10000000000LL},
        {4249, 10000000000LL},
        {4501, 10000000000LL},
        {5464, 10000000000LL},
        {5465, 10000000000LL},
        {17588, 10000000000LL},
        {99999, 10000000000LL},
        {210239, 10000000000LL},
        {210240, 10000000000LL},
        {999999, 10000000000LL},
        {1000000, 10000000000LL},
        {1000001, 8000000000LL},
        {1999999, 8000000000LL},
        {2000000, 7000000000LL},
        {2000001, 7000000000LL},
        {2999999, 7000000000LL},
        {3000000, 5000000000LL},
        {3000001, 5000000000LL},
        {3999999, 5000000000LL},
        {4000000, 4000000000LL},
        {4000001, 4000000000LL},
        {4999999, 4000000000LL},
        {5000000, 2000000000LL},
        {5000001, 2000000000LL},
        {5999999, 2000000000LL},
        {6000000, 1000000000LL},
        {6000001, 1000000000LL},
        {6999999, 1000000000LL},
        {7000000, 900000000LL},
        {7000001, 900000000LL},
        {7999999, 900000000LL},
        {8000000, 800000000LL},
        {8000001, 800000000LL},
        {8999999, 800000000LL},
        {9000000, 700000000LL},
        {9000001, 700000000LL},
        {9999999, 700000000LL},
        {10000000, 600000000LL},
        {10000001, 600000000LL},
        {10999999, 600000000LL},
        {11000000, 500000000LL},
        {11000001, 500000000LL},
        {11999999, 500000000LL},
        {12000000, 420000000LL},
        {12000001, 420000000LL},
        {12999999, 420000000LL},
        {13000000, 300000000LL},
        {13000001, 300000000LL},
        {13999999, 300000000LL},
        {14000000, 200000000LL},
        {14000001, 200000000LL},
        {14999999, 200000000LL},
        {15000000, 100000000LL},
        {15000001, 100000000LL},
        {15999999, 100000000LL},
        {16000000, 42000000LL},
        {16000001, 42000000LL},
        {20000000, 42000000LL},
    };

    for (const auto& network : {CBaseChainParams::MAIN, CBaseChainParams::TESTNET,
                               CBaseChainParams::REGTEST}) {
        const auto params = CreateChainParams(network);
        for (const auto& test : cases) {
            BOOST_TEST_CONTEXT("network=" << network << " previousHeight=" << test.previousHeight) {
                // Yerbas rewards do not depend on difficulty or the inherited
                // Dash superblock selector. Pin both behaviors explicitly.
                for (const auto bits : {0x1c4a47c4, 0x1b10d50b, 0x207fffff}) {
                    BOOST_CHECK_EQUAL(GetBlockSubsidy(bits, test.previousHeight, params->GetConsensus(), false), test.reward);
                    BOOST_CHECK_EQUAL(GetBlockSubsidy(bits, test.previousHeight, params->GetConsensus(), true), test.reward);
                }
            }
        }
    }
}

BOOST_AUTO_TEST_SUITE_END()
