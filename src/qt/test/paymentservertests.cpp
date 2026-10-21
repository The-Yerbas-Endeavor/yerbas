// Copyright (c) 2026 The Yerbas developers
// Distributed under the MIT software license, see the accompanying COPYING file.
#include "paymentservertests.h"
#include "streams.h"
#include "base58.h"
#include "version.h"

void PaymentServerTests::paymentServerTests()
{
    PaymentServer server(nullptr, false);
    int received = 0, rejected = 0;
    SendCoinsRecipient last;
    connect(&server, &PaymentServer::receivedPaymentRequest, &server, [&](SendCoinsRecipient r) { ++received; last = r; });
    connect(&server, &PaymentServer::message, &server, [&](const QString&, const QString&, unsigned int) { ++rejected; });
    const QString uri = "yerbas:" + QString::fromStdString(CBitcoinAddress(CKeyID(uint160())).ToString()) + "?amount=1.25&label=Example";
    server.handleURIOrFile(uri);
    QCOMPARE(received, 0); // Queue until startup completes.
    server.uiReady();
    QCOMPARE(received, 1);
    QCOMPARE(last.amount, CAmount(125000000));
    QCOMPARE(last.label, QString("Example"));
    for (const auto& value : {uri + "&r=https://example.invalid/request", uri + "&req-r=https://example.invalid/request", QString("/tmp/legacy.paymentrequest"), QString("yerbas:invalid")})
        server.handleURIOrFile(value);
    QCOMPARE(received, 1);
    QCOMPARE(rejected, 4);

    // Retiring processing must not change the serialized recipient layout.
    SendCoinsRecipient old;
    old.legacyPaymentRequest = std::string("historical\0request", 18);
    old.authenticatedMerchant = "Historical merchant";
    CDataStream stream(SER_DISK, PROTOCOL_VERSION);
    stream << old;
    CDataStream historical(SER_DISK, PROTOCOL_VERSION);
    historical << int(1) << std::string() << std::string() << CAmount(0)
               << std::string() << old.legacyPaymentRequest << old.authenticatedMerchant.toStdString();
    QVERIFY(std::equal(stream.begin(), stream.end(), historical.begin(), historical.end()));
    SendCoinsRecipient restored;
    stream >> restored;
    QCOMPARE(restored.legacyPaymentRequest, old.legacyPaymentRequest);
    QCOMPARE(restored.authenticatedMerchant, old.authenticatedMerchant);

    SendAssetsRecipient asset;
    asset.assetName = "TEST_ASSET";
    asset.legacyPaymentRequest = old.legacyPaymentRequest;
    CDataStream assetStream(SER_DISK, PROTOCOL_VERSION), historicalAsset(SER_DISK, PROTOCOL_VERSION);
    assetStream << asset;
    historicalAsset << int(1) << asset.assetName.toStdString() << std::string() << std::string()
                    << CAmount(0) << std::string() << old.legacyPaymentRequest << std::string();
    QVERIFY(std::equal(assetStream.begin(), assetStream.end(), historicalAsset.begin(), historicalAsset.end()));
    SendAssetsRecipient restoredAsset;
    assetStream >> restoredAsset;
    QCOMPARE(restoredAsset.legacyPaymentRequest, old.legacyPaymentRequest);
    QCOMPARE(restoredAsset.assetName, asset.assetName);
}
