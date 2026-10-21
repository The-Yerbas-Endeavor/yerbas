// Copyright (c) 2019 The Yerbas Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#ifndef YERBAS_MYASSETSDB_H
#define YERBAS_MYASSETSDB_H

#include <dbwrapper.h>

class CWallet;

// The LevelDB base is only an in-memory view for wallet-backed instances.
// Legacy disk constructors are retained exclusively for migration.
class CWalletAssetDB : public CDBWrapper {
    CWallet* wallet = nullptr;
    std::string section;
    bool Persist(const CDataStream& key, const CDataStream* value);
    bool WriteSerialized(const CDataStream& key, const CDataStream* value, bool sync);
public:
    using CDBWrapper::CDBWrapper;
#ifdef ENABLE_WALLET
    CWalletAssetDB(CWallet& wallet, const std::string& section);
#endif
    template<typename K, typename V> bool Write(const K& key, const V& value, bool sync = false) {
        CDataStream k(SER_DISK, CLIENT_VERSION), v(SER_DISK, CLIENT_VERSION);
        k << key; v << value;
        return WriteSerialized(k, &v, sync);
    }
    template<typename K> bool Erase(const K& key, bool sync = false) {
        CDataStream k(SER_DISK, CLIENT_VERSION); k << key;
        return WriteSerialized(k, nullptr, sync);
    }
};

#ifdef ENABLE_WALLET
bool InitializeWalletAssetStores(CWallet& wallet, bool migrateLegacy);
bool ValidateWalletAssetRecord(const std::pair<std::string, std::vector<unsigned char>>& key, const std::vector<unsigned char>& value);
#endif

class CMessage;
class COutPoint;

class CMessageDB  : public CWalletAssetDB {

public:
    explicit CMessageDB(size_t nCacheSize, bool fMemory = false, bool fWipe = false);
#ifdef ENABLE_WALLET
    explicit CMessageDB(CWallet& wallet);
#endif

    CMessageDB(const CMessageDB&) = delete;
    CMessageDB& operator=(const CMessageDB&) = delete;

    // Database of messages
    bool WriteMessage(const CMessage& message);
    bool ReadMessage(const COutPoint& out, CMessage& message);
    bool EraseMessage(const COutPoint& out);
    bool LoadMessages(std::set<CMessage>& setMessages);
    bool EraseAllMessages(int& count);

    // Write / Read Database flags
    bool WriteFlag(const std::string &name, bool fValue);
    bool ReadFlag(const std::string &name, bool &fValue);

    bool Flush();
};

class CMessageChannelDB  : public CWalletAssetDB {
public:
    explicit CMessageChannelDB(size_t nCacheSize, bool fMemory = false, bool fWipe = false);
#ifdef ENABLE_WALLET
    explicit CMessageChannelDB(CWallet& wallet);
#endif

    CMessageChannelDB(const CMessageChannelDB&) = delete;
    CMessageChannelDB& operator=(const CMessageChannelDB&) = delete;

    // My message channels
    bool WriteMyMessageChannel(const std::string& channelname);
    bool ReadMyMessageChannel(const std::string& channelname);
    bool EraseMyMessageChannel(const std::string& channelname);
    bool LoadMyMessageChannels(std::set<std::string>& setChannels);

    bool WriteUsedAddress(const std::string& address);
    bool ReadUsedAddress(const std::string& address);
    bool EraseUsedAddress(const std::string& address);

    // Write / Read Database flags
    bool WriteFlag(const std::string &name, bool fValue);
    bool ReadFlag(const std::string &name, bool &fValue);

    bool Flush();
};

class CMyRestrictedDB : public CWalletAssetDB {
public:
    explicit CMyRestrictedDB(size_t nCacheSize, bool fMemory = false, bool fWipe = false);
#ifdef ENABLE_WALLET
    explicit CMyRestrictedDB(CWallet& wallet);
#endif

    CMyRestrictedDB(const CMyRestrictedDB&) = delete;
    CMyRestrictedDB& operator=(const CMyRestrictedDB&) = delete;

    bool WriteTaggedAddress(const std::string& address, const std::string& tag_name, const bool fAdd, const uint32_t& nHeight);
    bool ReadTaggedAddress(const std::string& address, const std::string& tag_name, bool& fAdd, uint32_t& nHeight);
    bool EraseTaggedAddress(const std::string& address, const std::string& tag_name);
    bool LoadMyTaggedAddresses(std::vector<std::tuple<std::string, std::string, bool, uint32_t> >& vecTaggedAddresses);

    bool WriteRestrictedAddress(const std::string& address, const std::string& tag_name, const bool fAdd, const uint32_t& nHeight);
    bool ReadRestrictedAddress(const std::string& address, const std::string& tag_name, bool& fAdd, uint32_t& nHeight);
    bool EraseRestrictedAddress(const std::string& address, const std::string& tag_name);
    bool LoadMyRestrictedAddresses(std::vector<std::tuple<std::string, std::string, bool, uint32_t> >& vecRestrictedAddresses);

    // Write / Read Database flags
    bool WriteFlag(const std::string &name, bool fValue);
    bool ReadFlag(const std::string &name, bool &fValue);
};


#endif //YERBAS_MYASSETSDB_H
