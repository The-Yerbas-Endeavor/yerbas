// Copyright (c) 2026 The Yerbas Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include "assets/assetcontract.h"
#include "assets/assetcontractcache.h"
#include "assets/assetcontractdb.h"
#include "assets/assetcontractstate.h"
#include "streams.h"
#include "test/test_yerbas.h"
#include "version.h"

#include <boost/test/unit_test.hpp>

BOOST_FIXTURE_TEST_SUITE(assetcontract_tests, BasicTestingSetup)

BOOST_AUTO_TEST_CASE(contract_id_is_deterministic)
{
    const COutPoint outpoint(uint256S("01"), 7);

    const uint256 first = GetAssetContractId(outpoint);
    const uint256 second = GetAssetContractId(outpoint);
    const uint256 different = GetAssetContractId(COutPoint(uint256S("01"), 8));

    BOOST_CHECK(!first.IsNull());
    BOOST_CHECK_EQUAL(first.ToString(), second.ToString());
    BOOST_CHECK(first != different);
}

BOOST_AUTO_TEST_CASE(deploy_validation_rejects_invalid_and_accepts_bounded_data)
{
    CAssetContractDeploy deploy;
    std::string error;

    BOOST_CHECK(!deploy.IsValid(error));
    BOOST_CHECK(!error.empty());

    deploy.nTemplate = AssetContractTemplate::ESCROW;
    deploy.nTemplateVersion = 1;
    deploy.strAssetName = "YAC_TEST";
    deploy.ownerScript = CScript() << OP_TRUE;
    deploy.vParameters = {0x01, 0x02, 0x03};
    deploy.nExecutionLimit = 100;

    BOOST_CHECK(deploy.IsValid(error));
    BOOST_CHECK(error.empty());

    deploy.vParameters.resize(MAX_ASSET_CONTRACT_DEPLOY_PAYLOAD + 1);
    BOOST_CHECK(!deploy.IsValid(error));
}

BOOST_AUTO_TEST_CASE(call_validation_enforces_limits)
{
    CAssetContractCall call;
    std::string error;

    call.contractId = uint256S("02");
    call.nOperation = AssetContractOperation::CALL;
    call.nMethod = 1;
    call.nExecutionLimit = 25;
    call.nAttachedYerb = 0;

    BOOST_CHECK(call.IsValid(error));

    call.vArguments.resize(MAX_ASSET_CONTRACT_CALL_PAYLOAD + 1);
    BOOST_CHECK(!call.IsValid(error));
}

BOOST_AUTO_TEST_CASE(state_serialization_and_hash_are_deterministic)
{
    CAssetContractState original;
    original.contractId = uint256S("03");
    original.nStatus = AssetContractStatus::ACTIVE;
    original.mapState["buyer"] = {0x01, 0x02};
    original.mapState["seller"] = {0x03, 0x04};
    original.nLastHeight = 42;
    original.lastTxid = uint256S("04");

    std::string error;
    BOOST_CHECK(original.IsValid(error));

    CDataStream encoded(SER_DISK, CLIENT_VERSION);
    encoded << original;

    CAssetContractState decoded;
    encoded >> decoded;

    BOOST_CHECK_EQUAL(original.GetHash().ToString(), decoded.GetHash().ToString());
    BOOST_CHECK_EQUAL(decoded.contractId.ToString(), original.contractId.ToString());
    BOOST_CHECK_EQUAL(decoded.mapState.size(), original.mapState.size());
    BOOST_CHECK_EQUAL(decoded.nLastHeight, original.nLastHeight);
}

BOOST_AUTO_TEST_CASE(in_memory_database_round_trip)
{
    CAssetContractDB db(1 << 20, true, true);
    const uint256 contractId = uint256S("05");

    CAssetContractData data;
    data.deploy.nTemplate = AssetContractTemplate::ESCROW;
    data.deploy.nTemplateVersion = 1;
    data.deploy.strAssetName = "YAC_TEST";
    data.deploy.ownerScript = CScript() << OP_TRUE;
    data.deploy.nExecutionLimit = 100;
    data.deploymentOutpoint = COutPoint(uint256S("06"), 0);
    data.nStatus = AssetContractStatus::ACTIVE;
    data.nCreatedHeight = 10;
    data.nUpdatedHeight = 10;

    CAssetContractState state;
    state.contractId = contractId;
    state.nStatus = AssetContractStatus::ACTIVE;
    state.mapState["status"] = {0x01};
    state.nLastHeight = 10;
    state.lastTxid = uint256S("06");

    BOOST_CHECK(db.WriteContract(contractId, data));
    BOOST_CHECK(db.WriteState(contractId, state));
    BOOST_CHECK(db.HaveContract(contractId));
    BOOST_CHECK(db.HaveState(contractId));

    CAssetContractData readData;
    CAssetContractState readState;
    BOOST_CHECK(db.ReadContract(contractId, readData));
    BOOST_CHECK(db.ReadState(contractId, readState));
    BOOST_CHECK_EQUAL(readData.deploy.strAssetName, "YAC_TEST");
    BOOST_CHECK_EQUAL(readState.GetHash().ToString(), state.GetHash().ToString());
}

BOOST_AUTO_TEST_CASE(cache_flush_and_erase)
{
    CAssetContractDB db(1 << 20, true, true);
    CAssetContractCache cache(&db);
    const uint256 contractId = uint256S("07");

    CAssetContractData data;
    data.deploy.nTemplate = AssetContractTemplate::ESCROW;
    data.deploy.nTemplateVersion = 1;
    data.deploy.strAssetName = "YAC_CACHE";
    data.deploy.ownerScript = CScript() << OP_TRUE;
    data.deploy.nExecutionLimit = 50;
    data.deploymentOutpoint = COutPoint(uint256S("08"), 0);
    data.nStatus = AssetContractStatus::ACTIVE;

    CAssetContractState state;
    state.contractId = contractId;
    state.nStatus = AssetContractStatus::ACTIVE;
    state.mapState["value"] = {0x2a};

    cache.PutContract(contractId, data);
    cache.PutState(contractId, state);
    BOOST_CHECK(cache.HaveContract(contractId));
    BOOST_CHECK(cache.Flush());
    BOOST_CHECK(db.HaveContract(contractId));
    BOOST_CHECK(db.HaveState(contractId));

    cache.EraseContract(contractId);
    cache.EraseState(contractId);
    BOOST_CHECK(cache.Flush());
    BOOST_CHECK(!db.HaveContract(contractId));
    BOOST_CHECK(!db.HaveState(contractId));
}

BOOST_AUTO_TEST_SUITE_END()
