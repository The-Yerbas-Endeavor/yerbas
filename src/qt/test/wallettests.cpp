#include "wallettests.h"

#include "qt/bitcoinamountfield.h"
#include "qt/callback.h"
#include "qt/clientmodel.h"
#include "qt/optionsmodel.h"
#include "qt/platformstyle.h"
#include "qt/qvalidatedlineedit.h"
#include "qt/sendcoinsdialog.h"
#include "qt/sendcoinsentry.h"
#include "qt/transactiontablemodel.h"
#include "qt/walletmodel.h"
#include "test/test_yerbas.h"
#include "validation.h"
#include "wallet/wallet.h"

#include <QAbstractButton>
#include <QAbstractSpinBox>
#include <QApplication>
#include <QCheckBox>
#include <QComboBox>
#include <QRadioButton>
#include <QTimer>
#include <QFile>
#include <QScrollArea>
#include <QPushButton>
#include <QVBoxLayout>

namespace
{
// Destroy this guard after the wallet and widgets, including on a failed Qt assertion.
struct WalletDatabaseGuard
{
    WalletDatabaseGuard() { bitdb.MakeMock(); }
    ~WalletDatabaseGuard()
    {
        bitdb.Flush(true);
        bitdb.Reset();
    }
};

//! Press "Yes" button in modal send confirmation dialog.
void ConfirmSend()
{
    QTimer::singleShot(0, makeCallback([](Callback* callback) {
        for (QWidget* widget : QApplication::topLevelWidgets()) {
            if (widget->inherits("SendConfirmationDialog")) {
                SendConfirmationDialog* dialog = qobject_cast<SendConfirmationDialog*>(widget);
                QAbstractButton* button = dialog->button(QMessageBox::Yes);
                button->setEnabled(true);
                button->click();
            }
        }
        delete callback;
    }), SLOT(call()));
}

//! Send coins to address and return txid.
uint256 SendCoins(CWallet& wallet, SendCoinsDialog& sendCoinsDialog, const CBitcoinAddress& address, CAmount amount)
{
    QVBoxLayout* entries = sendCoinsDialog.findChild<QVBoxLayout*>("entries");
    SendCoinsEntry* entry = qobject_cast<SendCoinsEntry*>(entries->itemAt(0)->widget());
    entry->findChild<QValidatedLineEdit*>("payTo")->setText(QString::fromStdString(address.ToString()));
    entry->findChild<BitcoinAmountField*>("payAmount")->setValue(amount);
    uint256 txid;
    boost::signals2::scoped_connection c(wallet.NotifyTransactionChanged.connect([&txid](CWallet*, const uint256& hash, ChangeType status) {
        if (status == CT_NEW) txid = hash;
    }));
    ConfirmSend();
    QMetaObject::invokeMethod(&sendCoinsDialog, "on_sendButton_clicked");
    return txid;
}

//! Find index of txid in transaction list.
QModelIndex FindTx(const QAbstractItemModel& model, const uint256& txid)
{
    QString hash = QString::fromStdString(txid.ToString());
    int rows = model.rowCount({});
    for (int row = 0; row < rows; ++row) {
        QModelIndex index = model.index(row, 0, {});
        if (model.data(index, TransactionTableModel::TxHashRole) == hash) {
            return index;
        }
    }
    return {};
}

//! Simple qt wallet tests.
//
// Test widgets can be debugged interactively calling show() on them and
// manually running the event loop, e.g.:
//
//     sendCoinsDialog.show();
//     QEventLoop().exec();
//
// This also requires overriding the default minimal Qt platform:
//
//     src/qt/test/test_bitcoin-qt -platform xcb      # Linux
//     src/qt/test/test_bitcoin-qt -platform windows  # Windows
//     src/qt/test/test_bitcoin-qt -platform cocoa    # macOS
void TestSendCoins()
{
    // Set up wallet and chain with 101 blocks (1 mature block for spending).
    TestChain100Setup test;
    test.CreateAndProcessBlock({}, GetScriptForRawPubKey(test.coinbaseKey.GetPubKey()));
    WalletDatabaseGuard database;
    std::unique_ptr<CWalletDBWrapper> dbw(new CWalletDBWrapper(&bitdb, "wallet_test.dat"));
    CWallet wallet(std::move(dbw));
    bool firstRun;
    QCOMPARE(wallet.LoadWallet(firstRun), DB_LOAD_OK);
    {
        LOCK(wallet.cs_wallet);
        wallet.SetAddressBook(test.coinbaseKey.GetPubKey().GetID(), "", "receive");
        wallet.AddKeyPubKey(test.coinbaseKey, test.coinbaseKey.GetPubKey());
    }
    wallet.ScanForWalletTransactions(chainActive.Genesis(), true);
    wallet.SetBroadcastTransactions(true);

    // Create widgets for sending coins and listing transactions.
    std::unique_ptr<const PlatformStyle> platformStyle(PlatformStyle::instantiate("other"));
    SendCoinsDialog sendCoinsDialog(platformStyle.get());
    OptionsModel optionsModel;
    WalletModel walletModel(platformStyle.get(), &wallet, &optionsModel);
    sendCoinsDialog.setModel(&walletModel);

    // Render the actual send form in both modern themes when a QA directory is supplied.
    const QString themeDirectory = qEnvironmentVariable("YERBAS_SEND_THEME_DIR");
    if (!themeDirectory.isEmpty()) {
        for (const QString& theme : {QString("dark"), QString("light")}) {
            QFile css(themeDirectory + "/modern-" + theme + ".css");
            QVERIFY(css.open(QFile::ReadOnly));
            sendCoinsDialog.setStyleSheet(QString::fromUtf8(css.readAll()));
            sendCoinsDialog.resize(1100, 800);
            sendCoinsDialog.show();
            QTest::qWait(100);
            auto* recipients = sendCoinsDialog.findChild<QWidget*>("scrollAreaWidgetContents");
            QVERIFY(recipients);
            const QColor expected(theme == "dark" ? "#182225" : "#ffffff");
            const QImage image = recipients->grab().toImage();
            QCOMPARE(image.pixelColor(image.width()/2, image.height()-5), expected);
            QVERIFY(sendCoinsDialog.grab().save("send-" + theme + ".png"));
        }
    }
    auto* recipientAmount = sendCoinsDialog.findChild<BitcoinAmountField*>("payAmount");
    auto* useBalance = sendCoinsDialog.findChild<QPushButton*>("useAvailableBalanceButton");
    auto* subtractFee = sendCoinsDialog.findChild<QCheckBox*>("checkboxSubtractFeeFromAmount");
    QVERIFY(recipientAmount && useBalance && subtractFee);
    useBalance->click();
    QVERIFY(recipientAmount->value() > 0);
    QVERIFY(subtractFee->isChecked());
    subtractFee->setChecked(false);
    sendCoinsDialog.hide();

    // Exercise real clicks: removed Qt signal names previously left these controls stale.
    auto* smartFee = sendCoinsDialog.findChild<QRadioButton*>("radioSmartFee");
    auto* customFee = sendCoinsDialog.findChild<QRadioButton*>("radioCustomFee");
    auto* minimumFee = sendCoinsDialog.findChild<QCheckBox*>("checkBoxMinimumFee");
    auto* target = sendCoinsDialog.findChild<QComboBox*>("confTargetSelector");
    auto* amount = sendCoinsDialog.findChild<BitcoinAmountField*>("customFee");
    QVERIFY(smartFee && customFee && minimumFee && target && amount);
    auto* feeEditor = amount->findChild<QAbstractSpinBox*>();
    auto* feeUnit = amount->findChild<QComboBox*>();
    QVERIFY(feeEditor && feeUnit);
    minimumFee->setChecked(false);
    smartFee->click();
    QVERIFY(target->isEnabled());
    QVERIFY(!feeEditor->isEnabled());
    QVERIFY(!feeUnit->isEnabled());
    customFee->click();
    QVERIFY(!target->isEnabled());
    QVERIFY(minimumFee->isEnabled());
    QVERIFY(feeEditor->isEnabled());
    QVERIFY(feeUnit->isEnabled());
    smartFee->click();
    QVERIFY(target->isEnabled());
    QVERIFY(!minimumFee->isEnabled());
    QVERIFY(!feeEditor->isEnabled());
    QVERIFY(!feeUnit->isEnabled());

    // An offline GUI must explain the problem before preparing or signing a payment.
    ClientModel disconnected(&optionsModel);
    sendCoinsDialog.setClientModel(&disconnected);
    bool offlineWarning = false;
    QTimer::singleShot(0, [&offlineWarning]() {
        for (QWidget* widget : QApplication::topLevelWidgets()) {
            if (auto* box = qobject_cast<QMessageBox*>(widget)) {
                offlineWarning = box->text().contains("No transaction has been created");
                box->accept();
            }
        }
    });
    QMetaObject::invokeMethod(&sendCoinsDialog, "on_sendButton_clicked");
    QVERIFY(offlineWarning);
    QCOMPARE(walletModel.getTransactionTableModel()->rowCount({}), 101);
    sendCoinsDialog.setClientModel(nullptr);

    // Send two transactions within the mature Yerbas reward, and verify the transaction list.
    TransactionTableModel* transactionTableModel = walletModel.getTransactionTableModel();
    QCOMPARE(transactionTableModel->rowCount({}), 101);
    uint256 txid1 = SendCoins(wallet, sendCoinsDialog, CBitcoinAddress(CKeyID()), COIN / 10);
    QVERIFY(!txid1.IsNull());
    uint256 txid2 = SendCoins(wallet, sendCoinsDialog, CBitcoinAddress(CKeyID()), COIN / 5);
    QVERIFY(!txid2.IsNull());
    QVERIFY(txid1 != txid2);
    QCOMPARE(transactionTableModel->rowCount({}), 103);
    QVERIFY(FindTx(*transactionTableModel, txid1).isValid());
    QVERIFY(FindTx(*transactionTableModel, txid2).isValid());

}

}

void WalletTests::walletTests()
{
    TestSendCoins();
}
