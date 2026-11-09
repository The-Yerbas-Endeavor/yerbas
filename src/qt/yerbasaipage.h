#ifndef YERBAS_QT_YERBASAIPAGE_H
#define YERBAS_QT_YERBASAIPAGE_H
#include <QWidget>
#include <QByteArray>
#include "workpurchasewidget.h"
class QLocalSocket;
class OfferWidget;
class RentalWidget;
class CapacityWidget;
class QLabel;
class QLineEdit;
class QPlainTextEdit;
class QPushButton;
class QProcess;
class QTimer;
class QTemporaryDir;

/** Local model UI. Deliberately has no wallet/key/chain dependency. */
class YerbasAIPage : public QWidget
{
    Q_OBJECT
public:
    explicit YerbasAIPage(QWidget* parent = nullptr);
    ~YerbasAIPage();
    void connectAgent(const QString& path);
    void setWorkRefundContext(WorkPurchaseWidget::RefundContext callback);
    void setWorkSavedSelector(std::function<QJsonObject()> callback);
    void setWorkHistory(std::function<void()> callback);
    void setWorkPayment(WorkPurchaseWidget::Pay callback);
    void loadPilot(const QString& directory);
    bool loadPackage(const QString& directory);
    bool loadPreparedJob(const QString& path);
Q_SIGNALS:
    void marketplaceAgentChanged(const QString& path, bool ready);
private:
    OfferWidget* offers;
    RentalWidget* rentals;
    WorkPurchaseWidget* purchase;
    CapacityWidget* capacity;
    QLocalSocket* agentSocket;
    QTimer* agentDeadline;
    QPlainTextEdit* agentStatus;
    QLabel* agentConnection;
    QLabel* rewardSummary;
    QLineEdit* rewardReceipt;
    QPushButton* rewardRequest;
    QPushButton* rewardCheck;
    QLabel* rewardRequestStatus;
    QString requestedReceipt;
    bool rewardRequestsReady = false;
    void updateRewardControls();
    QPushButton* agentRefresh;
    QPushButton* agentStop;
    QString agentPath, agentRequestId, agentMethod, agentRun;
    QLineEdit* providerRunInput;
    QLineEdit* providerContribution;
    QPushButton* providerSubmit;
    bool submissionReady = false;
    qint64 preparedDeadline = 0;
    QLabel* preparedDetails = nullptr;
    QString submissionContribution, submissionKey;
    QPushButton* providerRefresh;
    QPushButton* providerStop;
    QString providerRun, providerStopKey;
    void updateProviderControls();
    QByteArray agentResponse;
    void agentRequest(const QString& method);
    void agentFailure();
    void agentRead();
    QLineEdit* pilotPath;
    QPlainTextEdit* jobs;
    QPushButton* stopJob;
    QString displayedRun;
    void refreshJobs();
    void requestJobStop();
    QLabel* status;
    QLabel* details;
    QLineEdit* packagePath;
    QPlainTextEdit* prompt;
    QPlainTextEdit* output;
    QPushButton* choose;
    QPushButton* generate;
    QPushButton* stop;
    QProcess* process;
    QTimer* deadline;
    QTemporaryDir* pythonCache;
    QByteArray response;
    bool cancelled = false;
    bool verified = false;
    void setBusy(bool busy);
    void startGeneration();
    void stopGeneration();
    void consumeOutput();
};
#endif
