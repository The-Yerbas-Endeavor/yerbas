// Copyright (c) 2026 The Yerbas developers
// Distributed under the MIT software license, see the accompanying COPYING file.
#include "assetviewtests.h"
#include "assetmanagerpage.h"
#include "createassetdialog.h"
#include "assetsdialog.h"
#include "platformstyle.h"
#include "chainparams.h"
#include <memory>
#include <QLineEdit>
#include <QTableView>
#include <QSignalSpy>
#include "assetdetailsdialog.h"
#include "assetfilterproxy.h"
#include "assetrecord.h"
#include "assettablemodel.h"
#include <QLabel>
#include <QBuffer>
#include <QImage>
#include <QTcpServer>
#include <QTcpSocket>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QStandardItemModel>
#include <QTest>
#include <limits>

void AssetViewTests::contentUrls()
{
    const QString cid = "Qm" + QString(44, 'a');
    const QString gateway = "https://example.org/ipfs/%s";
    QCOMPARE(AssetDetailsDialog::contentUrl(cid, gateway).toString(), "https://example.org/ipfs/" + cid);
    for (const QString& invalid : {QString(), QString(64, 'a'), cid + "/../", "Qm" + QString(44, '0')})
        QVERIFY(AssetDetailsDialog::contentUrl(invalid, gateway).isEmpty());
    for (const QString& invalid : {"file:///%s", "httpx://example.org/%s", "https://user:password@example.org/%s",
                                  "https://example.org/", "https://example.org/%s/%s"})
        QVERIFY(AssetDetailsDialog::contentUrl(cid, invalid).isEmpty());
}

void AssetViewTests::filteringAndSorting()
{
    QStandardItemModel source;
    for (const QString& name : {"ROOT/Z", "OTHER/Z", "ROOT/A"}) {
        auto* item = new QStandardItem(name);
        item->setData(name, AssetTableModel::AssetNameRole);
        source.appendRow(item);
    }
    AssetFilterProxy proxy;
    proxy.setSourceModel(&source);
    proxy.setSortRole(AssetTableModel::AssetNameRole);
    proxy.sort(AssetTableModel::Name);
    QCOMPARE(proxy.index(0, 0).data().toString(), QString("OTHER/Z"));
    proxy.setAssetNamePrefix("root/");
    QCOMPARE(proxy.rowCount(), 2);
    proxy.setAssetNameContains("z");
    QCOMPARE(proxy.rowCount(), 1);
    QCOMPARE(proxy.index(0, 0).data().toString(), QString("ROOT/Z"));
    proxy.setAssetNameContains("");
    QCOMPARE(proxy.rowCount(), 2);
    source.clear();
    QCOMPARE(proxy.rowCount(), 0);
}

void AssetViewTests::quantities()
{
    QCOMPARE(AssetRecord("", 123456789, 8, false, "").formattedQuantity(), std::string("1.23456789"));
    QCOMPARE(AssetRecord("", 123456789, 2, false, "").formattedQuantity(), std::string("1.23"));
    QCOMPARE(AssetRecord("", -100000001, 8, false, "").formattedQuantity(), std::string("-1.00000001"));
    QCOMPARE(AssetRecord("", std::numeric_limits<int64_t>::min(), 8, false, "").formattedQuantity(), std::string("-92233720368.54775808"));
    QCOMPARE(AssetRecord("", 123456789, -1, false, "").formattedQuantity(), std::string("1"));
    QCOMPARE(AssetRecord("", 123456789, 99, false, "").formattedQuantity(), std::string("1.23456789"));
}

void AssetViewTests::detailsWithoutContent()
{
    AssetDetailsDialog dialog("<asset metadata>", "", "", QNetworkProxy(QNetworkProxy::NoProxy));
    QCOMPARE(dialog.findChild<QPlainTextEdit*>()->toPlainText(), QString("<asset metadata>"));
    int disabled = 0;
    for (auto* button : dialog.findChildren<QPushButton*>())
        if (!button->isEnabled()) ++disabled;
    QCOMPARE(disabled, 2); // No preview request and no full-size image.
}

void AssetViewTests::imagePreview_data()
{
    QTest::addColumn<bool>("redirect");
    QTest::newRow("png") << false;
    QTest::newRow("redirect-rejected") << true;
}

void AssetViewTests::imagePreview()
{
    QFETCH(bool, redirect);
    QTcpServer server;
    QVERIFY(server.listen(QHostAddress::LocalHost));
    int requests = 0;
    QImage image(2, 2, QImage::Format_RGB32);
    image.fill(Qt::green);
    QByteArray png;
    QBuffer buffer(&png);
    QVERIFY(buffer.open(QIODevice::WriteOnly));
    QVERIFY(image.save(&buffer, "PNG"));
    connect(&server, &QTcpServer::newConnection, &server, [&] {
        auto* socket = server.nextPendingConnection();
        connect(socket, &QTcpSocket::readyRead, socket, [&, socket] {
            socket->readAll();
            if (socket->property("answered").toBool()) return;
            socket->setProperty("answered", true);
            ++requests;
            if (redirect) {
                socket->write("HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1/forbidden\r\nContent-Length: 0\r\n\r\n");
            } else {
                socket->write("HTTP/1.1 200 OK\r\nContent-Type: image/png\r\nContent-Length: "
                    + QByteArray::number(png.size()) + "\r\n\r\n" + png);
            }
            socket->disconnectFromHost();
        });
    });
    AssetDetailsDialog dialog("Snapshot", "Qm" + QString(44, 'a'),
        QString("http://127.0.0.1:%1/ipfs/%s").arg(server.serverPort()), QNetworkProxy(QNetworkProxy::NoProxy));
    QTest::qWait(20);
    QCOMPARE(requests, 0);
    auto* load = dialog.findChild<QPushButton*>("loadPreview");
    auto* fullSize = dialog.findChild<QPushButton*>("fullSizeImage");
    load->click();
    QVERIFY(!load->isEnabled());
    QTRY_VERIFY(load->isEnabled());
    QCOMPARE(requests, 1);
    QCOMPARE(fullSize->isEnabled(), !redirect);
}

void AssetViewTests::assetManagerSelection()
{
    QStandardItemModel wallet;
    wallet.setColumnCount(2);
    for (const QString& name : {"ALPHA", "BETA!"}) {
        auto* item = new QStandardItem(name);
        item->setData(name, AssetTableModel::AssetNameRole);
        item->setData("1", AssetTableModel::FormattedAmountRole);
        item->setData(name.endsWith('!'), AssetTableModel::AdministratorRole);
        wallet.appendRow({item, new QStandardItem("1")});
    }
    AssetManagerPage page;
    page.setModel(&wallet);
    auto* table = page.findChild<QTableView*>("assetManagerTable");
    auto* search = page.findChild<QLineEdit*>("assetManagerSearch");
    auto* send = page.findChild<QPushButton*>("assetManagerSend");
    auto* details = page.findChild<QPushButton*>("assetManagerDetails");
    auto* selection = page.findChild<QLabel*>("assetManagerSelection");
    QVERIFY(!send->isEnabled());
    QVERIFY(!details->isEnabled());
    QSignalSpy sends(&page, &AssetManagerPage::sendRequested);
    table->selectRow(1);
    QVERIFY(send->isEnabled());
    QVERIFY(selection->text().contains("ownership token"));
    send->click();
    QCOMPARE(sends.size(), 1);
    QCOMPARE(qvariant_cast<QModelIndex>(sends.first().first()).data(AssetTableModel::AssetNameRole).toString(), QString("BETA!"));
    search->setText("alpha");
    QCOMPARE(table->model()->rowCount(), 1);
    QVERIFY(!send->isEnabled()); // Filtering must not send a previously selected asset.
    table->selectRow(0);
    QVERIFY(details->isEnabled());
    wallet.clear();
    QVERIFY(!send->isEnabled());
    QVERIFY(!details->isEnabled());
    QStandardItemModel otherWallet;
    page.setModel(&otherWallet);
    QCOMPARE(table->model()->rowCount(), 0);
    QVERIFY(!send->isEnabled());
}

void AssetViewTests::mainnetIssuanceLock()
{
    QCOMPARE(Params().NetworkIDString(), std::string(CBaseChainParams::MAIN));
    std::unique_ptr<const PlatformStyle> style(PlatformStyle::instantiate("other"));
    CreateAssetDialog dialog(style.get());
    auto* button = dialog.findChild<QPushButton*>("createAssetButton");
    auto* notice = dialog.findChild<QLabel*>("issuanceAvailabilityLabel");
    QVERIFY(button);
    QVERIFY(notice);
    QVERIFY(!button->isEnabled());
    QVERIFY(!notice->isHidden());
    QVERIFY(notice->text().contains("1195400"));
    auto* name = dialog.findChild<QLineEdit*>("nameText");
    QVERIFY(name);
    name->setText("LOCKTEST");
    QVERIFY(!button->isEnabled());
    AssetsDialog sendDialog(style.get());
    auto* send = sendDialog.findChild<QPushButton*>("sendButton");
    auto* sendNotice = sendDialog.findChild<QLabel*>("assetAvailabilityLabel");
    QVERIFY(send);
    QVERIFY(sendNotice);
    QVERIFY(!send->isEnabled());
    QVERIFY(!sendNotice->isHidden());
    QVERIFY(sendNotice->text().contains("1195400"));
}
