// Copyright (c) 2026 The Yerbas Core developers
// Distributed under the MIT software license, see the accompanying COPYING file.

#include "wallet/wallet.h"
#include "assets/assets.h"
#include "assets/messages.h"
#include "assets/myassetsdb.h"
#include "test/test_yerbas.h"
#include "base58.h"
#include "rpc/server.h"
#include "univalue.h"
#include <limits>

UniValue resumerewarddistribution(const JSONRPCRequest& request);
#include <boost/test/unit_test.hpp>

BOOST_FIXTURE_TEST_SUITE(asset_wallet_tests, TestingSetup)

BOOST_AUTO_TEST_CASE(database_close_releases_error_log)
{
    CDBEnv env;
    BOOST_REQUIRE(env.Open(GetDataDir()));
    env.Close();
    // Windows refuses this removal while the application's FILE handle is open.
    BOOST_CHECK(fs::remove(GetDataDir() / "db.log"));
}

static std::unique_ptr<CWallet> OpenAssetTestWallet(CDBEnv& env, const std::string& name)
{
    std::unique_ptr<CWallet> wallet(new CWallet(std::unique_ptr<CWalletDBWrapper>(new CWalletDBWrapper(&env, name))));
    BOOST_REQUIRE_EQUAL(CWalletDB(wallet->GetDBHandle(), "cr+").LoadWallet(wallet.get()), DB_LOAD_OK);
    return wallet;
}

BOOST_AUTO_TEST_CASE(backup_restores_asset_records_without_side_databases)
{
    CDBEnv env;
    BOOST_REQUIRE(env.Open(GetDataDir()));
    CMessage message(COutPoint(uint256S("12"), 2), "ASSET!", "payload", 0, 1234);
    CRewardSnapshot plan("ASSET", "YERB", "", COIN, 123);
    {
        auto wallet = OpenAssetTestWallet(env, "asset-wallet.dat");
        BOOST_REQUIRE(InitializeWalletAssetStores(*wallet, false));
        AddChannel(*wallet, "ASSET!");
        AddAddressSeen(*wallet, "address");
        BOOST_REQUIRE(wallet->assetMessages->WriteMessage(message));
        BOOST_REQUIRE(wallet->assetRestrictions->WriteTaggedAddress("address", "#TAG", true, 1234));
        BOOST_REQUIRE(wallet->assetRestrictions->WriteRestrictedAddress("address", "$ASSET", false, 1235));
        BOOST_REQUIRE(wallet->assetSnapshotRequests->ScheduleSnapshot("ASSET", 123));
        CAssetSnapshotDBEntry snapshot("ASSET", 123, {{"address", COIN}});
        BOOST_REQUIRE(wallet->assetSnapshots->Write(std::make_pair('C', snapshot.heightAndName), snapshot));
        BOOST_REQUIRE(AddDistributeRewardSnapshot(*wallet, plan));
        BOOST_REQUIRE(wallet->assetDistributions->AddDistributeTransaction(plan.GetHash(), 0, uint256S("56")));
        CMutableTransaction tx;
        tx.vin.emplace_back(COutPoint(uint256S("11"), 0));
        CScript script = GetScriptForDestination(CKeyID(uint160()));
        CAssetTransfer("ASSET", COIN).ConstructTransaction(script);
        tx.vout.emplace_back(0, script);
        CWalletTx wtx(wallet.get(), MakeTransactionRef(tx));
        BOOST_REQUIRE(CWalletDB(wallet->GetDBHandle()).WriteTx(wtx));
        BOOST_REQUIRE(wallet->BackupWallet((GetDataDir() / "restored.dat").string()));
    }
    BOOST_CHECK(!fs::exists(GetDataDir() / "messages"));
    BOOST_CHECK(!fs::exists(GetDataDir() / "myrestricted"));
    BOOST_CHECK(!fs::exists(GetDataDir() / "rewards"));
    {
        auto restored = OpenAssetTestWallet(env, "restored.dat");
        BOOST_REQUIRE(InitializeWalletAssetStores(*restored, true));
        BOOST_CHECK(IsChannelSubscribed(*restored, "ASSET!"));
        BOOST_CHECK(IsAddressSeen(*restored, "address"));
        CMessage found;
        BOOST_REQUIRE(restored->assetMessages->ReadMessage(message.out, found));
        BOOST_CHECK_EQUAL(found.ipfsHash, "payload");
        bool add = false; uint32_t time = 0;
        BOOST_REQUIRE(restored->assetRestrictions->ReadTaggedAddress("address", "#TAG", add, time));
        BOOST_CHECK(add); BOOST_CHECK_EQUAL(time, 1234U);
        BOOST_REQUIRE(restored->assetRestrictions->ReadRestrictedAddress("address", "$ASSET", add, time));
        BOOST_CHECK(!add); BOOST_CHECK_EQUAL(time, 1235U);
        BOOST_CHECK(restored->assetSnapshotRequests->ContainsSnapshotRequest("ASSET", 123));
        std::set<CSnapshotRequestDBEntry> scheduled;
        BOOST_REQUIRE(restored->assetSnapshotRequests->RetrieveSnapshotRequestsForHeight("ASSET", 123, scheduled));
        BOOST_REQUIRE_EQUAL(scheduled.size(), 1U);
        CAssetSnapshotDBEntry snapshot;
        BOOST_REQUIRE(restored->assetSnapshots->RetrieveOwnershipSnapshot("ASSET", 123, snapshot));
        BOOST_CHECK_EQUAL(snapshot.ownersAndAmounts.size(), 1U);
        BOOST_CHECK_EQUAL(restored->rewardSnapshots.at(plan.GetHash()).nStatus, CRewardSnapshot::PROCESSING);
        uint256 txid;
        BOOST_REQUIRE(restored->assetDistributions->GetDistributeTransaction(plan.GetHash(), 0, txid));
        BOOST_CHECK(txid == uint256S("56"));
        BOOST_REQUIRE_EQUAL(restored->mapWallet.size(), 1U);
        CAssetOutputEntry asset;
        BOOST_REQUIRE(GetAssetData(restored->mapWallet.begin()->second.tx->vout[0].scriptPubKey, asset));
        BOOST_CHECK_EQUAL(asset.assetName, "ASSET");
        BOOST_CHECK_EQUAL(asset.nAmount, COIN);
    }
    env.Flush(true);
}

BOOST_AUTO_TEST_CASE(wallet_isolation_and_message_updates)
{
    CDBEnv env;
    BOOST_REQUIRE(env.Open(GetDataDir()));
    {
        auto first = OpenAssetTestWallet(env, "first.dat");
        auto second = OpenAssetTestWallet(env, "second.dat");
        BOOST_REQUIRE(InitializeWalletAssetStores(*first, false));
        BOOST_REQUIRE(InitializeWalletAssetStores(*second, false));
        AddChannel(*first, "FIRST!");
        BOOST_CHECK(!IsChannelSubscribed(*second, "FIRST!"));
        CMessage message(COutPoint(uint256S("23"), 1), "FIRST!", "payload", 0, 1234);
        BOOST_REQUIRE(first->assetMessages->WriteMessage(message));
        message.status = MessageStatus::READ;
        BOOST_REQUIRE(first->assetMessages->WriteMessage(message));
        CMessage found;
        BOOST_REQUIRE(first->assetMessages->ReadMessage(message.out, found));
        BOOST_CHECK(found.status == MessageStatus::READ);
        BOOST_CHECK(!second->assetMessages->ReadMessage(message.out, found));
        int erased = 0;
        BOOST_REQUIRE(second->assetMessages->EraseAllMessages(erased));
        BOOST_CHECK_EQUAL(erased, 0);
        BOOST_REQUIRE(first->assetMessages->ReadMessage(message.out, found));
        RemoveChannel(*first, "FIRST!");
        BOOST_CHECK(!IsChannelSubscribed(*first, "FIRST!"));
    }
    env.Flush(true);
}

BOOST_AUTO_TEST_CASE(legacy_migration_is_idempotent_and_rejects_corruption)
{
    CMessage message(COutPoint(uint256S("34"), 0), "LEGACY!", "legacy", 0, 1234);
    {
        CMessageDB legacy(1 << 20);
        BOOST_REQUIRE(legacy.WriteMessage(message));
        CMessageChannelDB channels(1 << 20);
        BOOST_REQUIRE(channels.WriteMyMessageChannel("LEGACY!"));
        BOOST_REQUIRE(channels.Write(std::make_pair('C', std::string("BROKEN!")), std::string("bad")));
    }
    CDBEnv env;
    BOOST_REQUIRE(env.Open(GetDataDir()));
    {
        auto wallet = OpenAssetTestWallet(env, "migration.dat");
        BOOST_CHECK(!InitializeWalletAssetStores(*wallet, true));
        BOOST_CHECK(wallet->walletAssetRecords.empty());
        {
            CMessageChannelDB legacy(1 << 20);
            BOOST_REQUIRE(legacy.EraseMyMessageChannel("BROKEN!"));
        }
        BOOST_REQUIRE(InitializeWalletAssetStores(*wallet, true));
        BOOST_CHECK(IsChannelSubscribed(*wallet, "LEGACY!"));
        CMessage found;
        BOOST_REQUIRE(wallet->assetMessages->ReadMessage(message.out, found));
        BOOST_REQUIRE(wallet->assetMessages->EraseMessage(message.out));
        RemoveChannel(*wallet, "LEGACY!");
        BOOST_REQUIRE(InitializeWalletAssetStores(*wallet, true));
        BOOST_CHECK(!IsChannelSubscribed(*wallet, "LEGACY!"));
        BOOST_CHECK(!wallet->assetMessages->ReadMessage(message.out, found));
        BOOST_CHECK(fs::exists(GetDataDir() / "messages"));
    }
    {
        auto reopened = OpenAssetTestWallet(env, "migration.dat");
        BOOST_REQUIRE(InitializeWalletAssetStores(*reopened, true));
        BOOST_CHECK(!IsChannelSubscribed(*reopened, "LEGACY!"));
        CMessage found;
        BOOST_CHECK(!reopened->assetMessages->ReadMessage(message.out, found));
    }
    env.Flush(true);
}

BOOST_AUTO_TEST_CASE(legacy_rewards_are_paused_and_invalid_wallet_records_fail_loading)
{
    CRewardSnapshot plan("ASSET", "YERB", "", COIN, 123);
    {
        CDistributeSnapshotRequestDB legacy(1 << 20);
        BOOST_REQUIRE(legacy.AddDistributeSnapshot(plan.GetHash(), plan));
        BOOST_REQUIRE(legacy.AddDistributeTransaction(plan.GetHash(), 0, uint256S("56")));
        CSnapshotRequestDB requests(1 << 20);
        BOOST_REQUIRE(requests.ScheduleSnapshot("ASSET", 123));
        CAssetSnapshotDB snapshots(1 << 20);
        CAssetSnapshotDBEntry snapshot("ASSET", 123, {{"address", COIN}});
        BOOST_REQUIRE(snapshots.Write(std::make_pair('C', snapshot.heightAndName), snapshot));
    }
    CDBEnv env;
    BOOST_REQUIRE(env.Open(GetDataDir()));
    {
        auto wallet = OpenAssetTestWallet(env, "rewards.dat");
        BOOST_REQUIRE(InitializeWalletAssetStores(*wallet, true));
        BOOST_REQUIRE_EQUAL(wallet->rewardSnapshots.size(), 1U);
        BOOST_CHECK_EQUAL(wallet->rewardSnapshots.at(plan.GetHash()).nStatus, CRewardSnapshot::PAUSED);
        BOOST_CHECK(wallet->assetSnapshotRequests->ContainsSnapshotRequest("ASSET", 123));
        CAssetSnapshotDBEntry snapshot;
        BOOST_REQUIRE(wallet->assetSnapshots->RetrieveOwnershipSnapshot("ASSET", 123, snapshot));
        uint256 txid;
        BOOST_REQUIRE(wallet->assetDistributions->GetDistributeTransaction(plan.GetHash(), 0, txid));
        BOOST_CHECK(txid == uint256S("56"));
        auto other = OpenAssetTestWallet(env, "other-rewards.dat");
        BOOST_REQUIRE(InitializeWalletAssetStores(*other, true));
        struct WalletRegistration {
            std::vector<CWalletRef> saved;
            WalletRegistration(CWallet* first, CWallet* second) : saved(vpwallets) { vpwallets = {first, second}; }
            ~WalletRegistration() { vpwallets = saved; }
        } registration(wallet.get(), other.get());
        JSONRPCRequest request;
        request.URI = "/wallet/rewards.dat";
        request.params = UniValue(UniValue::VARR);
        request.params.push_back(plan.GetHash().GetHex());
        BOOST_CHECK_NO_THROW(resumerewarddistribution(request));
        BOOST_CHECK_EQUAL(wallet->rewardSnapshots.at(plan.GetHash()).nStatus, CRewardSnapshot::PROCESSING);
        BOOST_CHECK_EQUAL(other->rewardSnapshots.at(plan.GetHash()).nStatus, CRewardSnapshot::PAUSED);
        BOOST_CHECK_THROW(resumerewarddistribution(request), UniValue);
        BOOST_REQUIRE(InitializeWalletAssetStores(*wallet, true));
        BOOST_CHECK_EQUAL(wallet->rewardSnapshots.at(plan.GetHash()).nStatus, CRewardSnapshot::PROCESSING);
        auto fresh = OpenAssetTestWallet(env, "fresh.dat");
        BOOST_REQUIRE(InitializeWalletAssetStores(*fresh, false));
        BOOST_CHECK(fresh->rewardSnapshots.empty());
        // Corruption must fail loading instead of silently losing wallet asset metadata.
        BOOST_REQUIRE(CWalletDB(wallet->GetDBHandle()).WriteAssetRecord({"unknown", {}}, {1}));
    }
    {
        CWallet wallet(std::unique_ptr<CWalletDBWrapper>(new CWalletDBWrapper(&env, "rewards.dat")));
        BOOST_CHECK_EQUAL(CWalletDB(wallet.GetDBHandle()).LoadWallet(&wallet), DB_CORRUPT);
    }
    env.Flush(true);
}

BOOST_AUTO_TEST_CASE(legacy_restrictions_follow_watch_only_ownership)
{
    const CScript mine = GetScriptForDestination(CKeyID(uint160()));
    const std::string address = EncodeDestination(CKeyID(uint160()));
    {
        CMyRestrictedDB legacy(1 << 20);
        BOOST_REQUIRE(legacy.WriteTaggedAddress(address, "#TAG", true, 1234));
        BOOST_REQUIRE(legacy.WriteTaggedAddress("not-ours", "#OTHER", true, 1234));
    }
    CDBEnv env;
    BOOST_REQUIRE(env.Open(GetDataDir()));
    {
        auto wallet = OpenAssetTestWallet(env, "watch.dat");
        BOOST_REQUIRE(wallet->AddWatchOnly(mine, 0));
        BOOST_REQUIRE(InitializeWalletAssetStores(*wallet, true));
        bool add; uint32_t time;
        BOOST_REQUIRE(wallet->assetRestrictions->ReadTaggedAddress(address, "#TAG", add, time));
        BOOST_CHECK(!wallet->assetRestrictions->ReadTaggedAddress("not-ours", "#OTHER", add, time));
    }
    env.Flush(true);
}

BOOST_AUTO_TEST_CASE(reward_allocation_is_exact_and_rejects_invalid_totals)
{
    std::vector<OwnerAndAmount> payments;
    const std::vector<OwnerAndAmount> equal{{"a", COIN}, {"b", COIN}, {"c", COIN}};
    BOOST_REQUIRE(CalculateRewardPayments(10, 8, equal, payments));
    BOOST_REQUIRE_EQUAL(payments.size(), 3U);
    for (const auto& payment : payments) BOOST_CHECK_EQUAL(payment.amount, 3);
    BOOST_REQUIRE(CalculateRewardPayments(10 * COIN + 1, 0, equal, payments));
    for (const auto& payment : payments) BOOST_CHECK_EQUAL(payment.amount, 3 * COIN);
    BOOST_REQUIRE(CalculateRewardPayments(10001, 4, {{"a", 1}}, payments));
    BOOST_CHECK_EQUAL(payments[0].amount, 10000);
    const auto maximum = std::numeric_limits<CAmount>::max();
    BOOST_REQUIRE(CalculateRewardPayments(maximum, 8, {{"a", maximum - 1}, {"b", 1}}, payments));
    BOOST_REQUIRE_EQUAL(payments.size(), 2U);
    BOOST_CHECK_EQUAL(payments[0].amount, maximum - 1);
    BOOST_CHECK_EQUAL(payments[1].amount, 1);
    BOOST_CHECK(!CalculateRewardPayments(1, 8, {{"a", maximum}, {"b", 1}}, payments));
    BOOST_CHECK(payments.empty());
    BOOST_CHECK(!CalculateRewardPayments(1, 8, {{"a", 0}}, payments));
    BOOST_CHECK(!CalculateRewardPayments(1, 8, {{"a", -1}}, payments));
    BOOST_CHECK(!CalculateRewardPayments(1, 8, {{"a", 1}, {"a", 1}}, payments));
    BOOST_CHECK(!CalculateRewardPayments(1, 0, {{"a", 1}}, payments));
    BOOST_CHECK(!CalculateRewardPayments(1, 9, {{"a", 1}}, payments));
    BOOST_CHECK(!CalculateRewardPayments(-1, 8, {{"a", 1}}, payments));
}

BOOST_AUTO_TEST_SUITE_END()
