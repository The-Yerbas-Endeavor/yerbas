// Copyright (c) 2017-2020 The Yerbas Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <utilstrencodings.h>
#include <hash.h>
#include <validation.h>
#include <boost/algorithm/string/classification.hpp>
#include <boost/algorithm/string/split.hpp>
#include <chainparams.h>
#include <univalue/include/univalue.h>
#include <core_io.h>
#include <net.h>
#include <base58.h>
#include <boost/multiprecision/cpp_int.hpp>
#include <limits>
#include <consensus/validation.h>
#include <wallet/coincontrol.h>
#include <utilmoneystr.h>
#include "assets/rewards.h"
#include "assetsnapshotdb.h"
#include "wallet/wallet.h"



uint256 CRewardSnapshot::GetHash() const
{
    return SerializeHash(*this, SER_GETHASH);
}

#ifdef ENABLE_WALLET
bool AddDistributeRewardSnapshot(CWallet& wallet, CRewardSnapshot& p_rewardSnapshot)
{
    auto pDistributeSnapshotDb = wallet.assetDistributions.get();
    auto& mapRewardSnapshots = wallet.rewardSnapshots;

    auto hash = p_rewardSnapshot.GetHash();
    CRewardSnapshot temp;
    if (pDistributeSnapshotDb->RetrieveDistributeSnapshotRequest(hash, temp)) {
        return false;
    }

    if (!pDistributeSnapshotDb->AddDistributeSnapshot(hash, p_rewardSnapshot)) return false;
    mapRewardSnapshots[hash] = p_rewardSnapshot;

    return true;
}

bool CalculateRewardPayments(CAmount budget, int units, const std::vector<OwnerAndAmount>& owners,
                             std::vector<OwnerAndAmount>& payments)
{
    payments.clear();
    if (budget <= 0 || units < 0 || units > 8) return false;
    CAmount quantum = 1;
    for (int i = units; i < 8; ++i) quantum *= 10;
    CAmount total = 0;
    std::set<std::string> addresses;
    for (const auto& owner : owners) {
        if (owner.amount < 0 || owner.amount > std::numeric_limits<CAmount>::max() - total ||
            !addresses.insert(owner.address).second) return false;
        total += owner.amount;
    }
    if (total == 0) return false;
    // A signed 64-bit amount times another fits in unsigned 128 bits. Never
    // convert monetary amounts through floating point (notably on Windows).
    const boost::multiprecision::uint128_t wholeUnits = budget / quantum;
    for (const auto& owner : owners) {
        const auto share = (wholeUnits * owner.amount / total).convert_to<CAmount>();
        if (share > 0) payments.emplace_back(owner.address, share * quantum);
    }
    return !payments.empty();
}

bool GenerateDistributionList(CWallet& wallet, const CRewardSnapshot& plan, std::vector<OwnerAndAmount>& payments)
{
    payments.clear();
    if (!passets || !wallet.assetSnapshots) return false;
    int units = 8;
    if (plan.strDistributionAsset != "YERB" && plan.strDistributionAsset != "tYERB") {
        CNewAsset asset;
        if (!passets->GetAssetMetaDataIfExists(plan.strDistributionAsset, asset)) return false;
        units = asset.units;
    }
    CAssetSnapshotDBEntry snapshot;
    if (!wallet.assetSnapshots->RetrieveOwnershipSnapshot(plan.strOwnershipAsset, plan.nHeight, snapshot)) return false;
    std::set<std::string> exceptions;
    boost::split(exceptions, plan.strExceptionAddresses, boost::is_any_of(ADDRESS_COMMA_DELIMITER));
    std::vector<OwnerAndAmount> owners;
    for (const auto& entry : snapshot.ownersAndAmounts) {
        if (!exceptions.count(entry.first) && !Params().IsBurnAddress(entry.first))
            owners.emplace_back(entry.first, entry.second);
    }
    return CalculateRewardPayments(plan.nDistributionAmount, units, owners, payments);
}

void DistributeRewardSnapshot(CWallet * p_wallet, const CRewardSnapshot& p_rewardSnapshot)
{
    auto pDistributeSnapshotDb = (*p_wallet).assetDistributions.get();
    auto pAssetSnapshotDb = (*p_wallet).assetSnapshots.get();

    if (p_rewardSnapshot.nStatus == CRewardSnapshot::PAUSED) return;
    if (p_wallet->IsLocked()) {
        LogPrint(BCLog::REWARDS, "Skipping distribution: Wallet is locked!\n");
        return;
    }

    if (IsInitialBlockDownload()) {
        LogPrint(BCLog::REWARDS, "Skipping distribution: Syncing Chain!\n");
        return;
    }

    //  Retrieve the asset snapshot entry for the target asset at the specified height
    CAssetSnapshotDBEntry snapshotEntry;

    if (!pAssetSnapshotDb->RetrieveOwnershipSnapshot(p_rewardSnapshot.strOwnershipAsset, p_rewardSnapshot.nHeight, snapshotEntry)) {
        LogPrint(BCLog::REWARDS, "Failed to retrieve ownership snapshot!\n");
        return;
    }

    //  Generate payment transactions and store in the payments DB
    std::vector<OwnerAndAmount> paymentDetails;
    if (!GenerateDistributionList(*p_wallet, p_rewardSnapshot, paymentDetails)) {
        LogPrint(BCLog::REWARDS, "Failed to generate payment details!\n");
        return;
    }

    int nNumberOfTransactions = ((int)paymentDetails.size() + MAX_PAYMENTS_PER_TRANSACTION - 1) / MAX_PAYMENTS_PER_TRANSACTION;
    auto setStatus = [&](int status) {
        CRewardSnapshot updated = p_rewardSnapshot;
        updated.nStatus = status;
        if (updated.nStatus == p_rewardSnapshot.nStatus) return;
        if (!pDistributeSnapshotDb->OverrideDistributeSnapshot(updated.GetHash(), updated))
            throw std::runtime_error("Cannot save reward distribution status");
        p_wallet->rewardSnapshots[updated.GetHash()] = updated;
    };
    bool allConfirmed = true;
    for (int i = 0; i < nNumberOfTransactions; i++) {
        uint256 txid;
        if (pDistributeSnapshotDb->GetDistributeTransaction(p_rewardSnapshot.GetHash(), i, txid)) {
            CTransactionRef txRef;
            uint256 hashBlock;
            auto walletTx = p_wallet->GetWalletTx(txid);
            if (walletTx) {
                int depth = walletTx->GetDepthInMainChain();
                if (depth < 0) {
                    setStatus(CRewardSnapshot::STUCK_TX);
                    LogPrint(BCLog::REWARDS, "Failed distribution: Tx conflict with another tx: %s: number of block back %d!\n", txid.GetHex(), depth);
                    return;
                } else if (depth == 0) {
                    setStatus(CRewardSnapshot::PROCESSING);
                    LogPrint(BCLog::REWARDS, "Tx is in the mempool! %s\n", txid.GetHex());
                    return;
                } else if (depth > 0) {
                    LogPrint(BCLog::REWARDS, "Tx is in a block %s!\n", txid.GetHex());
                    continue;
                }
            } else {
                setStatus(CRewardSnapshot::STUCK_TX);
                LogPrint(BCLog::REWARDS, "Failed to get wallet Tx: %s\n", txid.GetHex());
                return; // Do not advance a plan whose recorded payment is absent.
            }
        } else {
            // Never recreate a payment from a completed or inconsistent plan
            // merely because its transaction reference cannot be read.
            if (p_rewardSnapshot.nStatus == CRewardSnapshot::COMPLETE ||
                p_rewardSnapshot.nStatus == CRewardSnapshot::STUCK_TX) {
                setStatus(CRewardSnapshot::STUCK_TX);
                return;
            }
            allConfirmed = false;
            LogPrint(BCLog::REWARDS, "Didn't find transaction in database creating new transaction: %s %s %d %d\n", p_rewardSnapshot.strOwnershipAsset, p_rewardSnapshot.strDistributionAsset, p_rewardSnapshot.nDistributionAmount, i);
            // Create a new transaction and database it
            int start = i * MAX_PAYMENTS_PER_TRANSACTION;
            uint256 retTxid;
            std::string change = "";
            if (!BuildTransaction(p_wallet, p_rewardSnapshot, paymentDetails, start, change, retTxid)) {
                LogPrint(BCLog::REWARDS, "Failed to build Tx: distribute: %s, amount: %d\n", p_rewardSnapshot.strDistributionAsset, p_rewardSnapshot.nDistributionAmount);
                return;
            }
            if (!pDistributeSnapshotDb->AddDistributeTransaction(p_rewardSnapshot.GetHash(), i, retTxid))
                throw std::runtime_error("Cannot save reward payment transaction");
        }
    }
    // Recheck even completed plans: a reorganization can unconfirm a payment.
    // Never mark a newly broadcast batch complete before it is mined.
    setStatus(allConfirmed ? CRewardSnapshot::COMPLETE : CRewardSnapshot::PROCESSING);
}

bool BuildTransaction(
        CWallet * const p_walletPtr, const CRewardSnapshot& p_rewardSnapshot,
        const std::vector<OwnerAndAmount> & p_pendingPayments,const int& start,
        std::string& change_address, uint256& retTxid)
{
    auto pDistributeSnapshotDb = (*p_walletPtr).assetDistributions.get();
    auto& mapRewardSnapshots = (*p_walletPtr).rewardSnapshots;

    int expectedCount = 0;
    int actualCount = 0;
    CValidationState state;

    int stop = start + MAX_PAYMENTS_PER_TRANSACTION;
    CRewardSnapshot copyRewardSnapshot = p_rewardSnapshot;
    auto rewardSnapshotHash = p_rewardSnapshot.GetHash();

    LogPrint(BCLog::REWARDS, "Generating transactions for payments...\n");

    //  Transfer the specified amount of the asset from the source to the target
    CCoinControl ctrl;
    ctrl.destChange = DecodeDestination(change_address);
    ctrl.assetDestChange = DecodeDestination(change_address);
    std::shared_ptr<CWalletTx> txnPtr = std::make_shared<CWalletTx>();
    std::shared_ptr<CReserveKey> reserveKeyPtr = std::make_shared<CReserveKey>(p_walletPtr);
    std::shared_ptr<UniValue> batchResult = std::make_shared<UniValue>(UniValue::VOBJ);
    CAmount nFeeRequired = 0;
    CAmount totalPaymentAmt = 0;


    //  Handle payouts using YERB differently from those using an asset
    if (p_rewardSnapshot.strDistributionAsset == "YERB" || p_rewardSnapshot.strDistributionAsset == "tYERB" ) {
        // Check amount
        CAmount curBalance = p_walletPtr->GetBalance();

        if (p_walletPtr->GetBroadcastTransactions() && !g_connman) {
            mapRewardSnapshots[rewardSnapshotHash].nStatus = CRewardSnapshot::NETWORK_ERROR;
            pDistributeSnapshotDb->OverrideDistributeSnapshot(rewardSnapshotHash, mapRewardSnapshots.at(rewardSnapshotHash));
            LogPrint(BCLog::REWARDS, "Error: Peer-to-peer functionality missing or disabled\n");
            return false;
        }

        std::vector<CRecipient> vDestinations;

        //  This should (due to external logic) only include pending payments
        for (int i = start; i < (int)p_pendingPayments.size() && i < stop; i++) {
            expectedCount++;

            // Parse Yerbas address (already validated during ownership snapshot creation)
            CTxDestination dest = DecodeDestination(p_pendingPayments[i].address);
            CScript scriptPubKey = GetScriptForDestination(dest);
            CRecipient recipient = {scriptPubKey, p_pendingPayments[i].amount, false};
            vDestinations.emplace_back(recipient);

            totalPaymentAmt += p_pendingPayments[i].amount;
            actualCount++;
        }

        //  Verify funds
        if (totalPaymentAmt > curBalance) {
            mapRewardSnapshots[rewardSnapshotHash].nStatus = CRewardSnapshot::LOW_FUNDS;
            pDistributeSnapshotDb->OverrideDistributeSnapshot(rewardSnapshotHash, mapRewardSnapshots[rewardSnapshotHash]);
            LogPrint(BCLog::REWARDS, "Insufficient funds: total payment %lld > available balance %lld\n",
                     totalPaymentAmt, curBalance);
            return false;
        }

        // Create and send the transaction
        std::string strError;
        int nChangePosRet = -1;

        if (!p_walletPtr->CreateTransaction(vDestinations, *txnPtr.get(), *reserveKeyPtr.get(), nFeeRequired, nChangePosRet, strError, ctrl)) {
            if (totalPaymentAmt + nFeeRequired > curBalance) {
                mapRewardSnapshots[rewardSnapshotHash].nStatus = CRewardSnapshot::NOT_ENOUGH_FEE;
                pDistributeSnapshotDb->OverrideDistributeSnapshot(rewardSnapshotHash, mapRewardSnapshots.at(rewardSnapshotHash));
                strError = strprintf("Error: This transaction requires a transaction fee of at least %s",
                                     FormatMoney(nFeeRequired));
            } else {
                mapRewardSnapshots[rewardSnapshotHash].nStatus = CRewardSnapshot::FAILED_CREATE_TRANSACTION;
                pDistributeSnapshotDb->OverrideDistributeSnapshot(rewardSnapshotHash, mapRewardSnapshots.at(rewardSnapshotHash));
            }

            LogPrint(BCLog::REWARDS, "%s\n", strError.c_str());
            return false;
        }

        if (!p_walletPtr->CommitTransaction(*txnPtr.get(), *reserveKeyPtr.get(), g_connman.get(), state)) {
            mapRewardSnapshots[rewardSnapshotHash].nStatus = CRewardSnapshot::FAILED_COMMIT_TRANSACTION;
            pDistributeSnapshotDb->OverrideDistributeSnapshot(rewardSnapshotHash, mapRewardSnapshots.at(rewardSnapshotHash));
            LogPrint(BCLog::REWARDS, "%s\n", state.GetRejectReason());
            return false;
        }
    }
    else {
        std::pair<int, std::string> error;
        std::vector< std::pair<CAssetTransfer, std::string> > vDestinations;
        CAmount nTotalAssetAmount = 0;

        // Get the total amount of distribution assets this wallet has
        CAmount totalAssetBalance = 0;
        GetMyAssetBalance(*p_walletPtr, p_rewardSnapshot.strDistributionAsset, totalAssetBalance, 0);

        //  This should (due to external logic) only include pending payments
        for (int i = start; i < (int)p_pendingPayments.size() && i < stop; i++) {
            expectedCount++;

            vDestinations.emplace_back(std::make_pair(
                    CAssetTransfer(p_rewardSnapshot.strDistributionAsset, p_pendingPayments[i].amount, DecodeAssetData(""), 0), p_pendingPayments[i].address));

            nTotalAssetAmount += p_pendingPayments[i].amount;
            actualCount++;
        }

        if (nTotalAssetAmount > totalAssetBalance) {
            mapRewardSnapshots[rewardSnapshotHash].nStatus = CRewardSnapshot::LOW_REWARDS;
            pDistributeSnapshotDb->OverrideDistributeSnapshot(rewardSnapshotHash, mapRewardSnapshots[rewardSnapshotHash]);
            LogPrint(BCLog::REWARDS, "Insufficient asset funds: total payment %lld > available balance %lld\n",
                     nTotalAssetAmount, totalAssetBalance);
            return false;
        }

        // Create the Transaction (this also verifies dest address)
        if (!CreateTransferAssetTransaction(p_walletPtr, ctrl, vDestinations, "", error, *txnPtr.get(), *reserveKeyPtr.get(), nFeeRequired)) {
            mapRewardSnapshots[rewardSnapshotHash].nStatus = CRewardSnapshot::FAILED_CREATE_TRANSACTION;
            pDistributeSnapshotDb->OverrideDistributeSnapshot(rewardSnapshotHash, mapRewardSnapshots.at(rewardSnapshotHash));
            LogPrint(BCLog::REWARDS, "Failed to create transfer asset transaction: %s\n", error.second.c_str());
            return false;
        }

        if (!p_walletPtr->CommitTransaction(*txnPtr.get(), *reserveKeyPtr.get(), g_connman.get(), state)) {
            mapRewardSnapshots[rewardSnapshotHash].nStatus = CRewardSnapshot::FAILED_COMMIT_TRANSACTION;
            pDistributeSnapshotDb->OverrideDistributeSnapshot(rewardSnapshotHash, mapRewardSnapshots.at(rewardSnapshotHash));
            LogPrint(BCLog::REWARDS, "%s\n", state.GetRejectReason());
            return false;
        }
    }

    retTxid = txnPtr->GetHash();
    LogPrint(BCLog::REWARDS, "Transaction generation succeeded : %s\n", retTxid.GetHex());

    return true;
}

void CheckRewardDistributions(CWallet * p_wallet)
{
    LOCK(p_wallet->cs_wallet);
    auto& mapRewardSnapshots = (*p_wallet).rewardSnapshots;

    if (!fAssetIndex) return;
    for (auto item : mapRewardSnapshots) {
        DistributeRewardSnapshot(p_wallet, item.second);
    }
}

#endif //ENABLE_WALLET



