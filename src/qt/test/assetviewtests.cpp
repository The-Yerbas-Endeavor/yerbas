#include "walletrecovery.h"
#include <QTemporaryDir>
#include <QSignalSpy>
#include <QPersistentModelIndex>
// Copyright (c) 2026 The Yerbas developers
// Distributed under the MIT software license, see the accompanying COPYING file.
#include "assetviewtests.h"
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
    QCOMPARE(disabled, 3); // No preview request and no full-size image.
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

void AssetViewTests::incrementalBalances()
{
    AssetTableModel model;
    QSignalSpy resets(&model, &QAbstractItemModel::modelReset);
    QSignalSpy changes(&model, &QAbstractItemModel::dataChanged);
    AssetRecord a("AAA", 4 * COIN, 2, false, ""), b("BBB", COIN, 0, true, "");
    a.available = a.pending = a.restricted = a.locked = COIN;
    model.applySnapshot({a, b});
    QPersistentModelIndex selected(model.index(1, 0));
    model.applySnapshot({a, b});
    QCOMPARE(changes.count(), 0);
    a.quantity += COIN;
    a.restricted += COIN;
    model.applySnapshot({a, b});
    QCOMPARE(changes.count(), 1);
    QVERIFY(model.index(0, 0).data(AssetTableModel::BalanceStatusRole).toString().contains("Restricted: 2"));
    model.applySnapshot({b});
    QVERIFY(selected.isValid());
    QCOMPARE(selected.row(), 0);
    QCOMPARE(selected.data().toString(), QString("BBB"));
    model.applySnapshot({a, b});
    QCOMPARE(selected.row(), 1);
    QCOMPARE(resets.count(), 0);
    model.applySnapshot({});
    QVERIFY(!selected.isValid());
}

void AssetViewTests::imageExport()
{
    QTemporaryDir dir;
    QImage image(2, 3, QImage::Format_RGB32);
    image.fill(Qt::green);
    const QString path = dir.filePath("preview.png");
    QVERIFY(AssetDetailsDialog::saveImage(image, path));
    QCOMPARE(QImage(path), image);
    QVERIFY(!AssetDetailsDialog::saveImage(QImage(), path));
    QCOMPARE(QImage(path), image);
    QVERIFY(!AssetDetailsDialog::saveImage(image, dir.filePath("missing/image.png")));
}

void AssetViewTests::walletRecovery()
{
    QTemporaryDir dir;
    QFile original(dir.filePath("wallet.dat"));
    QVERIFY(original.open(QIODevice::WriteOnly));
    original.write("original wallet bytes");
    original.close();
    const QString first = WalletRecovery::copyBackup(original.fileName(), dir.path());
    const QString second = WalletRecovery::copyBackup(original.fileName(), dir.path());
    QVERIFY(!first.isEmpty());
    QVERIFY(first != second);
    QFile restored(dir.filePath(first));
    QVERIFY(restored.open(QIODevice::ReadOnly));
    QCOMPARE(restored.readAll(), QByteArray("original wallet bytes"));
    QVERIFY(original.open(QIODevice::ReadOnly));
    QCOMPARE(original.readAll(), QByteArray("original wallet bytes"));
    QVERIFY(WalletRecovery::copyBackup(dir.filePath("absent"), dir.path()).isEmpty());
    const QStringList args = WalletRecovery::restartArguments({"yerbas-qt", "-testnet", "-wallet=old.dat", "--wallet=other.dat", "-zapwallettxes=1", "-rescan=0", "-proxy=127.0.0.1:9050"}, first);
    QCOMPARE(args, QStringList({"-testnet", "-proxy=127.0.0.1:9050", "-wallet=" + first, "-rescan=1"}));
}
