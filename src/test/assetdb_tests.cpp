// Copyright (c) 2026 The Yerbas Core developers
// Distributed under the MIT software license, see the accompanying COPYING file.

#include "assets/assetdb.h"
#include "assets/assets.h"
#include "test/test_yerbas.h"
#include <boost/test/unit_test.hpp>
#include <limits>
#ifdef ENABLE_WALLET
#include "wallet/wallet.h"
#endif

BOOST_FIXTURE_TEST_SUITE(assetdb_tests, TestingSetup)

BOOST_AUTO_TEST_CASE(asset_filters_and_reverse_pagination)
{
    CAssetsDB db(1 << 20, true, true);
    // A key before the asset namespace exposes accidental SeekToFirst resets.
    BOOST_REQUIRE(db.Write('0', 1));
    for (const auto& name : {"ALPHA", "ALPHA/SUB", "BRAVO"})
        BOOST_REQUIRE(db.WriteAssetData(CNewAsset(name, COIN), 1, uint256()));
    std::vector<CDatabasedAssetData> rows;
    BOOST_REQUIRE(db.AssetDir(rows, "", 10, 0));
    BOOST_CHECK_EQUAL(rows.size(), 3U);
    rows.clear();
    BOOST_REQUIRE(db.AssetDir(rows, "ALPHA", 10, 0));
    BOOST_REQUIRE_EQUAL(rows.size(), 1U);
    BOOST_CHECK_EQUAL(rows[0].asset.strName, "ALPHA");
    rows.clear();
    BOOST_REQUIRE(db.AssetDir(rows, "ALPHA*", 10, -1));
    BOOST_REQUIRE_EQUAL(rows.size(), 1U);
    BOOST_CHECK_EQUAL(rows[0].asset.strName, "ALPHA/SUB");
    rows.clear();
    BOOST_REQUIRE(db.AssetDir(rows, "*", 10, std::numeric_limits<long>::min()));
    BOOST_CHECK_EQUAL(rows.size(), 3U);
    rows.clear();
    BOOST_REQUIRE(db.AssetDir(rows, "*", 0, 0));
    BOOST_CHECK(rows.empty());
}

BOOST_AUTO_TEST_CASE(address_indexes_reverse_pagination)
{
    CAssetsDB db(1 << 20, true, true);
    BOOST_REQUIRE(db.Write('0', 1));
    for (const auto& owner : {"owner-a", "owner-b"}) {
        for (const auto& name : {"ALPHA", "BRAVO"}) {
            BOOST_REQUIRE(db.WriteAssetAddressQuantity(name, owner, COIN));
            BOOST_REQUIRE(db.WriteAddressAssetQuantity(owner, name, COIN));
        }
    }
    int total = -1;
    std::vector<std::pair<std::string, CAmount>> rows;
    BOOST_REQUIRE(db.AddressDir(rows, total, true, "owner-b", 10, 0));
    BOOST_CHECK_EQUAL(total, 2);
    BOOST_REQUIRE(db.AddressDir(rows, total, false, "owner-b", 10, -1));
    BOOST_REQUIRE_EQUAL(rows.size(), 1U);
    BOOST_CHECK_EQUAL(rows[0].first, "BRAVO");
    rows.clear();
    BOOST_REQUIRE(db.AssetAddressDir(rows, total, true, "BRAVO", 10, 0));
    BOOST_CHECK_EQUAL(total, 2);
    BOOST_REQUIRE(db.AssetAddressDir(rows, total, false, "BRAVO", 10, -1));
    BOOST_REQUIRE_EQUAL(rows.size(), 1U);
    BOOST_CHECK_EQUAL(rows[0].first, "owner-b");
    rows.clear();
    BOOST_REQUIRE(db.AssetAddressDir(rows, total, false, "BRAVO", 10, std::numeric_limits<long>::min()));
    BOOST_CHECK_EQUAL(rows.size(), 2U);
    rows.clear();
    BOOST_REQUIRE(db.AddressDir(rows, total, false, "owner-b", 10, std::numeric_limits<long>::min()));
    BOOST_CHECK_EQUAL(rows.size(), 2U);
    rows.clear();
    BOOST_REQUIRE(db.AssetAddressDir(rows, total, false, "MISSING", 10, -1));
    BOOST_CHECK(rows.empty());
}

#ifdef ENABLE_WALLET
BOOST_AUTO_TEST_CASE(wallet_balance_outputs_do_not_retain_stale_values)
{
    CWallet wallet;
    CAmount balance = 123;
    BOOST_REQUIRE(GetMyAssetBalance(wallet, "MISSING", balance, 0));
    BOOST_CHECK_EQUAL(balance, 0);
    std::map<std::string, CAmount> amounts{{"STALE", COIN}};
    std::map<std::string, std::vector<COutput>> outputs{{"STALE", {}}};
    BOOST_REQUIRE(GetAllMyAssetBalances(wallet, outputs, amounts));
    BOOST_CHECK(amounts.empty());
    BOOST_CHECK(outputs.empty());
}
#endif

BOOST_AUTO_TEST_SUITE_END()
