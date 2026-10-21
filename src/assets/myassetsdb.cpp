// Copyright (c) 2018-2020 The Yerbas Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.
#include "validation.h"
#include "myassetsdb.h"
#include "messages.h"
#include <boost/thread.hpp>
#ifdef ENABLE_WALLET
#include "wallet/wallet.h"
#include "base58.h"
#include "script/ismine.h"
#endif

static const char MESSAGE_FLAG = 'Z'; // Message
static const char MY_MESSAGE_CHANNEL = 'C'; // My followed Channels
static const char MY_SEEN_ADDRESSES = 'S'; // Addresses that have been seen on the chain
static const char DB_FLAG = 'D'; // Database Flags

static const char MY_TAGGED_ADDRESSES = 'T'; // Addresses that have been tagged
static const char MY_RESTRICTED_ADDRESSES = 'R'; // Addresses that have been restricted

CMessageDB::CMessageDB(size_t nCacheSize, bool fMemory, bool fWipe) : CWalletAssetDB(GetDataDir() / "messages" / "messages", nCacheSize, fMemory, fWipe) {
}

bool CMessageDB::WriteMessage(const CMessage &message)
{
    return Write(std::make_pair(MESSAGE_FLAG, message.out), message);
}

bool CMessageDB::ReadMessage(const COutPoint &out, CMessage &message)
{
    return Read(std::make_pair(MESSAGE_FLAG, out), message);
}

bool CMessageDB::EraseMessage(const COutPoint &out)
{
    return Erase(std::make_pair(MESSAGE_FLAG, out));
}

bool CMessageDB::LoadMessages(std::set<CMessage>& setMessages)
{
    std::unique_ptr<CDBIterator> pcursor(NewIterator());

    pcursor->Seek(std::make_pair(MESSAGE_FLAG, COutPoint()));

    // Load messages
    while (pcursor->Valid()) {
        boost::this_thread::interruption_point();
        std::pair<char, COutPoint> key;
        if (pcursor->GetKey(key) && key.first == MESSAGE_FLAG) {
            CMessage message;
            if (pcursor->GetValue(message)) {
                setMessages.insert(message);
                pcursor->Next();
            } else {
                return error("%s: failed to read wallet asset message", __func__);
            }
        } else {
            break;
        }
    }
    return true;
}

bool CMessageDB::EraseAllMessages(int& count)
{
    std::set<CMessage> setMessages;
    std::unique_ptr<CDBIterator> pcursor(NewIterator());

    pcursor->Seek(std::make_pair(MESSAGE_FLAG, COutPoint()));

    // Load messages
    while (pcursor->Valid()) {
        boost::this_thread::interruption_point();
        std::pair<char, COutPoint> key;
        if (pcursor->GetKey(key) && key.first == MESSAGE_FLAG) {
            CMessage message;
            if (pcursor->GetValue(message)) {
                setMessages.insert(message);
                pcursor->Next();
            } else {
                return error("%s: failed to read wallet asset message", __func__);
            }
        } else {
            break;
        }
    }

    count += setMessages.size();
    for (const auto& message : setMessages)
        if (!EraseMessage(message.out)) return false;

    return true;
}

bool CMessageDB::Flush() {
    try {

        for (auto messageRemove : setDirtyMessagesRemove) {
            if (!EraseMessage(messageRemove))
                return error("%s: failed to erase message %s", __func__, messageRemove.ToString());
        }

        for (auto messageAdd : mapDirtyMessagesAdd) {
            if (!WriteMessage(messageAdd.second))
                return error("%s: failed to write message %s", __func__, messageAdd.second.ToString());

            mapDirtyMessagesOrphaned.erase(messageAdd.first);
        }

        for (auto orphans : mapDirtyMessagesOrphaned) {
            CMessage msg = orphans.second;
            msg.status = MessageStatus::ORPHAN;
            if (!WriteMessage(msg))
                return error("%s: failed to write message orphan %s", __func__, msg.ToString());
        }

        setDirtyMessagesRemove.clear();
        mapDirtyMessagesAdd.clear();
        mapDirtyMessagesOrphaned.clear();
    } catch (const std::runtime_error& e) {
        return error("%s : %s ", __func__, std::string("System error while flushing messages: ") + e.what());
    }

    return true;
}

CMessageChannelDB::CMessageChannelDB(size_t nCacheSize, bool fMemory, bool fWipe) : CWalletAssetDB(GetDataDir() / "messages" / "channels", nCacheSize, fMemory, fWipe) {
}

bool CMessageChannelDB::WriteMyMessageChannel(const std::string& channelname)
{
    return Write(std::make_pair(MY_MESSAGE_CHANNEL, channelname), 1);
}

bool CMessageChannelDB::ReadMyMessageChannel(const std::string& channelname)
{
    int i = 1;
    return Read(std::make_pair(MY_MESSAGE_CHANNEL, channelname), i);
}

bool CMessageChannelDB::EraseMyMessageChannel(const std::string& channelname)
{
    return Erase(std::make_pair(MY_MESSAGE_CHANNEL, channelname));
}

bool CMessageChannelDB::LoadMyMessageChannels(std::set<std::string>& setChannels)
{
    setChannels.clear();
    std::unique_ptr<CDBIterator> pcursor(NewIterator());

    pcursor->Seek(std::make_pair(MY_MESSAGE_CHANNEL, std::string()));

    // Load messages
    while (pcursor->Valid()) {
        boost::this_thread::interruption_point();
        std::pair<char, std::string> key;
        if (pcursor->GetKey(key) && key.first == MY_MESSAGE_CHANNEL) {
            setChannels.insert(key.second);
            pcursor->Next();
        } else {
            break;
        }
    }

    return true;
}

bool CMessageDB::WriteFlag(const std::string &name, bool fValue)
{
    return Write(std::make_pair(DB_FLAG, name), fValue ? '1' : '0');
}

bool CMessageDB::ReadFlag(const std::string &name, bool &fValue)
{
    char ch;
    if (!Read(std::make_pair(DB_FLAG, name), ch))
        return false;
    fValue = ch == '1';
    return true;
}


bool CMessageChannelDB::WriteUsedAddress(const std::string& address)
{
    return Write(std::make_pair(MY_SEEN_ADDRESSES, address), 1);
}
bool CMessageChannelDB::ReadUsedAddress(const std::string& address)
{
    int i;
    return Read(std::make_pair(MY_SEEN_ADDRESSES, address), i);
}
bool CMessageChannelDB::EraseUsedAddress(const std::string& address)
{
    return Erase(std::make_pair(MY_SEEN_ADDRESSES, address));
}

bool CMessageChannelDB::WriteFlag(const std::string &name, bool fValue)
{
    return Write(std::make_pair(DB_FLAG, name), fValue ? '1' : '0');
}

bool CMessageChannelDB::ReadFlag(const std::string &name, bool &fValue)
{
    char ch;
    if (!Read(std::make_pair(DB_FLAG, name), ch))
        return false;
    fValue = ch == '1';
    return true;
}

bool CMessageChannelDB::Flush() {
    try {
        LogPrintf("%s: Flushing messagechannelsdb addSize:%u, removeSize:%u, seenAddressSize:%u\n", __func__, setDirtyChannelsAdd.size(), setDirtyChannelsRemove.size(), setDirtySeenAddressAdd.size());

        for (auto channelRemove : setDirtyChannelsRemove) {
            if (!EraseMyMessageChannel(channelRemove))
                return error("%s: failed to erase messagechannel %s", __func__, channelRemove);
        }

        for (auto channelAdd : setDirtyChannelsAdd) {
            if (!WriteMyMessageChannel(channelAdd))
                return error("%s: failed to write messagechannel %s", __func__, channelAdd);
        }

        for (auto seenAddress : setDirtySeenAddressAdd) {
            if (!WriteUsedAddress(seenAddress))
                return error("%s: failed to write seenaddress %s", __func__, seenAddress);
        }

        setDirtyChannelsRemove.clear();
        setDirtyChannelsAdd.clear();
        setDirtySeenAddressAdd.clear();
        setSubscribedChannelsAskedForFalse.clear();
        setAddressAskedForFalse.clear();
    } catch (const std::runtime_error& e) {
        return error("%s : %s ", __func__, std::string("System error while flushing messagechannels: ") + e.what());
    }

    return true;
}


CMyRestrictedDB::CMyRestrictedDB(size_t nCacheSize, bool fMemory, bool fWipe) : CWalletAssetDB(GetDataDir() / "myrestricted", nCacheSize, fMemory, fWipe) {
}

bool CMyRestrictedDB::WriteTaggedAddress(const std::string& address, const std::string& tag_name, const bool fAdd, const uint32_t& nHeight)
{
    return Write(std::make_pair(MY_TAGGED_ADDRESSES, std::make_pair(address, tag_name)), std::make_pair(fAdd ? 1 : 0, nHeight));
}
bool CMyRestrictedDB::ReadTaggedAddress(const std::string& address, const std::string& tag_name, bool& fAdd, uint32_t& nHeight)
{
    std::pair<int, uint32_t> value;
    bool ret = Read(std::make_pair(MY_TAGGED_ADDRESSES, std::make_pair(address, tag_name)), value);
    fAdd = value.first;
    nHeight = value.second;
    return ret;
}
bool CMyRestrictedDB::EraseTaggedAddress(const std::string& address, const std::string& tag_name)
{
    return Erase(std::make_pair(MY_TAGGED_ADDRESSES, std::make_pair(address, tag_name)));
}
bool CMyRestrictedDB::LoadMyTaggedAddresses(std::vector<std::tuple<std::string, std::string, bool, uint32_t> >& vecTaggedAddresses)
{
    vecTaggedAddresses.clear();
    std::unique_ptr<CDBIterator> pcursor(NewIterator());

    pcursor->Seek(std::make_pair(MY_TAGGED_ADDRESSES, std::make_pair(std::string(), std::string())));

    // Load messages
    while (pcursor->Valid()) {
        boost::this_thread::interruption_point();
        std::pair<char, std::pair<std::string, std::string>> key;
        if (pcursor->GetKey(key) && key.first == MY_TAGGED_ADDRESSES) {
            std::pair<int, uint32_t> value;
            if (pcursor->GetValue(value)) {
                vecTaggedAddresses.emplace_back(std::make_tuple(key.second.first, key.second.second, value.first ? true : false, value.second));
            }
            pcursor->Next();
        } else {
            break;
        }
    }

    return true;
}

bool CMyRestrictedDB::WriteRestrictedAddress(const std::string& address, const std::string& tag_name, const bool fAdd, const uint32_t& nHeight)
{
    return Write(std::make_pair(MY_RESTRICTED_ADDRESSES, std::make_pair(address, tag_name)), std::make_pair(fAdd ? 1 : 0, nHeight));
}

bool CMyRestrictedDB::ReadRestrictedAddress(const std::string& address, const std::string& tag_name, bool& fAdd, uint32_t& nHeight)
{
    std::pair<int, uint32_t> value;
    bool ret = Read(std::make_pair(MY_RESTRICTED_ADDRESSES, std::make_pair(address, tag_name)), value);
    fAdd = value.first;
    nHeight = value.second;
    return ret;
}

bool CMyRestrictedDB::EraseRestrictedAddress(const std::string& address, const std::string& tag_name)
{
    return Erase(std::make_pair(MY_RESTRICTED_ADDRESSES, std::make_pair(address, tag_name)));
}

bool CMyRestrictedDB::LoadMyRestrictedAddresses(std::vector<std::tuple<std::string, std::string, bool, uint32_t> >& vecRestrictedAddresses)
{
    vecRestrictedAddresses.clear();
    std::unique_ptr<CDBIterator> pcursor(NewIterator());

    pcursor->Seek(std::make_pair(MY_RESTRICTED_ADDRESSES, std::make_pair(std::string(), std::string())));

    // Load messages
    while (pcursor->Valid()) {
        boost::this_thread::interruption_point();
        std::pair<char, std::pair<std::string, std::string>> key;
        if (pcursor->GetKey(key) && key.first == MY_RESTRICTED_ADDRESSES) {
            std::pair<int, uint32_t> value;
            if (pcursor->GetValue(value)) {
                vecRestrictedAddresses.emplace_back(std::make_tuple(key.second.first, key.second.second, value.first ? true : false, value.second));
            }
            pcursor->Next();
        } else {
            break;
        }
    }

    return true;
}


bool CMyRestrictedDB::WriteFlag(const std::string &name, bool fValue)
{
    return Write(std::make_pair(DB_FLAG, name), fValue ? '1' : '0');
}

bool CMyRestrictedDB::ReadFlag(const std::string &name, bool &fValue)
{
    char ch;
    if (!Read(std::make_pair(DB_FLAG, name), ch))
        return false;
    fValue = ch == '1';
    return true;
}

bool CWalletAssetDB::WriteSerialized(const CDataStream& key, const CDataStream* value, bool sync)
{
#ifdef ENABLE_WALLET
    if (wallet) {
        LOCK(wallet->cs_wallet);
        if (!Persist(key, value)) return false;
        return value ? CDBWrapper::Write(key, *value, sync) : CDBWrapper::Erase(key, sync);
    }
#endif
    return value ? CDBWrapper::Write(key, *value, sync) : CDBWrapper::Erase(key, sync);
}

bool CWalletAssetDB::Persist(const CDataStream& key, const CDataStream* value)
{
#ifdef ENABLE_WALLET
    if (wallet) {
        LOCK(wallet->cs_wallet);
        const auto recordKey = std::make_pair(section, std::vector<unsigned char>(key.begin(), key.end()));
        CWalletDB db(wallet->GetDBHandle());
        if (value) {
            std::vector<unsigned char> bytes(value->begin(), value->end());
            if (!ValidateWalletAssetRecord(recordKey, bytes) || !db.WriteAssetRecord(recordKey, bytes)) return false;
            wallet->walletAssetRecords[recordKey] = std::move(bytes);
        } else {
            if (!db.EraseAssetRecord(recordKey)) return false;
            wallet->walletAssetRecords.erase(recordKey);
        }
    }
#endif
    return true;
}

#ifdef ENABLE_WALLET
CWalletAssetDB::CWalletAssetDB(CWallet& owner, const std::string& name)
    : CDBWrapper(fs::path("wallet-assets-memory") / name, 1 << 20, true, false), wallet(&owner), section(name)
{
    for (const auto& record : owner.walletAssetRecords) {
        if (record.first.first != section) continue;
        CDataStream key(record.first.second, SER_DISK, CLIENT_VERSION);
        CDataStream value(record.second, SER_DISK, CLIENT_VERSION);
        if (!CDBWrapper::Write(key, value)) throw std::runtime_error("Cannot initialize wallet asset view");
    }
}

CMessageDB::CMessageDB(CWallet& wallet) : CWalletAssetDB(wallet, "messages") {}
CMessageChannelDB::CMessageChannelDB(CWallet& wallet) : CWalletAssetDB(wallet, "channels") {}
CMyRestrictedDB::CMyRestrictedDB(CWallet& wallet) : CWalletAssetDB(wallet, "restricted") {}

CSnapshotRequestDB::CSnapshotRequestDB(CWallet& wallet) : CWalletAssetDB(wallet, "snapshotrequests") {}
CAssetSnapshotDB::CAssetSnapshotDB(CWallet& wallet) : CWalletAssetDB(wallet, "snapshots") {}
CDistributeSnapshotRequestDB::CDistributeSnapshotRequestDB(CWallet& wallet) : CWalletAssetDB(wallet, "distributions") {}

bool InitializeWalletAssetStores(CWallet& wallet, bool migrateLegacy)
{
    LOCK(wallet.cs_wallet);
    const auto marker = std::make_pair(std::string("migration"), std::vector<unsigned char>());
    if (!wallet.walletAssetRecords.count(marker)) {
        auto records = wallet.walletAssetRecords;
        if (migrateLegacy) {
            const std::vector<std::pair<std::string, fs::path>> sources = {
                {"messages", GetDataDir() / "messages" / "messages"},
                {"channels", GetDataDir() / "messages" / "channels"},
                {"restricted", GetDataDir() / "myrestricted"},
                {"snapshotrequests", GetDataDir() / "rewards" / "snapshotrequest"},
                {"snapshots", GetDataDir() / "rewards" / "assetsnapshot"},
                {"distributions", GetDataDir() / "rewards" / "distributerequests"}
            };
            for (const auto& source : sources) {
                if (!fs::exists(source.second)) continue;
                if (!fs::exists(source.second / "CURRENT")) return false;
                // Never wipe or delete the legacy database. Missing stores are not created.
                CDBWrapper legacy(source.second, 1 << 20, false, false);
                std::unique_ptr<CDBIterator> cursor(legacy.NewIterator());
                for (cursor->SeekToFirst(); cursor->Valid(); cursor->Next()) {
                    CDataStream key = cursor->GetKey(), value(SER_DISK, CLIENT_VERSION);
                    if (!cursor->GetValue(value)) return false;
                    // Ignore LevelDB's internal obfuscation key; preserve all application records.
                    if (key.empty()) return false;
                    try {
                        auto special = key;
                        std::string name;
                        special >> name;
                        if (special.empty() && name == std::string("\0obfuscate_key", 14)) continue;
                    } catch (const std::exception&) {}
                    if (source.first == "restricted" && (key[0] == 'T' || key[0] == 'R')) {
                        auto decoded = key;
                        std::pair<char, std::pair<std::string, std::string>> addressKey;
                        decoded >> addressKey;
                        if (!(IsMine(wallet, DecodeDestination(addressKey.second.first)) & ISMINE_ALL)) continue;
                    }
                    if (source.first == "distributions" && key[0] == 'D') {
                        CRewardSnapshot plan;
                        value >> plan;
                        if (!value.empty()) return false;
                        plan.nStatus = CRewardSnapshot::PAUSED;
                        value.clear(); value << plan;
                    }
                    records.emplace(std::make_pair(source.first, std::vector<unsigned char>(key.begin(), key.end())),
                                    std::vector<unsigned char>(value.begin(), value.end()));
                }
                if (!cursor->StatusOK()) return false;
            }
        }
        records[marker] = {1};
        for (const auto& record : records)
            if (!ValidateWalletAssetRecord(record.first, record.second)) return false;
        CWalletDB db(wallet.GetDBHandle());
        if (!db.TxnBegin()) return false;
        for (const auto& record : records) {
            if (!db.WriteAssetRecord(record.first, record.second)) {
                db.TxnAbort();
                return false;
            }
        }
        if (!db.TxnCommit()) return false;
        wallet.walletAssetRecords = std::move(records);
    } else if (wallet.walletAssetRecords.at(marker) != std::vector<unsigned char>{1}) {
        return false;
    }
    wallet.assetMessages.reset(new CMessageDB(wallet));
    wallet.assetChannels.reset(new CMessageChannelDB(wallet));
    wallet.assetRestrictions.reset(new CMyRestrictedDB(wallet));
    wallet.assetSnapshotRequests.reset(new CSnapshotRequestDB(wallet));
    wallet.assetSnapshots.reset(new CAssetSnapshotDB(wallet));
    wallet.assetDistributions.reset(new CDistributeSnapshotRequestDB(wallet));
    wallet.rewardSnapshots.clear();
    wallet.assetDistributions->LoadAllDistributeSnapshot(wallet.rewardSnapshots);
    return true;
}
#endif

#ifdef ENABLE_WALLET
bool ValidateWalletAssetRecord(const std::pair<std::string, std::vector<unsigned char>>& recordKey,
                               const std::vector<unsigned char>& bytes)
{
    if (recordKey.first == "migration") return recordKey.second.empty() && bytes == std::vector<unsigned char>{1};
    if (recordKey.first != "messages" && recordKey.first != "channels" && recordKey.first != "restricted" && recordKey.first != "snapshotrequests" && recordKey.first != "snapshots" && recordKey.first != "distributions") return false;
    try {
        CDataStream key(recordKey.second, SER_DISK, CLIENT_VERSION), value(bytes, SER_DISK, CLIENT_VERSION);
        char type;
        key >> type;
        if (recordKey.first == "snapshotrequests" && type == 'S') {
            std::string id; CSnapshotRequestDBEntry entry;
            key >> id; value >> entry;
            if (entry.heightForSnapshot < 0 || id != entry.heightAndName || id != std::to_string(entry.heightForSnapshot) + entry.assetName) return false;
        } else if (recordKey.first == "snapshots" && type == 'C') {
            std::string id; CAssetSnapshotDBEntry entry;
            key >> id; value >> entry;
            if (entry.height < 0 || id != entry.heightAndName || id != std::to_string(entry.height) + entry.assetName) return false;
        } else if (recordKey.first == "distributions" && type == 'D') {
            uint256 hash; CRewardSnapshot plan;
            key >> hash; value >> plan;
            if (hash != plan.GetHash() || plan.nStatus < 0 || plan.nStatus > CRewardSnapshot::PAUSED) return false;
        } else if (recordKey.first == "distributions" && type == 'T') {
            std::pair<uint256, int> batch; uint256 txid;
            key >> batch; value >> txid;
            if (batch.second < 0 || txid.IsNull()) return false;
        } else if (type == DB_FLAG && recordKey.first != "distributions") {
            std::string name; char flag;
            key >> name; value >> flag;
            if (flag != '0' && flag != '1') return false;
        } else if (recordKey.first == "messages" && type == MESSAGE_FLAG) {
            COutPoint out; CMessage message;
            key >> out; value >> message;
            if (out != message.out || IntFromMessageStatus(message.status) < 0 || IntFromMessageStatus(message.status) > 6) return false;
        } else if (recordKey.first == "channels" && (type == MY_MESSAGE_CHANNEL || type == MY_SEEN_ADDRESSES)) {
            std::string name; int present;
            key >> name; value >> present;
            if (present != 1) return false;
        } else if (recordKey.first == "restricted" && (type == MY_TAGGED_ADDRESSES || type == MY_RESTRICTED_ADDRESSES)) {
            std::pair<std::string, std::string> address;
            std::pair<int, uint32_t> status;
            key >> address; value >> status;
            if (status.first != 0 && status.first != 1) return false;
        } else return false;
        return key.empty() && value.empty();
    } catch (const std::exception&) { return false; }
}
#endif
