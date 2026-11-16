// Copyright (c) 2018-2021 The Yerbas Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <validation.h>
#include <chainparams.h>
#include <wallet/wallet.h>
#include <script/ismine.h>
#include <base58.h>
#include "messages.h"
#include "myassetsdb.h"
#include <primitives/block.h>


std::set<COutPoint> setDirtyMessagesRemove;
std::map<COutPoint, CMessage> mapDirtyMessagesAdd;
std::map<COutPoint, CMessage> mapDirtyMessagesOrphaned;

std::set<std::string> setDirtyChannelsAdd;
std::set<std::string> setDirtyChannelsRemove;
std::set<std::string> setSubscribedChannelsAskedForFalse;

std::set<std::string> setDirtySeenAddressAdd;
std::set<std::string> setAddressAskedForFalse;

CCriticalSection cs_messaging;


int8_t IntFromMessageStatus(MessageStatus status)
{
    return (int8_t)status;
}

MessageStatus MessageStatusFromInt(int8_t nStatus)
{
    return (MessageStatus)nStatus;
}

std::string MessageStatusToString(MessageStatus status)
{
    switch (status) {
        case MessageStatus::READ: return "READ";
        case MessageStatus::UNREAD: return "UNREAD";
        case MessageStatus::ORPHAN: return "ORPHAN";
        case MessageStatus::EXPIRED: return "EXPIRED";
        case MessageStatus::SPAM: return "SPAM";
        case MessageStatus::HIDDEN: return "HIDDEN";
        default: return "ERROR";
    }
}

CMessage::CMessage() {
    SetNull();
}

CMessage::CMessage(const COutPoint& out, const std::string& strName, const std::string& ipfsHash, const int64_t& nExpiredTime, const int64_t& time)
{
    SetNull();
    this->out = out;
    this->strName = strName;
    this->ipfsHash = ipfsHash;
    this->nExpiredTime = nExpiredTime;
    this->time = time;
    status = MessageStatus::UNREAD;
}

#ifdef ENABLE_WALLET
static void RequireAssetWrite(bool success)
{
    if (!success) throw std::runtime_error("Failed to save wallet asset data");
}

bool IsChannelSubscribed(CWallet& wallet, const std::string& name)
{
    LOCK(wallet.cs_wallet);
    return wallet.assetChannels && wallet.assetChannels->ReadMyMessageChannel(name);
}

void AddChannel(CWallet& wallet, const std::string& name)
{
    LOCK(wallet.cs_wallet);
    RequireAssetWrite(wallet.assetChannels && wallet.assetChannels->WriteMyMessageChannel(name));
}

void RemoveChannel(CWallet& wallet, const std::string& name)
{
    LOCK(wallet.cs_wallet);
    RequireAssetWrite(wallet.assetChannels && wallet.assetChannels->EraseMyMessageChannel(name));
}

bool IsAddressSeen(CWallet& wallet, const std::string& address)
{
    LOCK(wallet.cs_wallet);
    return wallet.assetChannels && wallet.assetChannels->ReadUsedAddress(address);
}

void AddAddressSeen(CWallet& wallet, const std::string& address)
{
    LOCK(wallet.cs_wallet);
    RequireAssetWrite(wallet.assetChannels && wallet.assetChannels->WriteUsedAddress(address));
}
#endif

bool IsChannelSubscribed(const std::string& name)
{
#ifdef ENABLE_WALLET
    LOCK(cs_main);
    for (auto wallet : vpwallets)
        if (IsChannelSubscribed(*wallet, name)) return true;
#endif
    return false;
}

bool GetMessage(const COutPoint& out, CMessage& message)
{
#ifdef ENABLE_WALLET
    LOCK(cs_main);
    for (auto wallet : vpwallets) {
        LOCK(wallet->cs_wallet);
        if (wallet->assetMessages && wallet->assetMessages->ReadMessage(out, message)) return true;
    }
#endif
    return false;
}

void AddMessage(const CMessage& message)
{
#ifdef ENABLE_WALLET
    LOCK(cs_main);
    for (auto wallet : vpwallets) {
        LOCK(wallet->cs_wallet);
        if (IsChannelSubscribed(*wallet, message.strName))
            RequireAssetWrite(wallet->assetMessages && wallet->assetMessages->WriteMessage(message));
    }
#endif
}

void RemoveMessage(const CMessage& message) { RemoveMessage(message.out); }
void RemoveMessage(const COutPoint& out)
{
#ifdef ENABLE_WALLET
    LOCK(cs_main);
    for (auto wallet : vpwallets) {
        LOCK(wallet->cs_wallet);
        if (wallet->assetMessages) RequireAssetWrite(wallet->assetMessages->EraseMessage(out));
    }
#endif
}

void OrphanMessage(const CMessage& message) { OrphanMessage(message.out); }
void OrphanMessage(const COutPoint& out)
{
#ifdef ENABLE_WALLET
    LOCK(cs_main);
    for (auto wallet : vpwallets) {
        LOCK(wallet->cs_wallet);
        CMessage message;
        if (wallet->assetMessages && wallet->assetMessages->ReadMessage(out, message)) {
            message.status = MessageStatus::ORPHAN;
            RequireAssetWrite(wallet->assetMessages->WriteMessage(message));
        }
    }
#endif
}

#ifdef ENABLE_WALLET
bool ScanForMessageChannels(std::string& strError)
{
    LOCK(cs_main);

    LogPrintf("%s : Start Scanning For Message Channels\n", __func__);

    if (vpwallets.size() == 0) {
        strError = "Wallet isn't active on this client. Can't scan for MsgChannels";
        return false;
    }

    for (auto wallet : vpwallets) {
        LOCK(wallet->cs_wallet);
        CBlockIndex* blockIndex = chainActive[Params().GetAssetActivationHeight()];

        while (blockIndex) {
            CBlock block;
            if (!ReadBlockFromDisk(block, blockIndex, Params().GetConsensus())) {
                strError = "Block not found on disk";
                return false;
            }

            for (const auto& tx : block.vtx) {

                auto ptx = tx.get();
                if (!ptx) {
                    strError = "Failed to get transaction pointer";
                    return false;
                }

                for (auto out : ptx->vout) {
                    int nType = -1;
                    bool fOwner = false;
                    if (wallet->IsMine(out) == ISMINE_SPENDABLE) { // Is the out mine
                        if (out.scriptPubKey.IsAssetScript(nType, fOwner)) {
                            CAssetOutputEntry assetData;
                            // Get the asset data from the script
                            if (GetAssetData(out.scriptPubKey, assetData)) {
                                AssetType type;
                                IsAssetNameValid(assetData.assetName, type);

                                if (assetData.type == TX_TRANSFER_ASSET) {
                                    if (type == AssetType::MSGCHANNEL || type == AssetType::OWNER) { // Subscribe to any channels or owner tokens you own
                                        AddChannel(*wallet, assetData.assetName);
                                        AddAddressSeen(*wallet, EncodeDestination(assetData.destination));
                                    } else if (type == AssetType::ROOT || type == AssetType::SUB) { // Subscribe to any assets you are sent, if they are sent to a new address
                                        if (!IsChannelSubscribed(*wallet, assetData.assetName + OWNER_TAG)) {
                                            if (!IsAddressSeen(*wallet, EncodeDestination(assetData.destination))) {
                                                AddChannel(*wallet, assetData.assetName + OWNER_TAG);
                                                AddAddressSeen(*wallet, EncodeDestination(assetData.destination));
                                            }
                                        }
                                    }
                                } else if (assetData.type == TX_NEW_ASSET || assetData.type == TX_REISSUE_ASSET) {
                                    if (fOwner || type == AssetType::MSGCHANNEL) {
                                        AddChannel(*wallet, assetData.assetName);
                                        AddAddressSeen(*wallet, EncodeDestination(assetData.destination));
                                    } else if (type == AssetType::ROOT || type == AssetType::SUB || type == AssetType::RESTRICTED) {
                                        AddChannel(*wallet, assetData.assetName + "!");
                                        AddAddressSeen(*wallet, EncodeDestination(assetData.destination));
                                    }
                                }
                            } else {
                                LogPrintf("%s : Failed to get GetAssetData call\n", __func__);
                            }
                        }
                    }
                }
            }
            blockIndex = chainActive[blockIndex->nHeight + 1];
        }

    }
    LogPrintf("%s : Finished scanning wallet message channels\n", __func__);
    return true;
}
#endif

// Wallet asset mutations are written synchronously; there is no shared dirty cache.
size_t GetMessageDirtyCacheSize() { return 0; }

std::string CZMQMessage::createJsonString()
{
    std::string str = "";
    str += "{";
    str += "\"blockheight\": " + std::to_string(this->blockHeight) + ", ";
    str += "\"assetname\": \"" + this->assetName + "\", ";
    str += "\"ipfshash\": \"" + EncodeAssetData(this->ipfsHash) + "\", ";
    str += "\"expiretime\": " + std::to_string(this->nExpireTime);
    str += "}";

    return str;
}
