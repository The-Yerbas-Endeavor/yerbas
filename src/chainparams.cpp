// Copyright (c) 2010 Satoshi Nakamoto
// Copyright (c) 2009-2014 The Bitcoin Core developers
// Copyright (c) 2014-2020 The Dash Core developers
// Copyright (c) 2022 The Yerbas Endeavor developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <chainparams.h>
#include <consensus/merkle.h>

#include <tinyformat.h>
#include <util.h>
#include <utilstrencodings.h>

#include <arith_uint256.h>

#include <assert.h>
#include <iostream>
#include <string>
#include <memory>

#include <chainparamsseeds.h>

static size_t lastCheckMnCount = 0;
static int lastCheckHeight = 0;
static bool lastCheckedLowLLMQParams = false;

static CBlock CreateGenesisBlock(const char* pszTimestamp, const CScript& genesisOutputScript, uint32_t nTime, uint32_t nNonce, uint32_t nBits, int32_t nVersion, const CAmount& genesisReward)
{
    CMutableTransaction txNew;
    txNew.nVersion = 1;
    txNew.vin.resize(1);
    txNew.vout.resize(1);
    txNew.vin[0].scriptSig = CScript() << 486604799 << CScriptNum(4) << std::vector<unsigned char>((const unsigned char*)pszTimestamp, (const unsigned char*)pszTimestamp + strlen(pszTimestamp));
    txNew.vout[0].nValue = genesisReward;
    txNew.vout[0].scriptPubKey = genesisOutputScript;

    CBlock genesis;
    genesis.nTime    = nTime;
    genesis.nBits    = nBits;
    genesis.nNonce   = nNonce;
    genesis.nVersion = nVersion;
    genesis.vtx.push_back(MakeTransactionRef(std::move(txNew)));
    genesis.hashPrevBlock.SetNull();
    genesis.hashMerkleRoot = BlockMerkleRoot(genesis);
    return genesis;
}

static CBlock CreateDevNetGenesisBlock(const uint256 &prevBlockHash, const std::string& devNetName, uint32_t nTime, uint32_t nNonce, uint32_t nBits, const CAmount& genesisReward)
{
    assert(!devNetName.empty());

    CMutableTransaction txNew;
    txNew.nVersion = 1;
    txNew.vin.resize(1);
    txNew.vout.resize(1);
    // put height (BIP34) and devnet name into coinbase
    txNew.vin[0].scriptSig = CScript() << 1 << std::vector<unsigned char>(devNetName.begin(), devNetName.end());
    txNew.vout[0].nValue = genesisReward;
    txNew.vout[0].scriptPubKey = CScript() << OP_RETURN;

    CBlock genesis;
    genesis.nTime    = nTime;
    genesis.nBits    = nBits;
    genesis.nNonce   = nNonce;
    genesis.nVersion = 4;
    genesis.vtx.push_back(MakeTransactionRef(std::move(txNew)));
    genesis.hashPrevBlock = prevBlockHash;
    genesis.hashMerkleRoot = BlockMerkleRoot(genesis);
    return genesis;
}


static CBlock CreateGenesisBlock(uint32_t nTime, uint32_t nNonce, uint32_t nBits, int32_t nVersion, const CAmount& genesisReward)
{
    const char* pszTimestamp = "09/May/2022 Yerbas. The 'Good Shit' coin!";
    const CScript genesisOutputScript = CScript() << ParseHex("04678afdb0fe5548271967f1a67130b7105cd6a828e03909a67962e0ea1f61deb649f6bc3f4cef38c4f35504e51ec112de5c384df7ba0b8d578a4c702b6bf11d5f") << OP_CHECKSIG;
    return CreateGenesisBlock(pszTimestamp, genesisOutputScript, nTime, nNonce, nBits, nVersion, genesisReward);
}


void CChainParams::UpdateVersionBitsParameters(Consensus::DeploymentPos d, int64_t nStartTime, int64_t nTimeout, int64_t nWindowSize, int64_t nThresholdStart, int64_t nThresholdMin, int64_t nFalloffCoeff)
{
    consensus.vDeployments[d].nStartTime = nStartTime;
    consensus.vDeployments[d].nTimeout = nTimeout;
    if (nWindowSize != -1) {
            consensus.vDeployments[d].nWindowSize = nWindowSize;
    }
    if (nThresholdStart != -1) {
        consensus.vDeployments[d].nThresholdStart = nThresholdStart;
    }
    if (nThresholdMin != -1) {
        consensus.vDeployments[d].nThresholdMin = nThresholdMin;
    }
    if (nFalloffCoeff != -1) {
        consensus.vDeployments[d].nFalloffCoeff = nFalloffCoeff;
    }
}

//void CChainParams::UpdateDIP3Parameters(int nActivationHeight, int nEnforcementHeight)
//{
//    consensus.DIP0003Height = nActivationHeight;
//    consensus.DIP0003EnforcementHeight = nEnforcementHeight;
//}

void CChainParams::UpdateBudgetParameters(int nSmartnodePaymentsStartBlock, int nBudgetPaymentsStartBlock, int nSuperblockStartBlock)
{
    consensus.nSmartnodePaymentsStartBlock = nSmartnodePaymentsStartBlock;
    consensus.nBudgetPaymentsStartBlock = nBudgetPaymentsStartBlock;
    consensus.nSuperblockStartBlock = nSuperblockStartBlock;
}

void CChainParams::UpdateSubsidyAndDiffParams(int nMinimumDifficultyBlocks, int nHighSubsidyBlocks, int nHighSubsidyFactor)
{
    consensus.nMinimumDifficultyBlocks = nMinimumDifficultyBlocks;
    consensus.nHighSubsidyBlocks = nHighSubsidyBlocks;
    consensus.nHighSubsidyFactor = nHighSubsidyFactor;
}

void CChainParams::UpdateLLMQChainLocks(Consensus::LLMQType llmqType) {
    consensus.llmqTypeChainLocks = llmqType;
}

void CChainParams::UpdateLLMQInstantSend(Consensus::LLMQType llmqType) {
    consensus.llmqTypeInstantSend = llmqType;
}

static CBlock FindDevNetGenesisBlock(const CBlock &prevBlock, const CAmount& reward)
{
    std::string devNetName = gArgs.GetDevNetName();
    assert(!devNetName.empty());

    CBlock block = CreateDevNetGenesisBlock(prevBlock.GetHash(), devNetName.c_str(), prevBlock.nTime + 1, 0, prevBlock.nBits, reward);

    arith_uint256 bnTarget;
    bnTarget.SetCompact(block.nBits);

    for (uint32_t nNonce = 0; nNonce < UINT32_MAX; nNonce++) {
        block.nNonce = nNonce;

        uint256 hash = block.GetHash();
        if (UintToArith256(hash) <= bnTarget)
            return block;
    }

    // This is very unlikely to happen as we start the devnet with a very low difficulty. In many cases even the first
    // iteration of the above loop will give a result already
    error("FindDevNetGenesisBlock: could not find devnet genesis block for %s", devNetName);
    assert(false);
}

static void FindMainNetGenesisBlock(uint32_t nTime, uint32_t nBits, const char* network)
{
    CBlock block = CreateGenesisBlock(nTime, 0, nBits, 4, 5000 * COIN);

    arith_uint256 bnTarget;
    bnTarget.SetCompact(block.nBits);

    for (uint32_t nNonce = 0; nNonce < UINT32_MAX; nNonce++) {
        block.nNonce = nNonce;

        uint256 hash = block.GetPOWHash();
        if (nNonce % 48 == 0) {
        	printf("\nrnonce=%d, pow is %s\n", nNonce, hash.GetHex().c_str());
        }
        if (UintToArith256(hash) <= bnTarget) {
        	printf("\n%s net\n", network);
        	printf("\ngenesis is %s\n", block.ToString().c_str());
        	printf("\npow is %s\n", hash.GetHex().c_str());
        	printf("\ngenesisNonce is %d\n", nNonce);
        	std::cout << "Genesis Merkle " << block.hashMerkleRoot.GetHex() << std::endl;
        	return;
        }

    }

    // This is very unlikely to happen as we start the devnet with a very low difficulty. In many cases even the first
    // iteration of the above loop will give a result already
    error("%sNetGenesisBlock: could not find %s genesis block",network, network);
    assert(false);
}

static Consensus::LLMQParams llmq200_2 = {
        .type = Consensus::LLMQ_50_60,
        .name = "llmq_3_200",
        .size = 200,
        .minSize = 2,
        .threshold = 2,

        .dkgInterval = 30, // one DKG per hour
        .dkgPhaseBlocks = 2,
        .dkgMiningWindowStart = 10, // dkgPhaseBlocks * 5 = after finalization
        .dkgMiningWindowEnd = 18,
        .dkgBadVotesThreshold = 8,

        .signingActiveQuorumCount = 2, // just a few ones to allow easier testing

        .keepOldConnections = 3,
        .recoveryMembers = 3,
};

static Consensus::LLMQParams llmq3_60 = {
        .type = Consensus::LLMQ_50_60,
        .name = "llmq_3_60",
        .size = 3,
        .minSize = 2,
        .threshold = 2,

        .dkgInterval = 30, // one DKG per hour
        .dkgPhaseBlocks = 2,
        .dkgMiningWindowStart = 10, // dkgPhaseBlocks * 5 = after finalization
        .dkgMiningWindowEnd = 18,
        .dkgBadVotesThreshold = 2,

        .signingActiveQuorumCount = 2, // just a few ones to allow easier testing

        .keepOldConnections = 3,
};

static Consensus::LLMQParams llmq5_60 = {
        .type = Consensus::LLMQ_400_60,
        .name = "llmq_20_60",
        .size = 5,
        .minSize = 4,
        .threshold = 3,

        .dkgInterval = 30 * 12, // one DKG every 12 hours
        .dkgPhaseBlocks = 4,
        .dkgMiningWindowStart = 20, // dkgPhaseBlocks * 5 = after finalization
        .dkgMiningWindowEnd = 28,
        .dkgBadVotesThreshold = 30,

        .signingActiveQuorumCount = 4, // two days worth of LLMQs

        .keepOldConnections = 5,
        .recoveryMembers = 5,
};

static Consensus::LLMQParams llmq5_85 = {
        .type = Consensus::LLMQ_400_85,
        .name = "llmq_20_85",
        .size = 5,
        .minSize = 4,
        .threshold = 3,

        .dkgInterval = 30 * 24, // one DKG every 24 hours
        .dkgPhaseBlocks = 4,
        .dkgMiningWindowStart = 20, // dkgPhaseBlocks * 5 = after finalization
        .dkgMiningWindowEnd = 48, // give it a larger mining window to make sure it is mined
        .dkgBadVotesThreshold = 30,

        .signingActiveQuorumCount = 4, // four days worth of LLMQs

        .keepOldConnections = 5,
        .recoveryMembers = 5,
};

static Consensus::LLMQParams llmq20_60 = {
        .type = Consensus::LLMQ_400_60,
        .name = "llmq_20_60",
        .size = 20,
        .minSize = 15,
        .threshold = 12,

        .dkgInterval = 30 * 12, // one DKG every 12 hours
        .dkgPhaseBlocks = 4,
        .dkgMiningWindowStart = 20, // dkgPhaseBlocks * 5 = after finalization
        .dkgMiningWindowEnd = 28,
        .dkgBadVotesThreshold = 30,

        .signingActiveQuorumCount = 4, // two days worth of LLMQs

        .keepOldConnections = 5,
};

static Consensus::LLMQParams llmq20_85 = {
        .type = Consensus::LLMQ_400_85,
        .name = "llmq_20_85",
        .size = 20,
        .minSize = 18,
        .threshold = 17,

        .dkgInterval = 30 * 24, // one DKG every 24 hours
        .dkgPhaseBlocks = 4,
        .dkgMiningWindowStart = 20, // dkgPhaseBlocks * 5 = after finalization
        .dkgMiningWindowEnd = 48, // give it a larger mining window to make sure it is mined
        .dkgBadVotesThreshold = 30,

        .signingActiveQuorumCount = 4, // four days worth of LLMQs

        .keepOldConnections = 5,
};

static Consensus::LLMQParams llmq10_60 = {
        .type = Consensus::LLMQ_50_60,
        .name = "llmq_10_60",
        .size = 10,
        .minSize = 8,
        .threshold = 7,

        .dkgInterval = 30, // one DKG per hour
        .dkgPhaseBlocks = 2,
        .dkgMiningWindowStart = 10, // dkgPhaseBlocks * 5 = after finalization
        .dkgMiningWindowEnd = 18,
        .dkgBadVotesThreshold = 8,

        .signingActiveQuorumCount = 6, // just a few ones to allow easier testing

        .keepOldConnections = 7,
        .recoveryMembers = 7,
};

static Consensus::LLMQParams llmq40_60 = {
        .type = Consensus::LLMQ_400_60,
        .name = "llmq_40_60",
        .size = 40,
        .minSize = 30,
        .threshold = 24,

        .dkgInterval = 30 * 12, // one DKG every 12 hours
        .dkgPhaseBlocks = 4,
        .dkgMiningWindowStart = 20, // dkgPhaseBlocks * 5 = after finalization
        .dkgMiningWindowEnd = 28,
        .dkgBadVotesThreshold = 30,

        .signingActiveQuorumCount = 4, // two days worth of LLMQs

        .keepOldConnections = 5,
        .recoveryMembers = 5,
};

static Consensus::LLMQParams llmq40_85 = {
        .type = Consensus::LLMQ_400_85,
        .name = "llmq_40_85",
        .size = 40,
        .minSize = 35,
        .threshold = 34,

        .dkgInterval = 30 * 24, // one DKG every 24 hours
        .dkgPhaseBlocks = 4,
        .dkgMiningWindowStart = 20, // dkgPhaseBlocks * 5 = after finalization
        .dkgMiningWindowEnd = 48, // give it a larger mining window to make sure it is mined
        .dkgBadVotesThreshold = 30,

        .signingActiveQuorumCount = 4, // four days worth of LLMQs

        .keepOldConnections = 5,
        .recoveryMembers = 5,
};

static Consensus::LLMQParams llmq50_60 = {
        .type = Consensus::LLMQ_50_60,
        .name = "llmq_50_60",
        .size = 50,
        .minSize = 40,
        .threshold = 30,

        .dkgInterval = 30, // one DKG per hour
        .dkgPhaseBlocks = 2,
        .dkgMiningWindowStart = 10, // dkgPhaseBlocks * 5 = after finalization
        .dkgMiningWindowEnd = 18,
        .dkgBadVotesThreshold = 40,

        .signingActiveQuorumCount = 24, // a full day worth of LLMQs

        .keepOldConnections = 25,
        .recoveryMembers = 25,
};

static Consensus::LLMQParams llmq400_60 = {
        .type = Consensus::LLMQ_400_60,
        .name = "llmq_400_60",
        .size = 400,
        .minSize = 300,
        .threshold = 240,

        .dkgInterval = 30 * 12, // one DKG every 12 hours
        .dkgPhaseBlocks = 4,
        .dkgMiningWindowStart = 20, // dkgPhaseBlocks * 5 = after finalization
        .dkgMiningWindowEnd = 28,
        .dkgBadVotesThreshold = 300,

        .signingActiveQuorumCount = 4, // two days worth of LLMQs

        .keepOldConnections = 5,
        .recoveryMembers = 100,
};

// Used for deployment and min-proto-version signalling, so it needs a higher threshold
static Consensus::LLMQParams llmq400_85 = {
        .type = Consensus::LLMQ_400_85,
        .name = "llmq_400_85",
        .size = 400,
        .minSize = 350,
        .threshold = 340,

        .dkgInterval = 30 * 24, // one DKG every 24 hours
        .dkgPhaseBlocks = 4,
        .dkgMiningWindowStart = 20, // dkgPhaseBlocks * 5 = after finalization
        .dkgMiningWindowEnd = 48, // give it a larger mining window to make sure it is mined
        .dkgBadVotesThreshold = 300,

        .signingActiveQuorumCount = 4, // four days worth of LLMQs

        .keepOldConnections = 5,
        .recoveryMembers = 100,
};

// this one is for testing only
static Consensus::LLMQParams llmq_test_v17 = {
        .type = Consensus::LLMQ_TEST_V17,
        .name = "llmq_test_v17",
        .size = 3,
        .minSize = 2,
        .threshold = 2,

        .dkgInterval = 24, // one DKG per hour
        .dkgPhaseBlocks = 2,
        .dkgMiningWindowStart = 10, // dkgPhaseBlocks * 5 = after finalization
        .dkgMiningWindowEnd = 18,
        .dkgBadVotesThreshold = 2,

        .signingActiveQuorumCount = 2, // just a few ones to allow easier testing

        .keepOldConnections = 3,
        .recoveryMembers = 3,
};

// Used for Platform
static Consensus::LLMQParams llmq100_67 = {
        .type = Consensus::LLMQ_100_67,
        .name = "llmq_100_67",
        .size = 100,
        .minSize = 80,
        .threshold = 67,

        .dkgInterval = 24, // one DKG per hour
        .dkgPhaseBlocks = 2,
        .dkgMiningWindowStart = 10, // dkgPhaseBlocks * 5 = after finalization
        .dkgMiningWindowEnd = 18,
        .dkgBadVotesThreshold = 80,

        .signingActiveQuorumCount = 24, // a full day worth of LLMQs

        .keepOldConnections = 25,
        .recoveryMembers = 50,
};

/**
 * Main network
 */
/**
 * What makes a good checkpoint block?
 * + Is surrounded by blocks with reasonable timestamps
 *   (no blocks before with a timestamp after, none after with
 *    timestamp before)
 * + Contains no strange transactions
 */


class CMainParams : public CChainParams {
public:
    CMainParams() {
        strNetworkID = "main";
        consensus.nSubsidyHalvingInterval = 210240; // Note: actual number of blocks per calendar year with DGW v3 is ~200700 (for example 449750 - 249050)
        consensus.nSmartnodePaymentsStartBlock = 4200; //
        consensus.nSmartnodePaymentsIncreaseBlock = 158000; // actual historical value
        consensus.nSmartnodePaymentsIncreasePeriod = 576*30; // 17280 - actual historical value
        consensus.nInstantSendConfirmationsRequired = 6;
        consensus.nInstantSendKeepLock = 24;
        consensus.nBudgetPaymentsStartBlock = INT_MAX; // actual historical value
        consensus.nBudgetPaymentsCycleBlocks = 16616; // ~(60*24*30)/2.6, actual number of blocks per month is 200700 / 12 = 16725
        consensus.nBudgetPaymentsWindowBlocks = 100;
        consensus.nSuperblockStartBlock = INT_MAX; // The block at which 12.1 goes live (end of final 12.0 budget cycle)
        consensus.nSuperblockStartHash = uint256S("0000000000020cb27c7ef164d21003d5d20cdca2f54dd9a9ca6d45f4d47f8aa3");
        consensus.nSuperblockCycle = 16616; // ~(60*24*30)/2.6, actual number of blocks per month is 200700 / 12 = 16725
        consensus.nGovernanceMinQuorum = 10;
        consensus.nGovernanceFilterElements = 20000;
        consensus.nSmartnodeMinimumConfirmations = 15;
        consensus.BIPCSVEnabled = true;
        consensus.BIP147Enabled = true;
        consensus.BIP34Enabled = true;
        consensus.BIP65Enabled = true; // 00000000000076d8fcea02ec0963de4abfd01e771fec0863f960c2c64fe6f357
        consensus.BIP66Enabled = true; // 00000000000b1fa2dfa312863570e13fae9ca7b5566cb27e55422620b469aefa
        consensus.DIP0001Enabled = true;
        consensus.DIP0003Enabled = true;
        consensus.DIP0008Enabled = true;
        // consensus.DIP0003EnforcementHeight = 1047200;
        consensus.powLimit = uint256S("00ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"); // ~uint256(0) >> 20
        consensus.nPowTargetTimespan = 24 * 60 * 60; // Yerbas: 1 day
        consensus.nPowTargetSpacing = 2 * 60; // Yerbas: 2 minutes
        consensus.fPowAllowMinDifficultyBlocks = false;
        consensus.fPowNoRetargeting = false;
        consensus.nPowDGWHeight = 60;
        consensus.DGWBlocksAvg = 60;
        consensus.nRuleChangeActivationThreshold = 1916; // 95% of 2016
        consensus.nMinerConfirmationWindow = 2016; // nPowTargetTimespan / nPowTargetSpacing
        consensus.smartnodePaymentFixedBlock = 6800;
        consensus.nFutureForkBlock = 9999999;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].bit = 28;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].nStartTime = 1199145601; // January 1, 2008
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].nTimeout = 1230767999; // December 31, 2008

        consensus.vDeployments[Consensus::DEPLOYMENT_V17].bit = 0;
        consensus.vDeployments[Consensus::DEPLOYMENT_V17].nStartTime = 9999999999; // 1643670001; // Feb 01, 2022 00:00:01hrs
        consensus.vDeployments[Consensus::DEPLOYMENT_V17].nTimeout = 9999999999; // 1675206001; // Feb 01, 2023 00:00:01hrs
        consensus.vDeployments[Consensus::DEPLOYMENT_V17].nWindowSize = 4032;
        consensus.vDeployments[Consensus::DEPLOYMENT_V17].nThresholdStart = 3226; // 80% of 4032
        consensus.vDeployments[Consensus::DEPLOYMENT_V17].nThresholdMin = 2420; // 60% of 4032
        consensus.vDeployments[Consensus::DEPLOYMENT_V17].nFalloffCoeff = 5; // this corresponds to 10 periods

        // The best chain should have at least this much work.
        consensus.nMinimumChainWork = uint256S("0x0000000000000000000000000000000000000000000000000000021b23df662d"); // 0

        // By default assume that the signatures in ancestors of this block are valid.
        consensus.defaultAssumeValid = uint256S("0x25c1c019d70e6990d3ed680fa9703cb84d620008a6cb8f635bbcdcef913dfbae"); // 0

        /**
         * The message start string is designed to be unlikely to occur in normal data.
         * The characters are rarely used upper ASCII, not valid as UTF-8, and produce
         * a large 32-bit integer with any alignment.
         */
        pchMessageStart[0] = 0x79;//y
        pchMessageStart[1] = 0x65;//e
        pchMessageStart[2] = 0x72;//r
        pchMessageStart[3] = 0x62;//b
        nDefaultPort = 15420;
        nPruneAfterHeight = 100000;
   //   FindMainNetGenesisBlock(1652138420, 0x20001fff, "main");
        genesis = CreateGenesisBlock(1652138420, 3397, 0x20001fff, 4, 5000 * COIN);
        consensus.hashGenesisBlock = genesis.GetHash();
        assert(consensus.hashGenesisBlock == uint256S("0xeff0bbe5c1bbe1ef8da54822a18f528d6dc58232990bdb86e0a77ab2814ed12c"));
        assert(genesis.hashMerkleRoot == uint256S("0xbfe15871764bf35d6391308fc2dab8846f177ba563d256b1764271987ec99bc0"));

        vSeeds.emplace_back("weednode00.yerbas.org");
        vSeeds.emplace_back("weednode01.yerbas.org");
        vSeeds.emplace_back("weednode02.yerbas.org");
        vSeeds.emplace_back("weednode03.yerbas.org");
        vSeeds.emplace_back("weednode420.yerbas.org");
        vSeeds.emplace_back("weednode05.yerbas.org");
        vSeeds.emplace_back("149.28.180.9");
        vSeeds.emplace_back("144.202.98.65");
        vSeeds.emplace_back("45.32.140.6");
        vSeeds.emplace_back("108.61.180.20");



        // Yerbas addresses start with 'y'
        base58Prefixes[PUBKEY_ADDRESS] = std::vector<unsigned char>(1,140);
        // Yerbas script addresses start with '8' or '9'
        base58Prefixes[SCRIPT_ADDRESS] = std::vector<unsigned char>(1,19);
        // Yerbas private keys start with '7' or 'X'
        base58Prefixes[SECRET_KEY] =     std::vector<unsigned char>(1,128);
        // Yerbas BIP32 pubkeys start with 'xpub' (Bitcoin defaults)
        base58Prefixes[EXT_PUBLIC_KEY] = {0x04, 0x88, 0xB2, 0x1E};
        // Yerbas BIP32 prvkeys start with 'xprv' (Bitcoin defaults)
        base58Prefixes[EXT_SECRET_KEY] = {0x04, 0x88, 0xAD, 0xE4};
        // Yerbas BIP44 coin type is '5'
        std::string strExtCoinType = gArgs.GetArg("-extcoinindex", "");
        nExtCoinType = strExtCoinType.empty() ? 200 : std::stoi(strExtCoinType);
//        if(gArgs.GetChainName() == CBaseChainParams::MAIN) {
//        	std::cout << "mainnet is disable" << endl;
//        	exit(0);
//        }
        std::vector<FounderRewardStructure> rewardStructures = {  {INT_MAX, 5} };// 5% founder/dev fee forever
        consensus.nFounderPayment = FounderPayment(rewardStructures, 420);
        consensus.nCollaterals = SmartnodeCollaterals(
          { {69420, 10000 * COIN},
            {100420, 16000 * COIN},
            {200420, 22000 * COIN}, 
            {302420, 28000 * COIN},
            {420420, 34000 * COIN},
            {INT_MAX, 42000 * COIN}
          },
          { {4200, 0}, {INT_MAX, 20} }
        );
        //FutureRewardShare defaultShare(0.8,0.2,0.0);
        consensus.nFutureRewardShare = Consensus::FutureRewardShare(0.8,0.2,0.0);

        vFixedSeeds = std::vector<SeedSpec6>(pnSeed6_main, pnSeed6_main + ARRAYLEN(pnSeed6_main));

        // long living quorum params
        consensus.llmqs[Consensus::LLMQ_50_60] = llmq3_60;
        consensus.llmqs[Consensus::LLMQ_400_60] = llmq20_60;
        consensus.llmqs[Consensus::LLMQ_400_85] = llmq20_85;
        consensus.llmqs[Consensus::LLMQ_100_67] = llmq100_67;
        consensus.llmqTypeChainLocks = Consensus::LLMQ_400_60;
        consensus.llmqTypeInstantSend = Consensus::LLMQ_50_60;
        consensus.llmqTypePlatform = Consensus::LLMQ_100_67;

        fDefaultConsistencyChecks = false;
        fRequireStandard = true;
        fRequireRoutableExternalIP = true;
        fMineBlocksOnDemand = false;
        fAllowMultipleAddressesFromGroup = false;
        fAllowMultiplePorts = false;
        miningRequiresPeers = true;
        nLLMQConnectionRetryTimeout = 60;

        nPoolMinParticipants = 3;
        nPoolNewMinParticipants = 3;
        nPoolMaxParticipants = 5;
        nPoolNewMaxParticipants = 20;
        nFulfilledRequestExpireTime = 60*60; // fulfilled requests expire in 1 hour

        vSporkAddresses = {"yWBtCoQuxeUx91YeLF6cii9XjHdCjGH3mh"};
        nMinSporkKeys = 1;
        fBIP9CheckSmartnodesUpgraded = true;

        checkpointData = {
          {  {0, uint256S("0xeff0bbe5c1bbe1ef8da54822a18f528d6dc58232990bdb86e0a77ab2814ed12c")}, 
             {1420, uint256S("0x9cf529c09eaf90f1b1b96c681c203aa80e1840b1709c928ab6e840b562d54c34")},
             {8837, uint256S("0x25c1c019d70e6990d3ed680fa9703cb84d620008a6cb8f635bbcdcef913dfbae")},
          }
	};

        chainTxData = ChainTxData{
          1653342048,   // * UNIX timestamp of last known number of transactions (Block 0)
              24916,   // * total number of transactions between genesis and that timestamp
                        //   (the tx=... number in the SetBestChain debug.log lines)
                 0.01    // * estimated number of transactions per second after that timestamp
        };
    }
};

/**
 * Testnet (v4)
 */
class CTestNetParams : public CChainParams {
public:
    CTestNetParams() {
        strNetworkID = "test";
        consensus.nSubsidyHalvingInterval = 210240;
        consensus.nSmartnodePaymentsStartBlock = 1000; // not true, but it's ok as long as it's less then nSmartnodePaymentsIncreaseBlock
        consensus.nSmartnodePaymentsIncreaseBlock = 4030;
        consensus.nSmartnodePaymentsIncreasePeriod = 10;
        consensus.nInstantSendConfirmationsRequired = 2;
        consensus.nInstantSendKeepLock = 6;
        consensus.nBudgetPaymentsStartBlock = INT_MAX;
        consensus.nBudgetPaymentsCycleBlocks = 50;
        consensus.nBudgetPaymentsWindowBlocks = 10;
        consensus.nSuperblockStartBlock = INT_MAX; // NOTE: Should satisfy nSuperblockStartBlock > nBudgetPeymentsStartBlock
        consensus.nSuperblockStartHash = uint256(); // do not check this on testnet
        consensus.nSuperblockCycle = 24; // Superblocks can be issued hourly on testnet
        consensus.nGovernanceMinQuorum = 1;
        consensus.nGovernanceFilterElements = 500;
        consensus.nSmartnodeMinimumConfirmations = 1;
        consensus.BIP34Enabled = true;
        consensus.BIP65Enabled = true; // 0000039cf01242c7f921dcb4806a5994bc003b48c1973ae0c89b67809c2bb2ab
        consensus.BIP66Enabled = true; // 0000002acdd29a14583540cb72e1c5cc83783560e38fa7081495d474fe1671f7
        consensus.DIP0001Enabled = true;
        consensus.DIP0003Enabled = true;
        consensus.BIPCSVEnabled = true;
        consensus.BIP147Enabled = true;
        consensus.DIP0008Enabled = true;
        // consensus.DIP0003EnforcementHeight = 7300;
        consensus.powLimit = uint256S("00ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"); // ~uint256(0) >> 20
        consensus.nPowTargetTimespan = 24 * 60 * 60; // Yerbas: 1 day
        consensus.nPowTargetSpacing = 60; // Yerbas: 1 minutes
        consensus.fPowAllowMinDifficultyBlocks = true;
        consensus.fPowNoRetargeting = false;
        consensus.nPowDGWHeight = 60;
        consensus.DGWBlocksAvg = 60;
        consensus.smartnodePaymentFixedBlock = 1;
        consensus.nRuleChangeActivationThreshold = 1512; // 75% for testchains
        consensus.nMinerConfirmationWindow = 2016; // nPowTargetTimespan / nPowTargetSpacing
        consensus.nFutureForkBlock = 1000;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].bit = 28;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].nStartTime = 1199145601; // January 1, 2008
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].nTimeout = 1230767999; // December 31, 2008

        consensus.vDeployments[Consensus::DEPLOYMENT_V17].bit = 0;
        consensus.vDeployments[Consensus::DEPLOYMENT_V17].nStartTime = 1643670001; // Feb 01, 2022 00:00:01hrs
        consensus.vDeployments[Consensus::DEPLOYMENT_V17].nTimeout = 1675206001; // Feb 01, 2023 00:00:01hrs
        consensus.vDeployments[Consensus::DEPLOYMENT_V17].nWindowSize = 100;
        consensus.vDeployments[Consensus::DEPLOYMENT_V17].nThresholdStart = 80;
        consensus.vDeployments[Consensus::DEPLOYMENT_V17].nThresholdMin = 60;
        consensus.vDeployments[Consensus::DEPLOYMENT_V17].nFalloffCoeff = 5; // this corresponds to 10 periods

        // The best chain should have at least this much work.
        consensus.nMinimumChainWork = uint256S("0x0"); // 0

        // By default assume that the signatures in ancestors of this block are valid.
        consensus.defaultAssumeValid = uint256S("0x0"); // 0

        pchMessageStart[0] = 0x7a;//t
        pchMessageStart[0] = 0x79;//y
        pchMessageStart[1] = 0x65;//e
        pchMessageStart[2] = 0x72;//r
        nDefaultPort = 20421;
        nPruneAfterHeight = 1000;
  //      FindMainNetGenesisBlock(1651158966, 0x20001fff, "test");
        genesis = CreateGenesisBlock(1651158966, 5025, 0x20001fff, 4, 5000 * COIN);
        consensus.hashGenesisBlock = genesis.GetHash();
        assert(consensus.hashGenesisBlock == uint256S("0xdfcc020dd96156eb9246cb7a3239169cbf45f0896cbc02a646905f5c8217b6bd"));
        assert(genesis.hashMerkleRoot == uint256S("0xbfe15871764bf35d6391308fc2dab8846f177ba563d256b1764271987ec99bc0"));

        vFixedSeeds.clear();
        vFixedSeeds = std::vector<SeedSpec6>(pnSeed6_test, pnSeed6_test + ARRAYLEN(pnSeed6_test));

        vSeeds.clear();
        // nodes with support for servicebits filtering should be at the top

        vSeeds.emplace_back("weednode00.yerbas.org");
        vSeeds.emplace_back("weednode01.yerbas.org");
        vSeeds.emplace_back("weednode02.yerbas.org");
        vSeeds.emplace_back("weednode03.yerbas.org");
        vSeeds.emplace_back("weednode420.yerbas.org");
        vSeeds.emplace_back("weednode05.yerbas.org");

        // Testnet Yerbas addresses start with 'r'
        base58Prefixes[PUBKEY_ADDRESS] = std::vector<unsigned char>(1,123);
        // Testnet Yerbas script addresses start with '8' or '9'
        base58Prefixes[SCRIPT_ADDRESS] = std::vector<unsigned char>(1,19);
        // Testnet private keys start with '9' or 'c' (Bitcoin defaults)
        base58Prefixes[SECRET_KEY] =     std::vector<unsigned char>(1,239);
        // Testnet Yerbas BIP32 pubkeys start with 'tpub' (Bitcoin defaults)
        base58Prefixes[EXT_PUBLIC_KEY] = {0x04, 0x35, 0x87, 0xCF};
        // Testnet Yerbas BIP32 prvkeys start with 'tprv' (Bitcoin defaults)
        base58Prefixes[EXT_SECRET_KEY] = {0x04, 0x35, 0x83, 0x94};

        // Testnet Yerbas BIP44 coin type is '1' (All coin's testnet default)
        std::string strExtCoinType = gArgs.GetArg("-extcoinindex", "");
        nExtCoinType = strExtCoinType.empty() ? 10227 : std::stoi(strExtCoinType);


        // long living quorum params
        consensus.llmqs[Consensus::LLMQ_50_60] = llmq3_60;
        consensus.llmqs[Consensus::LLMQ_400_60] = llmq20_60;
        consensus.llmqs[Consensus::LLMQ_400_85] = llmq20_85;
        consensus.llmqs[Consensus::LLMQ_100_67] = llmq100_67;
        consensus.llmqTypeChainLocks = Consensus::LLMQ_400_60;
        consensus.llmqTypeInstantSend = Consensus::LLMQ_50_60;
        consensus.llmqTypePlatform = Consensus::LLMQ_100_67;

        consensus.nCollaterals = SmartnodeCollaterals(
          {  {30000, 2000 * COIN}, {60000, 4000 * COIN}, {INT_MAX, 6000 * COIN}  },
          {  {INT_MAX, 20}  });

        consensus.nFutureRewardShare = Consensus::FutureRewardShare(0.8,0.2,0.0);

        std::vector<FounderRewardStructure> rewardStructures = {  {INT_MAX, 5}  };// 5% founder/dev fee forever
        consensus.nFounderPayment = FounderPayment(rewardStructures, 200, "rbKpULX5CgTcwJ7KbzY3BTwzEqwpFYHqXd");

        fDefaultConsistencyChecks = false;
        fRequireStandard = false;
        fRequireRoutableExternalIP = true;
        fMineBlocksOnDemand = false;
        fAllowMultipleAddressesFromGroup = false;
        fAllowMultiplePorts = true;
        nLLMQConnectionRetryTimeout = 60;
        miningRequiresPeers = true;

        nPoolMinParticipants = 3;
        nPoolNewMinParticipants = 2;
        nPoolMaxParticipants = 5;
        nPoolNewMaxParticipants = 20;
        nFulfilledRequestExpireTime = 5*60; // fulfilled requests expire in 5 minutes

        vSporkAddresses = {"rbKpULX5CgTcwJ7KbzY3BTwzEqwpFYHqXd"};
        nMinSporkKeys = 1;
        fBIP9CheckSmartnodesUpgraded = true;

        checkpointData = {
            {

            }
        };

        chainTxData = ChainTxData{
            1645942755, // * UNIX timestamp of last known number of transactions (Block 213054)
            0,    // * total number of transactions between genesis and that timestamp
                        //   (the tx=... number in the SetBestChain debug.log lines)
            0.01        // * estimated number of transactions per second after that timestamp
        };

    }
};

/**
 * Devnet
 */
class CDevNetParams : public CChainParams {
public:
    CDevNetParams() {
        strNetworkID = "devnet";
        consensus.nSubsidyHalvingInterval = 210240;
        consensus.nSmartnodePaymentsStartBlock = 4010; // not true, but it's ok as long as it's less then nSmartnodePaymentsIncreaseBlock
        consensus.nSmartnodePaymentsIncreaseBlock = 4030;
        consensus.nSmartnodePaymentsIncreasePeriod = 10;
        consensus.nInstantSendConfirmationsRequired = 2;
        consensus.nInstantSendKeepLock = 6;
        consensus.nBudgetPaymentsStartBlock = 4100;
        consensus.nBudgetPaymentsCycleBlocks = 50;
        consensus.nBudgetPaymentsWindowBlocks = 10;
        consensus.nSuperblockStartBlock = 4200; // NOTE: Should satisfy nSuperblockStartBlock > nBudgetPeymentsStartBlock
        consensus.nSuperblockStartHash = uint256(); // do not check this on devnet
        consensus.nSuperblockCycle = 24; // Superblocks can be issued hourly on devnet
        consensus.nGovernanceMinQuorum = 1;
        consensus.nGovernanceFilterElements = 500;
        consensus.nSmartnodeMinimumConfirmations = 1;
        consensus.BIP147Enabled = true;
        consensus.BIPCSVEnabled = true;
        consensus.BIP34Enabled = true; // BIP34 activated immediately on devnet
        consensus.BIP65Enabled = true; // BIP65 activated immediately on devnet
        consensus.BIP66Enabled = true; // BIP66 activated immediately on devnet
        consensus.DIP0001Enabled = true; // DIP0001 activated immediately on devnet
        consensus.DIP0003Enabled = true; // DIP0003 activated immediately on devnet
        consensus.DIP0008Enabled = true;// DIP0008 activated immediately on devnet
       // consensus.DIP0003EnforcementHeight = 2; // DIP0003 activated immediately on devnet
        consensus.powLimit = uint256S("7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"); // ~uint256(0) >> 1
        consensus.nPowTargetTimespan = 24 * 60 * 60; // Yerbas: 1 day
        consensus.nPowTargetSpacing = 2.5 * 60; // Yerbas: 2.5 minutes
        consensus.fPowAllowMinDifficultyBlocks = true;
        consensus.fPowNoRetargeting = false;
        consensus.nPowDGWHeight = 60;
        consensus.DGWBlocksAvg = 60;
        consensus.nRuleChangeActivationThreshold = 1512; // 75% for testchains
        consensus.nMinerConfirmationWindow = 2016; // nPowTargetTimespan / nPowTargetSpacing
        consensus.nFutureForkBlock = 1;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].bit = 28;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].nStartTime = 1199145601; // January 1, 2008
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].nTimeout = 1230767999; // December 31, 2008

        consensus.vDeployments[Consensus::DEPLOYMENT_V17].bit = 0;
        consensus.vDeployments[Consensus::DEPLOYMENT_V17].nStartTime = 0; // Feb 01, 2022 00:00:01hrs
        consensus.vDeployments[Consensus::DEPLOYMENT_V17].nTimeout = 9999999999ULL; // Feb 01, 2023 00:00:01hrs
        consensus.vDeployments[Consensus::DEPLOYMENT_V17].nWindowSize = 100;
        consensus.vDeployments[Consensus::DEPLOYMENT_V17].nThresholdStart = 80;
        consensus.vDeployments[Consensus::DEPLOYMENT_V17].nThresholdMin = 60;
        consensus.vDeployments[Consensus::DEPLOYMENT_V17].nFalloffCoeff = 5; // this corresponds to 10 periods

        // The best chain should have at least this much work.
        consensus.nMinimumChainWork = uint256S("0x000000000000000000000000000000000000000000000000000000000000000");

        // By default assume that the signatures in ancestors of this block are valid.
        consensus.defaultAssumeValid = uint256S("0x000000000000000000000000000000000000000000000000000000000000000");

        pchMessageStart[0] = 0xe2;
        pchMessageStart[1] = 0xca;
        pchMessageStart[2] = 0xff;
        pchMessageStart[3] = 0xce;
        nDefaultPort = 19799;
        nPruneAfterHeight = 1000;

        genesis = CreateGenesisBlock(1417713337, 1096447, 0x207fffff, 1, 50 * COIN);
        consensus.hashGenesisBlock = genesis.GetHash();
        assert(consensus.hashGenesisBlock == uint256S("0x000008ca1832a4baf228eb1553c03d3a2c8e02399550dd6ea8d65cec3ef23d2e"));
        assert(genesis.hashMerkleRoot == uint256S("0xe0028eb9648db56b1ac77cf090b99048a8007e2bb64b68f092c03c7f56a662c7"));

        devnetGenesis = FindDevNetGenesisBlock(genesis, 50 * COIN);
        consensus.hashDevnetGenesisBlock = devnetGenesis.GetHash();
        consensus.nFutureRewardShare = Consensus::FutureRewardShare(0.8,0.2,0.0);

        std::vector<FounderRewardStructure> rewardStructures = {  {INT_MAX, 5} };// 5% founder/dev fee forever

        consensus.nFounderPayment = FounderPayment(rewardStructures, 200);

        vFixedSeeds.clear();
        vSeeds.clear();
        //vSeeds.push_back(CDNSSeedData("yerbasevo.org",  "devnet-seed.yerbasevo.org"));

        // Testnet Yerbas addresses start with 'y'
        base58Prefixes[PUBKEY_ADDRESS] = std::vector<unsigned char>(1,140);
        // Testnet Yerbas script addresses start with '8' or '9'
        base58Prefixes[SCRIPT_ADDRESS] = std::vector<unsigned char>(1,19);
        // Testnet private keys start with '9' or 'c' (Bitcoin defaults)
        base58Prefixes[SECRET_KEY] =     std::vector<unsigned char>(1,239);
        // Testnet Yerbas BIP32 pubkeys start with 'tpub' (Bitcoin defaults)
        base58Prefixes[EXT_PUBLIC_KEY] = {0x04, 0x35, 0x87, 0xCF};
        // Testnet Yerbas BIP32 prvkeys start with 'tprv' (Bitcoin defaults)
        base58Prefixes[EXT_SECRET_KEY] = {0x04, 0x35, 0x83, 0x94};

        // Testnet Yerbas BIP44 coin type is '1' (All coin's testnet default)
        nExtCoinType = 1;

        // long living quorum params
        consensus.llmqs[Consensus::LLMQ_50_60] = llmq50_60;
        consensus.llmqs[Consensus::LLMQ_400_60] = llmq400_60;
        consensus.llmqs[Consensus::LLMQ_400_85] = llmq400_85;
        consensus.llmqs[Consensus::LLMQ_100_67] = llmq100_67;
        consensus.llmqTypeChainLocks = Consensus::LLMQ_50_60;
        consensus.llmqTypeInstantSend = Consensus::LLMQ_50_60;
        consensus.llmqTypePlatform = Consensus::LLMQ_100_67;

        fDefaultConsistencyChecks = false;
        fRequireStandard = false;
        fRequireRoutableExternalIP = true;
        fMineBlocksOnDemand = false;
        fAllowMultipleAddressesFromGroup = true;
        fAllowMultiplePorts = true;
        nLLMQConnectionRetryTimeout = 60;

        nPoolMinParticipants = 3;
        nPoolNewMinParticipants = 2;
        nPoolMaxParticipants = 5;
        nPoolNewMaxParticipants = 20;
        nFulfilledRequestExpireTime = 5*60; // fulfilled requests expire in 5 minutes

        vSporkAddresses = {"yjPtiKh2uwk3bDutTEA2q9mCtXyiZRWn55"};
        nMinSporkKeys = 1;
        // devnets are started with no blocks and no MN, so we can't check for upgraded MN (as there are none)
        fBIP9CheckSmartnodesUpgraded = false;

        checkpointData = (CCheckpointData) {
            {
                { 0, uint256S("0x000008ca1832a4baf228eb1553c03d3a2c8e02399550dd6ea8d65cec3ef23d2e")},
                { 1, devnetGenesis.GetHash() },
            }
        };

        chainTxData = ChainTxData{
            devnetGenesis.GetBlockTime(), // * UNIX timestamp of devnet genesis block
            2,                            // * we only have 2 coinbase transactions when a devnet is started up
            0.01                          // * estimated number of transactions per second
        };
    }
};

/**
 * Regression test
 */
class CRegTestParams : public CChainParams {
public:
    CRegTestParams() {
        strNetworkID = "regtest";
        consensus.nSubsidyHalvingInterval = 150;
        consensus.nSmartnodePaymentsStartBlock = 240;
        consensus.nSmartnodePaymentsIncreaseBlock = 350;
        consensus.nSmartnodePaymentsIncreasePeriod = 10;
        consensus.nInstantSendConfirmationsRequired = 2;
        consensus.nInstantSendKeepLock = 6;
        consensus.nBudgetPaymentsStartBlock = INT_MAX;
        consensus.nBudgetPaymentsCycleBlocks = 50;
        consensus.nBudgetPaymentsWindowBlocks = 10;
        consensus.nSuperblockStartBlock = INT_MAX;
        consensus.nSuperblockStartHash = uint256(); // do not check this on regtest
        consensus.nSuperblockCycle = 10;
        consensus.nGovernanceMinQuorum = 1;
        consensus.nGovernanceFilterElements = 100;
        consensus.nSmartnodeMinimumConfirmations = 1;
        consensus.BIPCSVEnabled = true;
        consensus.BIP147Enabled = true;
        consensus.BIP34Enabled = true; // BIP34 has not activated on regtest (far in the future so block v1 are not rejected in tests)
        consensus.BIP65Enabled = true; // BIP65 activated on regtest (Used in rpc activation tests)
        consensus.BIP66Enabled = true; // BIP66 activated on regtest (Used in rpc activation tests)
        consensus.DIP0001Enabled = true;
        consensus.DIP0003Enabled = true;
       // consensus.DIP0003EnforcementHeight = 500;
        consensus.powLimit = uint256S("7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"); // ~uint256(0) >> 1
        consensus.nPowTargetTimespan = 24 * 60 * 60; // Yerbas: 1 day
        consensus.nPowTargetSpacing = 2.5 * 60; // Yerbas: 2.5 minutes
        consensus.fPowAllowMinDifficultyBlocks = true;
        consensus.fPowNoRetargeting = true;
        consensus.nPowDGWHeight = 60;
        consensus.DGWBlocksAvg = 60;
        consensus.nRuleChangeActivationThreshold = 108; // 75% for testchains
        consensus.nMinerConfirmationWindow = 144; // Faster than normal for regtest (144 instead of 2016)
        consensus.nFutureForkBlock = 1;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].bit = 28;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].nStartTime = 0;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].nTimeout = 999999999999ULL;

        consensus.vDeployments[Consensus::DEPLOYMENT_V17].bit = 0;
        consensus.vDeployments[Consensus::DEPLOYMENT_V17].nStartTime = 0; // 1643670001; // Feb 01, 2022 00:00:01hrs
        consensus.vDeployments[Consensus::DEPLOYMENT_V17].nTimeout = 9999999999ULL; // 1675206001; // Feb 01, 2023 00:00:01hrs
        consensus.vDeployments[Consensus::DEPLOYMENT_V17].nWindowSize = 100;
        consensus.vDeployments[Consensus::DEPLOYMENT_V17].nThresholdStart = 80; // 80% of 4032
        consensus.vDeployments[Consensus::DEPLOYMENT_V17].nThresholdMin = 60; // 60% of 4032
        consensus.vDeployments[Consensus::DEPLOYMENT_V17].nFalloffCoeff = 5; // this corresponds to 10 periods

        // The best chain should have at least this much work.
        consensus.nMinimumChainWork = uint256S("0x00");

        // By default assume that the signatures in ancestors of this block are valid.
        consensus.defaultAssumeValid = uint256S("0x00");

        pchMessageStart[0] = 0xfc;
        pchMessageStart[1] = 0xc1;
        pchMessageStart[2] = 0xb7;
        pchMessageStart[3] = 0xdc;
        nDefaultPort = 19899;
        nPruneAfterHeight = 1000;

        genesis = CreateGenesisBlock(1614369600, 1130, 0x20001fff, 4, 5000 * COIN);
        consensus.hashGenesisBlock = genesis.GetHash();
        assert(consensus.hashGenesisBlock == uint256S("0xb79e5df07278b9567ada8fc655ffbfa9d3f586dc38da3dd93053686f41caeea0"));
        assert(genesis.hashMerkleRoot == uint256S("0x87a48bc22468acdd72ee540aab7c086a5bbcddc12b51c6ac925717a74c269453"));
        consensus.nFutureRewardShare = Consensus::FutureRewardShare(0.8,0.2,0.0);

        vFixedSeeds.clear(); //!< Regtest mode doesn't have any fixed seeds.
        vSeeds.clear();      //!< Regtest mode doesn't have any DNS seeds.

        fDefaultConsistencyChecks = true;
        fRequireStandard = false;
        fRequireRoutableExternalIP = false;
        fMineBlocksOnDemand = true;
        fAllowMultipleAddressesFromGroup = true;
        fAllowMultiplePorts = true;
        nLLMQConnectionRetryTimeout = 1; // must be lower then the LLMQ signing session timeout so that tests have control over failing behavior

        nFulfilledRequestExpireTime = 5*60; // fulfilled requests expire in 5 minutes
        nPoolMinParticipants = 2;
        nPoolNewMinParticipants = 2;
        nPoolMaxParticipants = 5;
        nPoolNewMaxParticipants = 20;

        // privKey: cP4EKFyJsHT39LDqgdcB43Y3YXjNyjb5Fuas1GQSeAtjnZWmZEQK
        vSporkAddresses = {"RWGvGpd3yJdnfh9ziyHNDEoHMJBvnZ23zK"};
        nMinSporkKeys = 1;
        // regtest usually has no smartnodes in most tests, so don't check for upgraged MNs
        fBIP9CheckSmartnodesUpgraded = false;
        std::vector<FounderRewardStructure> rewardStructures = {  {INT_MAX, 5} };// 5% founder/dev fee forever

        consensus.nFounderPayment = FounderPayment(rewardStructures, 200);

        checkpointData = {
            {
                {0, uint256S("0x000008ca1832a4baf228eb1553c03d3a2c8e02399550dd6ea8d65cec3ef23d2e")},
            }
        };

        chainTxData = ChainTxData{
            0,
            0,
            0
        };

        // Regtest Yerbas addresses start with 'y'
        base58Prefixes[PUBKEY_ADDRESS] = std::vector<unsigned char>(1,140);
        // Regtest Yerbas script addresses start with '8' or '9'
        base58Prefixes[SCRIPT_ADDRESS] = std::vector<unsigned char>(1,19);
        // Regtest private keys start with '9' or 'c' (Bitcoin defaults)
        base58Prefixes[SECRET_KEY] =     std::vector<unsigned char>(1,239);
        // Regtest Yerbas BIP32 pubkeys start with 'tpub' (Bitcoin defaults)
        base58Prefixes[EXT_PUBLIC_KEY] = {0x04, 0x35, 0x87, 0xCF};
        // Regtest Yerbas BIP32 prvkeys start with 'tprv' (Bitcoin defaults)
        base58Prefixes[EXT_SECRET_KEY] = {0x04, 0x35, 0x83, 0x94};

        // Regtest Yerbas BIP44 coin type is '1' (All coin's testnet default)
        nExtCoinType = 1;

        // long living quorum params
        consensus.llmqs[Consensus::LLMQ_5_60] = llmq3_60;
        consensus.llmqs[Consensus::LLMQ_50_60] = llmq50_60;
        consensus.llmqs[Consensus::LLMQ_TEST_V17] = llmq_test_v17;
        consensus.llmqTypeChainLocks = Consensus::LLMQ_5_60;
        consensus.llmqTypeInstantSend = Consensus::LLMQ_5_60;
        consensus.llmqTypePlatform = Consensus::LLMQ_5_60;
    }
};

static std::unique_ptr<CChainParams> globalChainParams;

const CChainParams &Params() {
    assert(globalChainParams);
    return *globalChainParams;
}

std::unique_ptr<CChainParams> CreateChainParams(const std::string& chain)
{
    if (chain == CBaseChainParams::MAIN)
        return std::unique_ptr<CChainParams>(new CMainParams());
    else if (chain == CBaseChainParams::TESTNET)
        return std::unique_ptr<CChainParams>(new CTestNetParams());
    else if (chain == CBaseChainParams::DEVNET) {
        return std::unique_ptr<CChainParams>(new CDevNetParams());
    } else if (chain == CBaseChainParams::REGTEST)
        return std::unique_ptr<CChainParams>(new CRegTestParams());
    throw std::runtime_error(strprintf("%s: Unknown chain %s.", __func__, chain));
}

void SelectParams(const std::string& network)
{
    SelectBaseParams(network);
    globalChainParams = CreateChainParams(network);
}

void UpdateVersionBitsParameters(Consensus::DeploymentPos d, int64_t nStartTime, int64_t nTimeout, int64_t nWindowSize, int64_t nThresholdStart, int64_t nThresholdMin, int64_t nFalloffCoeff)
{
    globalChainParams->UpdateVersionBitsParameters(d, nStartTime, nTimeout, nWindowSize, nThresholdStart, nThresholdMin, nFalloffCoeff);
}

//void UpdateDIP3Parameters(int nActivationHeight, int nEnforcementHeight)
//{
//    globalChainParams->UpdateDIP3Parameters(nActivationHeight, nEnforcementHeight);
//}

void UpdateBudgetParameters(int nSmartnodePaymentsStartBlock, int nBudgetPaymentsStartBlock, int nSuperblockStartBlock)
{
    globalChainParams->UpdateBudgetParameters(nSmartnodePaymentsStartBlock, nBudgetPaymentsStartBlock, nSuperblockStartBlock);
}

void UpdateDevnetSubsidyAndDiffParams(int nMinimumDifficultyBlocks, int nHighSubsidyBlocks, int nHighSubsidyFactor)
{
    globalChainParams->UpdateSubsidyAndDiffParams(nMinimumDifficultyBlocks, nHighSubsidyBlocks, nHighSubsidyFactor);
}

void UpdateDevnetLLMQChainLocks(Consensus::LLMQType llmqType)
{
    globalChainParams->UpdateLLMQChainLocks(llmqType);
}

void UpdateDevnetLLMQInstantSend(Consensus::LLMQType llmqType)
{
    globalChainParams->UpdateLLMQInstantSend(llmqType);
}

void UpdateLLMQParams(size_t totalMnCount, int height, bool lowLLMQParams) {
	globalChainParams->UpdateLLMQParams(totalMnCount, height, lowLLMQParams);
}
bool IsMiningPhase(Consensus::LLMQParams params, int nHeight)
{
    int phaseIndex = nHeight % params.dkgInterval;
    if (phaseIndex >= params.dkgMiningWindowStart && phaseIndex <= params.dkgMiningWindowEnd) {
        return true;
    }
    return false;
}

bool IsLLMQsMiningPhase(int nHeight) {
	for(auto& it : globalChainParams->GetConsensus().llmqs) {
		if(IsMiningPhase(it.second, nHeight)) {
			return true;
		}
	}
	return false;
}

void CChainParams::UpdateLLMQParams(size_t totalMnCount, int height, bool lowLLMQParams) {
	bool isNotLLMQsMiningPhase;
    if(lastCheckHeight < height &&
    		(lastCheckMnCount != totalMnCount || lastCheckedLowLLMQParams != lowLLMQParams) &&
			(isNotLLMQsMiningPhase = !IsLLMQsMiningPhase(height))) {
	    LogPrintf("---UpdateLLMQParams %d-%d-%ld-%ld-%d\n", lastCheckHeight, height, lastCheckMnCount, totalMnCount, isNotLLMQsMiningPhase);
                lastCheckMnCount = totalMnCount;
		lastCheckedLowLLMQParams = lowLLMQParams;
		lastCheckHeight = height;
        bool isTestNet = strcmp(Params().NetworkIDString().c_str(),"testnet") == 0;
		if(totalMnCount < 5) {
			consensus.llmqs[Consensus::LLMQ_50_60] = llmq3_60;
			if(isTestNet) {
				consensus.llmqs[Consensus::LLMQ_400_60] = llmq5_60;
				consensus.llmqs[Consensus::LLMQ_400_85] = llmq5_85;
			} else {
				consensus.llmqs[Consensus::LLMQ_400_60] = llmq20_60;
				consensus.llmqs[Consensus::LLMQ_400_85] = llmq20_85;
			}
		} else if((totalMnCount < 80 && isTestNet) ||  (totalMnCount < 100 && !isTestNet)) {
			consensus.llmqs[Consensus::LLMQ_50_60] = llmq10_60;
			consensus.llmqs[Consensus::LLMQ_400_60] = llmq20_60;
			consensus.llmqs[Consensus::LLMQ_400_85] = llmq20_85;
		}  else if(totalMnCount < 600) {
			consensus.llmqs[Consensus::LLMQ_50_60] = llmq50_60;
			consensus.llmqs[Consensus::LLMQ_400_60] = llmq40_60;
			consensus.llmqs[Consensus::LLMQ_400_85] = llmq40_85;
		} else {
			consensus.llmqs[Consensus::LLMQ_50_60] = llmq50_60;
			consensus.llmqs[Consensus::LLMQ_400_60] = llmq400_60;
			consensus.llmqs[Consensus::LLMQ_400_85] = llmq400_85;
		}
        if((height > 6759) && (height < 8320) || (height > 15909)){ //need add && (height < ????) when urn off low llmq
        consensus.llmqs[Consensus::LLMQ_50_60] = llmq200_2;
		} 
		
	}else{
        if(lastCheckHeight < height){
        lastCheckHeight = height;
        if(height == 6759 || height > 15909){
        consensus.llmqs[Consensus::LLMQ_50_60] = llmq200_2;
		}  
         if(height == 8319){
        consensus.llmqs[Consensus::LLMQ_50_60] = llmq10_60;
		}
        }
    }
}

