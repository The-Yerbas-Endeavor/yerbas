// Copyright (c) 2011-2026 The Bitcoin, Dash and Yerbas developers
// Distributed under the MIT software license, see the accompanying COPYING file.
#include "paymentserver.h"
#include "guiutil.h"
#include "base58.h"
#include "chainparams.h"
#include "ui_interface.h"
#include "util.h"
#include <QApplication>
#include <QDataStream>
#include <QFile>
#include <QFileOpenEvent>
#include <QLocalServer>
#include <QLocalSocket>
#include <QMessageBox>
#include <QUrlQuery>
#include <QDebug>

const int BITCOIN_IPC_CONNECT_TIMEOUT = 1000;
const QString BITCOIN_IPC_PREFIX("yerbas:");
static QList<QString> savedPaymentRequests;
static QString ipcServerName()
{
    QString name("YerbasQt");

    // Append a simple hash of the datadir
    // Note that GetDataDir(true) returns a different path
    // for -testnet versus main net
    QString ddir(GUIUtil::boostPathToQString(GetDataDir(true)));
    name.append(QString::number(qHash(ddir)));

    return name;
}

void PaymentServer::ipcParseCommandLine(int argc, char* argv[])
{
    for (int i = 1; i < argc; i++)
    {
        QString arg(argv[i]);
        if (arg.startsWith("-"))
            continue;

        // If the yerbas: URI contains a payment request, we are not able to detect the
        // network as that would require fetching and parsing the payment request.
        // That means clicking such an URI which contains a testnet payment request
        // will start a mainnet instance and throw a "wrong network" error.
        if (arg.startsWith(BITCOIN_IPC_PREFIX, Qt::CaseInsensitive)) // yerbas: URI
        {
            savedPaymentRequests.append(arg);

            SendCoinsRecipient r;
            if (GUIUtil::parseBitcoinURI(arg, &r) && !r.address.isEmpty())
            {
                CBitcoinAddress address(r.address.toStdString());
                auto tempChainParams = CreateChainParams(CBaseChainParams::MAIN);

                if (address.IsValid(*tempChainParams))
                {
                    SelectParams(CBaseChainParams::MAIN);
                }
                else {
                    tempChainParams = CreateChainParams(CBaseChainParams::TESTNET);
                    if (address.IsValid(*tempChainParams))
                        SelectParams(CBaseChainParams::TESTNET);
                }
            }
        }
        else if (QFile::exists(arg)) {
            savedPaymentRequests.append(arg); // Report unsupported files once the UI is ready.
        }
        else
        {
            // Printing to debug.log is about the best we can do here, the
            // GUI hasn't started yet so we can't pop up a message box.
            qWarning() << "PaymentServer::ipcSendCommandLine: Payment request file does not exist: " << arg;
        }
    }
}

bool PaymentServer::ipcSendCommandLine()
{
    bool fResult = false;
    for (const QString& r : savedPaymentRequests)
    {
        QLocalSocket* socket = new QLocalSocket();
        socket->connectToServer(ipcServerName(), QIODevice::WriteOnly);
        if (!socket->waitForConnected(BITCOIN_IPC_CONNECT_TIMEOUT))
        {
            delete socket;
            socket = nullptr;
            return false;
        }

        QByteArray block;
        QDataStream out(&block, QIODevice::WriteOnly);
        out.setVersion(QDataStream::Qt_4_0);
        out << r;
        out.device()->seek(0);

        socket->write(block);
        socket->flush();
        socket->waitForBytesWritten(BITCOIN_IPC_CONNECT_TIMEOUT);
        socket->disconnectFromServer();

        delete socket;
        socket = nullptr;
        fResult = true;
    }

    return fResult;
}

bool PaymentServer::eventFilter(QObject *object, QEvent *event)
{
    if (event->type() == QEvent::FileOpen) {
        QFileOpenEvent *fileEvent = static_cast<QFileOpenEvent*>(event);
        if (!fileEvent->file().isEmpty())
            handleURIOrFile(fileEvent->file());
        else if (!fileEvent->url().isEmpty())
            handleURIOrFile(fileEvent->url().toString());

        return true;
    }

    return QObject::eventFilter(object, event);
}

void PaymentServer::handleURIConnection()
{
    QLocalSocket *clientConnection = uriServer->nextPendingConnection();

    while (clientConnection->bytesAvailable() < (int)sizeof(quint32))
        clientConnection->waitForReadyRead();

    connect(clientConnection, SIGNAL(disconnected()),
            clientConnection, SLOT(deleteLater()));

    QDataStream in(clientConnection);
    in.setVersion(QDataStream::Qt_4_0);
    if (clientConnection->bytesAvailable() < (int)sizeof(quint16)) {
        return;
    }
    QString msg;
    in >> msg;

    handleURIOrFile(msg);
}

PaymentServer::PaymentServer(QObject* parent, bool startLocalServer)
    : QObject(parent), saveURIs(true), uriServer(nullptr)
{
    if (parent) parent->installEventFilter(this);
    if (startLocalServer) {
        const QString name = ipcServerName();
        QLocalServer::removeServer(name);
        uriServer = new QLocalServer(this);
        if (!uriServer->listen(name))
            QMessageBox::critical(nullptr, tr("URI handling"), tr("Cannot start yerbas: click-to-pay handler"));
        else
            connect(uriServer, &QLocalServer::newConnection, this, &PaymentServer::handleURIConnection);
    }
}
PaymentServer::~PaymentServer() = default;
void PaymentServer::setOptionsModel(OptionsModel*) {}
void PaymentServer::uiReady()
{
    saveURIs = false;
    const auto pending = savedPaymentRequests;
    savedPaymentRequests.clear();
    for (const auto& uri : pending) handleURIOrFile(uri);
}
void PaymentServer::handleURIOrFile(const QString& uri)
{
    if (saveURIs) { savedPaymentRequests.append(uri); return; }
    const QUrlQuery query{QUrl(uri)};
    if (!uri.startsWith(BITCOIN_IPC_PREFIX, Qt::CaseInsensitive) || query.hasQueryItem("r") || query.hasQueryItem("req-r")) {
        Q_EMIT message(tr("URI handling"), tr("Legacy payment-request files and remote payment requests are no longer supported. Use a Yerbas address or a yerbas: payment URI."), CClientUIInterface::ICON_WARNING);
        return;
    }
    SendCoinsRecipient recipient;
    if (!GUIUtil::parseBitcoinURI(uri, &recipient) || !CBitcoinAddress(recipient.address.toStdString()).IsValid()) {
        Q_EMIT message(tr("URI handling"), tr("Invalid Yerbas address or payment URI."), CClientUIInterface::ICON_WARNING);
        return;
    }
    Q_EMIT receivedPaymentRequest(recipient);
}
