// Copyright (c) 2011-2026 The Bitcoin, Dash and Yerbas developers
// Distributed under the MIT software license, see the accompanying COPYING file.
#ifndef BITCOIN_QT_PAYMENTSERVER_H
#define BITCOIN_QT_PAYMENTSERVER_H
#include "walletmodel.h"
#include <QObject>
class OptionsModel;
class QLocalServer;
class PaymentServer : public QObject
{
    Q_OBJECT
public:
    static void ipcParseCommandLine(int argc, char* argv[]);
    static bool ipcSendCommandLine();
    PaymentServer(QObject* parent, bool startLocalServer = true);
    ~PaymentServer();
    void setOptionsModel(OptionsModel*);
Q_SIGNALS:
    void receivedPaymentRequest(SendCoinsRecipient);
    void message(const QString& title, const QString& message, unsigned int style);
public Q_SLOTS:
    void uiReady();
    void handleURIOrFile(const QString& uri);
private Q_SLOTS:
    void handleURIConnection();
protected:
    bool eventFilter(QObject* object, QEvent* event) override;
private:
    bool saveURIs;
    QLocalServer* uriServer;
};
#endif
