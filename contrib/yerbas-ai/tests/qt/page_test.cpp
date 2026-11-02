#include "yerbasaipage.h"
#include "rewarddisplay.h"
#include "requestdisplay.h"
#include <QApplication>
#include <QDir>
#include <QProcess>
#include <sys/file.h>
#include <unistd.h>
#include <QFile>
#include <QLabel>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QSettings>
#include <QTemporaryDir>
#include <QtTest>
#include <QLocalServer>
#include <QLocalSocket>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>
#include <QLineEdit>
#include <QSysInfo>
#include <QDateTime>
#include <QTimer>

class PageTests : public QObject {
    Q_OBJECT
private slots:
    void initTestCase() { QCoreApplication::setOrganizationName("YerbasAITest");QCoreApplication::setApplicationName("IsolatedPage");QSettings().clear(); }
    void missingAndModifiedPackageRejected() {
        YerbasAIPage page;QVERIFY(!page.loadPackage("/missing-yerbas-ai-package"));
        QVERIFY(!page.findChild<QPushButton*>("aiGenerate")->isEnabled());
        QTemporaryDir tmp;QFile f(tmp.path()+"/RELEASE.json");QVERIFY(f.open(QIODevice::WriteOnly));f.write("{}");f.close();
        QVERIFY(!page.loadPackage(tmp.path()));
    }
    void unexpectedCodeRejected() {
        YerbasAIPage page;QVERIFY(!page.loadPackage(qEnvironmentVariable("YERBAS_TEST_EXTRA_PACKAGE")));
        QVERIFY(!page.findChild<QPushButton*>("aiGenerate")->isEnabled());
    }
    void localGenerationAndNoShellExpansion() {
        YerbasAIPage page;page.resize(900,650);page.show();
        QVERIFY(page.loadPackage(qEnvironmentVariable("YERBAS_TEST_PACKAGE")));
        QVERIFY(page.findChild<QLabel*>("aiDetails")->text().contains("2.436"));
        QTemporaryDir tmp;const QString marker=tmp.path()+"/should-not-exist";
        const QString prompt="Alice $(touch "+marker+") ";
        page.findChild<QPlainTextEdit*>("aiPrompt")->setPlainText(prompt);
        page.findChild<QPushButton*>("aiGenerate")->click();
        QTRY_VERIFY_WITH_TIMEOUT(page.findChild<QLabel*>("aiStatus")->text().startsWith("Completed locally"),10000);
        QVERIFY(page.findChild<QPlainTextEdit*>("aiOutput")->toPlainText().startsWith(prompt));
        QVERIFY(!QFile::exists(marker));
        page.findChild<QPlainTextEdit*>("aiPrompt")->setPlainText("Alice was ");
        page.findChild<QPushButton*>("aiGenerate")->click();
        QTRY_VERIFY_WITH_TIMEOUT(page.findChild<QLabel*>("aiStatus")->text().startsWith("Completed locally"),10000);
        QVERIFY(page.grab().save(qEnvironmentVariable("YERBAS_TEST_SCREENSHOT")));
    }
    void stopAndPromptBound() {
        YerbasAIPage page;QVERIFY(page.loadPackage(qEnvironmentVariable("YERBAS_TEST_PACKAGE")));
        page.findChild<QPlainTextEdit*>("aiPrompt")->setPlainText(QString(4097,'x'));
        page.findChild<QPushButton*>("aiGenerate")->click();
        QVERIFY(page.findChild<QLabel*>("aiStatus")->text().contains("4096"));
        page.findChild<QPlainTextEdit*>("aiPrompt")->setPlainText("Alice was ");
        page.findChild<QPushButton*>("aiGenerate")->click();page.findChild<QPushButton*>("aiStop")->click();
        QTRY_COMPARE_WITH_TIMEOUT(page.findChild<QLabel*>("aiStatus")->text(),QString("Generation stopped."),10000);
        QVERIFY(page.findChild<QPushButton*>("aiGenerate")->isEnabled());
    }
    void historyAndExactJobStop() {
        QTemporaryDir root;QDir dir(root.path());QVERIFY(dir.mkpath("work/operator"));QVERIFY(dir.mkdir("outputs"));
        QFile::setPermissions(root.path()+"/work/operator",QFile::ReadOwner|QFile::WriteOwner|QFile::ExeOwner);
        const QString run(32,'a'), other(32,'b');
        auto save = [&](const QString& path, const QByteArray& data) { QFile f(root.path()+path);QVERIFY(f.open(QIODevice::WriteOnly));QCOMPARE(f.write(data),data.size()); };
        save("/work/operator/active.json",("{\"run_id\":\""+run+"\",\"phase\":\"training\",\"updated_at\":1}").toUtf8());
        save("/outputs/text-handoff-"+run+".json",("{\"run_id\":\""+run+"\",\"passed\":true,\"final_step\":6000}").toUtf8());
        QFile lock(root.path()+"/work/operator/session.lock");QVERIFY(lock.open(QIODevice::ReadWrite));
        YerbasAIPage page;page.loadPilot(root.path());
        auto* text=page.findChild<QPlainTextEdit*>("aiJobs");auto* stop=page.findChild<QPushButton*>("aiStopJob");
        QVERIFY(text->toPlainText().contains("Historical session"));QVERIFY(text->toPlainText().contains("reported passed"));QVERIFY(!stop->isEnabled());
        QVERIFY(::flock(lock.handle(),LOCK_EX|LOCK_NB)==0);
        page.findChild<QPushButton*>("aiRefreshJobs")->click();QVERIFY(stop->isEnabled());stop->click();
        QVERIFY(QFile::exists(root.path()+"/work/operator/"+run+".stop"));QVERIFY(text->toPlainText().contains("shutdown is not confirmed"));
        QVERIFY(QFile::remove(root.path()+"/work/operator/"+run+".stop"));
        page.findChild<QPushButton*>("aiRefreshJobs")->click();
        save("/work/operator/active.json",("{\"run_id\":\""+other+"\",\"phase\":\"training\",\"updated_at\":2}").toUtf8());
        stop->click();QVERIFY(text->toPlainText().contains("Stop rejected"));
        QVERIFY(!QFile::exists(root.path()+"/work/operator/"+run+".stop"));QVERIFY(!QFile::exists(root.path()+"/work/operator/"+other+".stop"));
        ::flock(lock.handle(),LOCK_UN);page.findChild<QPushButton*>("aiRefreshJobs")->click();QVERIFY(!stop->isEnabled());
    }
    void invalidAndSymlinkSessionRejected() {
        QTemporaryDir root;QDir dir(root.path());QVERIFY(dir.mkpath("work/operator"));QVERIFY(dir.mkdir("outputs"));
        QFile::setPermissions(root.path()+"/work/operator",QFile::ReadOwner|QFile::WriteOwner|QFile::ExeOwner);
        QFile lock(root.path()+"/work/operator/session.lock");QVERIFY(lock.open(QIODevice::ReadWrite));QVERIFY(::flock(lock.handle(),LOCK_EX|LOCK_NB)==0);
        QFile data(root.path()+"/elsewhere");QVERIFY(data.open(QIODevice::WriteOnly));data.write("{}");data.close();
        QVERIFY(QFile::link(data.fileName(),root.path()+"/work/operator/active.json"));
        YerbasAIPage page;page.loadPilot(root.path());QVERIFY(!page.findChild<QPushButton*>("aiStopJob")->isEnabled());
        QVERIFY(page.findChild<QPlainTextEdit*>("aiJobs")->toPlainText().contains("unavailable"));
    }
    void existingSupervisorAcceptsStop() {
        QTemporaryDir root;QDir(root.path()).mkpath("outputs");
        QProcess supervisor;
        const QString script = "import sys,time;sys.path.insert(0,sys.argv[1]);from operator_session import Session;from pathlib import Path;s=Session(Path(sys.argv[2])/'work/operator','c'*32);s.phase('training');\nwhile not s.stopped(): time.sleep(.02)\ns.close('stopped')";
        supervisor.start("python3",QStringList()<<"-I"<<"-B"<<"-c"<<script<<qEnvironmentVariable("YERBAS_TEST_PROTOTYPE")<<root.path());
        QVERIFY(supervisor.waitForStarted());
        QTRY_VERIFY_WITH_TIMEOUT(QFile::exists(root.path()+"/work/operator/active.json"),3000);
        YerbasAIPage page;page.loadPilot(root.path());
        auto* stop=page.findChild<QPushButton*>("aiStopJob");QVERIFY(stop->isEnabled());stop->click();
        QTRY_COMPARE_WITH_TIMEOUT(supervisor.state(),QProcess::NotRunning,3000);QCOMPARE(supervisor.exitCode(),0);
        page.findChild<QPushButton*>("aiRefreshJobs")->click();QVERIFY(!stop->isEnabled());
        QVERIFY(page.findChild<QPlainTextEdit*>("aiJobs")->toPlainText().contains("stopped"));
    }
    void realHistoricalResultsReadOnly() {
        YerbasAIPage page;page.resize(1100,850);page.show();
        page.loadPilot(qEnvironmentVariable("YERBAS_TEST_WORKSPACE"));
        QVERIFY(page.findChild<QPlainTextEdit*>("aiJobs")->toPlainText().contains("c85abf7ab7b2492fa4b6410fc9c8686b"));
        QVERIFY(page.grab().save(qEnvironmentVariable("YERBAS_TEST_SCREENSHOT")));
    }
    void authenticatedAgentAndStop() {
        QTemporaryDir root;QDir(root.path()).mkpath("outputs");
        QFile::setPermissions(root.path()+"/outputs",QFile::ReadOwner|QFile::WriteOwner|QFile::ExeOwner);
        QProcess supervisor, agent;
        const QString script = "import sys,time,os;os.umask(0o077);sys.path.insert(0,sys.argv[1]);from operator_session import Session;from pathlib import Path;s=Session(Path(sys.argv[2])/'work/operator','d'*32);s.phase('training');\nwhile not s.stopped(): time.sleep(.02)\ns.close('stopped')";
        supervisor.start("python3",QStringList()<<"-I"<<"-B"<<"-c"<<script<<qEnvironmentVariable("YERBAS_TEST_PROTOTYPE")<<root.path());
        QVERIFY(supervisor.waitForStarted());
        QTRY_VERIFY_WITH_TIMEOUT(QFile::exists(root.path()+"/work/operator/active.json"),3000);
        agent.start("python3",QStringList()<<"-I"<<"-B"<<qEnvironmentVariable("YERBAS_TEST_PROTOTYPE")+"/wallet_agent.py"<<"--workspace"<<root.path()<<"--state"<<root.path()+"/agent");
        QVERIFY(agent.waitForStarted());
        QTRY_VERIFY_WITH_TIMEOUT(QFile::exists(root.path()+"/agent/control.sock"),3000);
        YerbasAIPage page;page.connectAgent(root.path()+"/agent/control.sock");
        auto* stop=page.findChild<QPushButton*>("aiAgentStop");auto* text=page.findChild<QPlainTextEdit*>("aiAgentStatus");
        QTRY_VERIFY_WITH_TIMEOUT(stop->isEnabled(),4000);QVERIFY(text->toPlainText().contains("owner-authorized"));
        stop->click();QTRY_VERIFY_WITH_TIMEOUT(text->toPlainText().contains("Stop request recorded"),4000);
        QTRY_COMPARE_WITH_TIMEOUT(supervisor.state(),QProcess::NotRunning,3000);QCOMPARE(supervisor.exitCode(),0);
        agent.terminate();QVERIFY(agent.waitForFinished(3000));
        page.connectAgent(root.path()+"/agent/control.sock");QTRY_VERIFY_WITH_TIMEOUT(text->toPlainText().contains("unavailable"),5000);
        QVERIFY(!stop->isEnabled());
    }
    void savedWalletIdentityIsClearlyHistorical() {
        QTemporaryDir root;QDir(root.path()).mkpath("outputs");QDir(root.path()).mkpath("agent");
        QFile::setPermissions(root.path()+"/agent",QFile::ReadOwner|QFile::WriteOwner|QFile::ExeOwner);
        QFile record(root.path()+"/agent/identity-status.json");QVERIFY(record.open(QIODevice::WriteOnly));
        record.write(QJsonDocument(QJsonObject{{"schema",1},{"provider",QSysInfo::machineHostName()},{"address","yAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"},{"proof",QString(64,'a')},{"active",true},{"required",true},{"checked_at",QDateTime::currentSecsSinceEpoch()},{"origin","https://192.168.0.102:9444"},{"profile","yerbas-private-reduced-collateral-testnet"}}).toJson());record.close();record.setPermissions(QFile::ReadOwner|QFile::WriteOwner);
        QFile reward(root.path()+"/agent/reward-status.json");QVERIFY(reward.open(QIODevice::WriteOnly));
        reward.write(QJsonDocument(QJsonObject{{"schema",1},{"provider",QSysInfo::machineHostName()},{"address","yAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"},{"checked_at",QDateTime::currentSecsSinceEpoch()},{"profile","yerbas-private-reduced-collateral-testnet"},{"rewards",QJsonArray{QJsonObject{{"receipt",QString(32,'a')},{"txid",QString(64,'b')},{"amount_base_units",35388},{"confirmations",6},{"required_confirmations",6},{"state","confirmed"},{"block_height",13},{"tip_height",18}}}}}).toJson());reward.close();reward.setPermissions(QFile::ReadOwner|QFile::WriteOwner);
        QProcess agent;agent.start("python3",QStringList()<<"-I"<<"-B"<<qEnvironmentVariable("YERBAS_TEST_PROTOTYPE")+"/wallet_agent.py"<<"--workspace"<<root.path()<<"--state"<<root.path()+"/agent");
        QVERIFY(agent.waitForStarted());QTRY_VERIFY_WITH_TIMEOUT(QFile::exists(root.path()+"/agent/control.sock"),3000);
        YerbasAIPage page;page.connectAgent(root.path()+"/agent/control.sock");auto* text=page.findChild<QPlainTextEdit*>("aiAgentStatus");
        QTRY_VERIFY_WITH_TIMEOUT(text->toPlainText().contains("identity active and required"),4000);
        QTRY_VERIFY_WITH_TIMEOUT(text->toPlainText().contains("0.00035388 testnet YERB"),4000);
        QVERIFY(text->toPlainText().contains("6/6 confirmations"));
        QVERIFY(text->toPlainText().contains("not live authorization"));QVERIFY(!page.findChild<QPushButton*>("aiProviderSubmit")->isEnabled());
        agent.terminate();QVERIFY(agent.waitForFinished(3000));
    }
    void rewardSnapshotValidation() {
        QJsonObject row{{"receipt",QString(32,'a')},{"txid",QString(64,'b')},{"amount_base_units",35388},{"confirmations",6},{"required_confirmations",6},{"state","confirmed"},{"block_height",13},{"tip_height",18}};
        QJsonObject snapshot{{"available",true},{"historical",true},{"live_authorization",false},{"payments_enabled",false},{"provider","host"},{"address","address"},{"profile","yerbas-private-reduced-collateral-testnet"},{"checked_at",1000},{"rewards",QJsonArray{row}}};
        auto text=walletRewardLines(snapshot,"address","host",1001).join("\n");
        QVERIFY(text.contains("0.00035388 testnet YERB"));QVERIFY(text.contains("6/6 confirmations"));QVERIFY(text.contains("cannot send"));
        QVERIFY(walletRewardLines(snapshot,"address","host",1400).join("\n").contains("stale"));
        QVERIFY(walletRewardLines(snapshot,"other","host",1001).join("\n").contains("no valid"));
        row["confirmations"]=5;snapshot["rewards"]=QJsonArray{row};
        QVERIFY(walletRewardLines(snapshot,"address","host",1001).join("\n").contains("no valid"));
        row["confirmations"]=6;snapshot["rewards"]=QJsonArray{row,row};
        QVERIFY(walletRewardLines(snapshot,"address","host",1001).join("\n").contains("no valid"));
    }
    void automaticStatusDoesNotOverlap() {
        QTemporaryDir tmp;QLocalServer server;QVERIFY(server.listen(tmp.path()+"/control.sock"));
        QStringList methods;QList<QLocalSocket*> clients;
        connect(&server,&QLocalServer::newConnection,this,[&] {
            auto* client=server.nextPendingConnection();clients.append(client);
            connect(client,&QLocalSocket::readyRead,this,[&,client] {
                if(client->canReadLine()) methods.append(QJsonDocument::fromJson(client->readLine()).object().value("method").toString());
            });
        });
        YerbasAIPage page;page.show();page.connectAgent(tmp.path()+"/control.sock");
        auto* timer=page.findChild<QTimer*>("aiStatusPoll");QVERIFY(timer);QCOMPARE(timer->interval(),60000);
        QTRY_COMPARE(methods.size(),1);QCOMPARE(methods.first(),QString("status"));
        QMetaObject::invokeMethod(timer,"timeout",Qt::DirectConnection);QTest::qWait(30);
        QCOMPARE(methods.size(),1); // An outstanding request is never interrupted or duplicated.
        clients.first()->disconnectFromServer();
        QTRY_VERIFY(page.findChild<QLabel*>("aiAgentConnection")->text().contains("unavailable"));
        page.hide();QMetaObject::invokeMethod(timer,"timeout",Qt::DirectConnection);QTest::qWait(30);QCOMPARE(methods.size(),1);
        page.show();QMetaObject::invokeMethod(timer,"timeout",Qt::DirectConnection);
        QTRY_COMPARE(methods.size(),2);QCOMPARE(methods.last(),QString("status"));
    }
    void rewardRequestWireAndDuplicate() {
        QTemporaryDir tmp;QLocalServer server;QVERIFY(server.listen(tmp.path()+"/control.sock"));
        QJsonObject stored;int requests=0;int rewardCalls=0;bool enabled=false;
        connect(&server,&QLocalServer::newConnection,this,[&] {
            auto* client=server.nextPendingConnection();
            connect(client,&QLocalSocket::disconnected,client,&QObject::deleteLater);
            connect(client,&QLocalSocket::readyRead,this,[&,client] {
                if(!client->canReadLine())return;
                auto wire=QJsonDocument::fromJson(client->readLine()).object();const auto method=wire.value("method").toString();QJsonObject result;
                if(method=="status")result=QJsonObject{{"reward_requests_ready",enabled}};
                else if(method=="rewards.request" || method=="rewards.status") {
                    ++rewardCalls;
                    QCOMPARE(wire.value("params").toObject().size(),1);
                    QCOMPARE(wire.value("params").toObject().value("receipt").toString(),QString(32,'a'));
                    if(method=="rewards.request") {++requests;stored=QJsonObject{{"schema",1},{"receipt",QString(32,'a')},{"provider",QSysInfo::machineHostName()},{"request_id",QString(64,'b')},{"status","pending_review"},{"requested_at",1},{"payment_authorized",false},{"gpu_time_approved",false}};}
                    result=QJsonObject{{"receipt",QString(32,'a')},{"request",stored.isEmpty()?QJsonValue(QJsonValue::Null):QJsonValue(stored)}};
                }
                client->write(QJsonDocument(QJsonObject{{"v",1},{"id",wire.value("id")},{"ok",true},{"result",result}}).toJson(QJsonDocument::Compact)+"\n");
            });
        });
        YerbasAIPage page;page.resize(1100,1000);page.show();page.connectAgent(tmp.path()+"/control.sock");
        auto* receipt=page.findChild<QLineEdit*>("aiRewardReceipt");auto* request=page.findChild<QPushButton*>("aiRewardRequest");auto* check=page.findChild<QPushButton*>("aiRewardCheck");auto* status=page.findChild<QLabel*>("aiRewardRequestStatus");
        receipt->setText(QString(32,'a'));QTest::qWait(50);QVERIFY(!request->isEnabled());
        enabled=true;page.connectAgent(tmp.path()+"/control.sock");QTRY_VERIFY(check->isEnabled());
        check->click();QTRY_VERIFY(status->text().contains("No reward request"));
        request->click();QTRY_VERIFY(status->text().contains("pending review"));QCOMPARE(requests,1);
        request->click();QTRY_COMPARE(requests,2);QTRY_VERIFY(status->text().contains("No payment"));
        check->click();QTRY_VERIFY(check->isEnabled());QVERIFY(status->text().contains("pending review"));
        const auto screenshot=qEnvironmentVariable("YERBAS_TEST_REQUEST_SCREENSHOT");
        if(!screenshot.isEmpty()) QVERIFY(page.grab().save(screenshot));
        const int callsBeforeEdit=rewardCalls;
        receipt->setText(QString(32,'c'));
        QVERIFY(request->isEnabled());QVERIFY(check->isEnabled());
        QVERIFY(status->text().contains("not checked for this receipt"));
        QVERIFY(!status->text().contains("pending review"));
        receipt->setText("invalid");QVERIFY(!request->isEnabled());QVERIFY(!check->isEnabled());
        receipt->clear();QVERIFY(!request->isEnabled());QVERIFY(!check->isEnabled());
        receipt->setText(QString(32,'a'));
        QVERIFY(status->text().contains("not checked for this receipt"));
        QTest::qWait(50);QCOMPARE(rewardCalls,callsBeforeEdit);
        check->click();QTRY_VERIFY(status->text().contains("pending review"));
        QCOMPARE(rewardCalls,callsBeforeEdit+1);QCOMPARE(requests,2);
    }
    void installedRewardRequest() {
        const auto path=qEnvironmentVariable("YERBAS_TEST_INSTALLED_AGENT");
        const auto id=qEnvironmentVariable("YERBAS_TEST_REQUEST_RECEIPT");
        if(path.isEmpty() || id.isEmpty()) QSKIP("Live request test requires explicit opt-in");
        QCOMPARE(id.size(),32);
        YerbasAIPage page;page.resize(1100,1000);page.show();page.connectAgent(path);
        auto* receipt=page.findChild<QLineEdit*>("aiRewardReceipt");auto* request=page.findChild<QPushButton*>("aiRewardRequest");auto* check=page.findChild<QPushButton*>("aiRewardCheck");auto* status=page.findChild<QLabel*>("aiRewardRequestStatus");
        receipt->setText(id);QTRY_VERIFY_WITH_TIMEOUT(request->isEnabled(),8000);
        check->click();QTRY_VERIFY_WITH_TIMEOUT(check->isEnabled(),8000);
        request->click();QTRY_VERIFY_WITH_TIMEOUT(status->text().contains("pending review"),8000);
        QTRY_VERIFY_WITH_TIMEOUT(request->isEnabled(),8000);request->click();
        QTRY_VERIFY_WITH_TIMEOUT(status->text().contains("pending review"),8000);
        QTRY_VERIFY_WITH_TIMEOUT(check->isEnabled(),8000);check->click();
        QTRY_VERIFY_WITH_TIMEOUT(status->text().contains("pending review"),8000);
        QTRY_VERIFY_WITH_TIMEOUT(check->isEnabled(),8000);
        const auto shot=qEnvironmentVariable("YERBAS_TEST_REQUEST_SCREENSHOT");
        if(!shot.isEmpty()) QVERIFY(page.grab().save(shot));
    }
    void installedLifecycleStatus() {
        const auto path=qEnvironmentVariable("YERBAS_TEST_INSTALLED_AGENT");
        const auto id=qEnvironmentVariable("YERBAS_TEST_REQUEST_RECEIPT");
        const auto expected=qEnvironmentVariable("YERBAS_TEST_EXPECTED_STATUS");
        if(path.isEmpty() || id.isEmpty() || expected.isEmpty()) QSKIP("Live lifecycle test requires explicit opt-in");
        YerbasAIPage page;page.resize(1100,1000);page.show();page.connectAgent(path);
        auto* receipt=page.findChild<QLineEdit*>("aiRewardReceipt");auto* check=page.findChild<QPushButton*>("aiRewardCheck");auto* status=page.findChild<QLabel*>("aiRewardRequestStatus");
        receipt->setText(id);QTRY_VERIFY_WITH_TIMEOUT(check->isEnabled(),8000);
        check->click();QTRY_VERIFY_WITH_TIMEOUT(status->text().contains(expected),8000);
        QTRY_VERIFY_WITH_TIMEOUT(check->isEnabled(),8000);
        const auto shot=qEnvironmentVariable("YERBAS_TEST_REQUEST_SCREENSHOT");
        if(!shot.isEmpty()) QVERIFY(page.grab().save(shot));
    }
    void lifecycleDisplayValidation() {
        QJsonObject d{{"status","approved"},{"amount_base_units",1000000},{"basis","fixed_private_testnet_allowance"},{"verification_sha256",QString(64,'c')}};
        QJsonObject r{{"schema",2},{"request_id",QString(64,'b')},{"receipt",QString(32,'a')},{"provider","host"},{"status","approved"},{"requested_at",10},{"payment_authorized",false},{"gpu_time_approved",false},{"lifecycle",d}};
        auto render=[&]{return requestStatusText(r,QString(32,'a'),"host",1000);};
        QVERIFY(render().contains("0.01000000"));QVERIFY(render().contains("not yet recorded"));
        d["status"]="confirmed";d["plan_sha256"]=QString(64,'d');d["txid"]=QString(64,'e');d["confirmations"]=6;d["block_height"]=19;d["tip_height"]=24;d["blockhash"]=QString(64,'f');d["observed_at"]=900;r["status"]="confirmed";r["lifecycle"]=d;
        QVERIFY(render().contains("6/6 confirmations"));
        d["confirmations"]=5;r["lifecycle"]=d;QVERIFY(render().isEmpty());
        d["confirmations"]=6;d["observed_at"]=100;r["lifecycle"]=d;QVERIFY(render().contains("stale"));
        d["status"]="reorged";for(const auto k:{"confirmations","block_height","tip_height","blockhash"})d[k]=QJsonValue(QJsonValue::Null);r["status"]="reorged";r["lifecycle"]=d;
        QVERIFY(render().contains("no replacement sent"));
        r["provider"]="other";QVERIFY(render().isEmpty());r["provider"]="host";
        r["payment_authorized"]=true;QVERIFY(render().isEmpty());
    }
    void installedRewardReadOnly() {
        const QString path=qEnvironmentVariable("YERBAS_TEST_INSTALLED_AGENT");
        if(path.isEmpty()) QSKIP("Installed reward check is opt-in");
        const QString amount=qEnvironmentVariable("YERBAS_TEST_REWARD_AMOUNT");
        const QString tx=qEnvironmentVariable("YERBAS_TEST_REWARD_TXID");
        const QString depth=qEnvironmentVariable("YERBAS_TEST_REWARD_DEPTH");
        QVERIFY(!amount.isEmpty());QCOMPARE(tx.size(),64);QVERIFY(!depth.isEmpty());
        YerbasAIPage page;page.resize(1100,850);page.show();page.connectAgent(path);
        auto* text=page.findChild<QPlainTextEdit*>("aiAgentStatus");
        QTRY_VERIFY_WITH_TIMEOUT(text->toPlainText().contains(amount+" testnet YERB"),5000);
        auto* summary=page.findChild<QLabel*>("aiRewardSummary");
        QVERIFY(summary->isVisible());QVERIFY(summary->text().contains(depth+" confirmations"));
        QVERIFY(!text->isVisible());QVERIFY(text->toPlainText().contains(tx));
        QVERIFY(text->toPlainText().contains("Not a live wallet balance"));
        QVERIFY(text->toPlainText().contains("cannot send rewards"));
        QVERIFY(!page.findChild<QPushButton*>("aiProviderSubmit")->isEnabled());
        const auto shot=qEnvironmentVariable("YERBAS_TEST_AGENT_SCREENSHOT");
        if(!shot.isEmpty()) QVERIFY(page.grab().save(shot));
    }
    void installedWalletIdentityReadOnly() {
        const QString path=qEnvironmentVariable("YERBAS_TEST_INSTALLED_AGENT");
        if(path.isEmpty()) QSKIP("Installed identity check is opt-in");
        YerbasAIPage page;page.connectAgent(path);auto* text=page.findChild<QPlainTextEdit*>("aiAgentStatus");
        QTRY_VERIFY_WITH_TIMEOUT(text->toPlainText().contains("identity active and required"),5000);
        QVERIFY(text->toPlainText().contains("not live authorization"));
        QVERIFY(text->toPlainText().contains(qEnvironmentVariable("YERBAS_TEST_IDENTITY_ADDRESS")));
        QVERIFY(!page.findChild<QPushButton*>("aiProviderSubmit")->isEnabled());
    }
    void installedAgentReadOnlyConnection() {
        const QString path=qEnvironmentVariable("YERBAS_TEST_INSTALLED_AGENT");
        if (path.isEmpty()) QSKIP("Installed agent smoke is opt-in");
        QDir data=QFileInfo(path).dir();QVERIFY(data.cdUp());QVERIFY(data.cdUp());
        const QByteArray oldData=qgetenv("XDG_DATA_HOME");qputenv("XDG_DATA_HOME",data.absolutePath().toUtf8());
        YerbasAIPage page;
        if (oldData.isNull()) qunsetenv("XDG_DATA_HOME");else qputenv("XDG_DATA_HOME",oldData);
        page.resize(1100,900);page.show();
        auto* text=page.findChild<QPlainTextEdit*>("aiAgentStatus");
        QTRY_VERIFY_WITH_TIMEOUT(text->toPlainText().contains("Historical reports: 0"),5000);
        QVERIFY(text->toPlainText().contains("owner-authorized"));
        if (qEnvironmentVariableIsSet("YERBAS_TEST_PROVIDER_LINK"))
            QVERIFY(text->toPlainText().contains("Protected provider service connected. GPU submissions are disabled."));
        QVERIFY(!page.findChild<QPushButton*>("aiAgentStop")->isEnabled());
        const QString screenshot=qEnvironmentVariable("YERBAS_TEST_AGENT_SCREENSHOT");
        if (!screenshot.isEmpty()) QVERIFY(page.grab().save(screenshot));
    }
    void providerStopRetriesSameIdAndRejectsWrongJob() {
        QTemporaryDir tmp;QLocalServer server;QVERIFY(server.listen(tmp.path()+"/control.sock"));
        QStringList stopIds;bool wrongJob=false;bool drop=true;
        connect(&server,&QLocalServer::newConnection,&server,[&] {
            auto* socket=server.nextPendingConnection();
            connect(socket,&QLocalSocket::disconnected,socket,&QObject::deleteLater);
            connect(socket,&QLocalSocket::readyRead,socket,[&,socket] {
                QByteArray raw=socket->property("frame").toByteArray()+socket->readAll();socket->setProperty("frame",raw);
                if (!raw.endsWith('\n')) return;
                auto request=QJsonDocument::fromJson(raw).object();auto method=request.value("method").toString();QJsonObject result;
                if (method=="provider.status") result={{"id",wrongJob ? QString(32,'c') : QString(32,'b')},{"state","running"}};
                else if (method=="provider.cancel") {
                    stopIds << request.value("id").toString();
                    if(drop) { socket->disconnectFromServer();return; }
                    result={{"run_id",QString(32,'b')},{"stop_recorded",true},{"shutdown_confirmed",false}};
                }
                QJsonObject response{{"v",1},{"id",request.value("id")},{"ok",true},{"result",result}};
                socket->write(QJsonDocument(response).toJson(QJsonDocument::Compact)+"\n");socket->flush();
            });
        });
        YerbasAIPage page;page.connectAgent(tmp.path()+"/control.sock");
        auto* input=page.findChild<QLineEdit*>("aiProviderRun");auto* refresh=page.findChild<QPushButton*>("aiProviderRefresh");auto* stop=page.findChild<QPushButton*>("aiProviderStop");
        input->setText(QString(32,'b'));QTRY_VERIFY_WITH_TIMEOUT(refresh->isEnabled(),5000);
        refresh->click();QTRY_VERIFY_WITH_TIMEOUT(stop->isEnabled(),5000);stop->click();
        QTRY_VERIFY_WITH_TIMEOUT(refresh->isEnabled(),5000);QVERIFY(!stop->isEnabled());
        drop=false;refresh->click();QTRY_VERIFY_WITH_TIMEOUT(stop->isEnabled(),5000);stop->click();
        QTRY_COMPARE_WITH_TIMEOUT(stopIds.size(),2,5000);QCOMPARE(stopIds[0],stopIds[1]);
        QTRY_VERIFY_WITH_TIMEOUT(page.findChild<QPlainTextEdit*>("aiAgentStatus")->toPlainText().contains("Stop recorded"),5000);
        wrongJob=true;refresh->click();QTRY_VERIFY_WITH_TIMEOUT(refresh->isEnabled(),5000);QVERIFY(!stop->isEnabled());
        input->setText("invalid");QVERIFY(!refresh->isEnabled());
    }
    void preassignedSubmissionWire() {
        QTemporaryDir tmp;QLocalServer server;QVERIFY(server.listen(tmp.path()+"/control.sock"));QStringList ids;bool drop=true;
        connect(&server,&QLocalServer::newConnection,&server,[&] {
            auto* socket=server.nextPendingConnection();connect(socket,&QLocalSocket::disconnected,socket,&QObject::deleteLater);
            connect(socket,&QLocalSocket::readyRead,socket,[&,socket] {
                QByteArray raw=socket->property("frame").toByteArray()+socket->readAll();socket->setProperty("frame",raw);if(!raw.endsWith('\n'))return;
                auto req=QJsonDocument::fromJson(raw).object();auto method=req.value("method").toString();QJsonObject result;
                if(method=="status")result={{"submission_ready",true}};
                if(method=="provider.submit") {
                    QCOMPARE(req.value("params").toObject().size(),2);QCOMPARE(req.value("params").toObject().value("contribution").toString(),QString("approved"));
                    ids << req.value("id").toString();if(drop){socket->disconnectFromServer();return;}
                    result={{"run_id",QString(32,'b')},{"request_recorded",true},{"training_started",false}};
                }
                socket->write(QJsonDocument(QJsonObject{{"v",1},{"id",req.value("id")},{"ok",true},{"result",result}}).toJson(QJsonDocument::Compact)+"\n");socket->flush();
            });
        });
        YerbasAIPage page;page.connectAgent(tmp.path()+"/control.sock");
        auto* run=page.findChild<QLineEdit*>("aiProviderRun");auto* contribution=page.findChild<QLineEdit*>("aiContribution");auto* submit=page.findChild<QPushButton*>("aiProviderSubmit");
        run->setText(QString(32,'b'));contribution->setText("approved");QTRY_VERIFY_WITH_TIMEOUT(submit->isEnabled(),5000);submit->click();
        QTRY_VERIFY_WITH_TIMEOUT(submit->isEnabled(),5000);drop=false;submit->click();QTRY_COMPARE_WITH_TIMEOUT(ids.size(),2,5000);QCOMPARE(ids[0],ids[1]);
        QTRY_VERIFY_WITH_TIMEOUT(page.findChild<QPlainTextEdit*>("aiAgentStatus")->toPlainText().contains("Submission recorded"),5000);
        contribution->setText("changed");submit->click();QVERIFY(page.findChild<QPlainTextEdit*>("aiAgentStatus")->toPlainText().contains("already bound"));QCOMPARE(ids.size(),2);
        const QString file=tmp.path()+"/expiring-job.json";QFile ticket(file);QVERIFY(ticket.open(QIODevice::WriteOnly));
        ticket.write(QJsonDocument(QJsonObject{{"schema",1},{"run_id",QString(32,'d')},{"contribution","approved"},{"provider",QSysInfo::machineHostName()},{"recipe","byte-context-mlp-v1"},{"simulated_credits_reserved",9},{"lease_until",double(QDateTime::currentSecsSinceEpoch()+2)}}).toJson());ticket.close();
        QVERIFY(page.loadPreparedJob(file));QVERIFY(submit->isEnabled());QTRY_VERIFY_WITH_TIMEOUT(!submit->isEnabled(),4000);QCOMPARE(ids.size(),2);

    }
    void livePreassignedSubmission() {
        const QString path=qEnvironmentVariable("YERBAS_TEST_SUBMIT_AGENT");if(path.isEmpty())QSKIP("Live bounded training is explicit opt-in");
        YerbasAIPage page;page.connectAgent(path);
        page.findChild<QLineEdit*>("aiProviderRun")->setText(qEnvironmentVariable("YERBAS_TEST_SUBMIT_RUN"));
        page.findChild<QLineEdit*>("aiContribution")->setText(qEnvironmentVariable("YERBAS_TEST_SUBMIT_CONTRIBUTION"));
        auto* submit=page.findChild<QPushButton*>("aiProviderSubmit");auto* refresh=page.findChild<QPushButton*>("aiProviderRefresh");auto* status=page.findChild<QPlainTextEdit*>("aiAgentStatus");
        QTRY_VERIFY_WITH_TIMEOUT(submit->isEnabled(),5000);submit->click();
        QTRY_VERIFY_WITH_TIMEOUT(status->toPlainText().contains("Submission recorded"),5000);
        QElapsedTimer timer;timer.start();bool completed=false;
        while(timer.elapsed()<60000){
            if(refresh->isEnabled())refresh->click();QTest::qWait(500);
            if(status->toPlainText().contains(": completed.")){completed=true;break;}
            if(status->toPlainText().contains(": failed.") || status->toPlainText().contains(": uncertain."))break;
        }
        QVERIFY2(completed,qPrintable(status->toPlainText()));
        QVERIFY(!page.findChild<QPushButton*>("aiProviderStop")->isEnabled());
    }
    void livePreassignedStop() {
        const QString path=qEnvironmentVariable("YERBAS_TEST_SUBMIT_AGENT");if(path.isEmpty())QSKIP("Live cancellation is explicit opt-in");
        YerbasAIPage page;page.connectAgent(path);
        page.findChild<QLineEdit*>("aiProviderRun")->setText(qEnvironmentVariable("YERBAS_TEST_SUBMIT_RUN"));
        page.findChild<QLineEdit*>("aiContribution")->setText(qEnvironmentVariable("YERBAS_TEST_SUBMIT_CONTRIBUTION"));
        auto* submit=page.findChild<QPushButton*>("aiProviderSubmit");auto* refresh=page.findChild<QPushButton*>("aiProviderRefresh");auto* stop=page.findChild<QPushButton*>("aiProviderStop");auto* status=page.findChild<QPlainTextEdit*>("aiAgentStatus");
        QTRY_VERIFY_WITH_TIMEOUT(submit->isEnabled(),5000);submit->click();QTRY_VERIFY_WITH_TIMEOUT(status->toPlainText().contains("Submission recorded"),5000);
        QElapsedTimer timer;timer.start();bool gpuObserved=false;
        while(timer.elapsed()<30000){
            if(refresh->isEnabled())refresh->click();QTest::qWait(100);
            QProcess probe;probe.start("/usr/bin/nvidia-smi",QStringList()<<QString("--id=%1").arg(qEnvironmentVariable("YERBAS_TEST_PHYSICAL_GPU", "1"))<<"--query-compute-apps=pid"<<"--format=csv,noheader");QVERIFY(probe.waitForFinished(3000));
            if(!probe.readAllStandardOutput().trimmed().isEmpty() && stop->isEnabled()){gpuObserved=true;break;}
        }
        QVERIFY(gpuObserved);qInfo("Observed GPU compute process before wallet Stop click");stop->click();
        QTRY_VERIFY_WITH_TIMEOUT(status->toPlainText().contains("Stop recorded") || status->toPlainText().contains("terminal"),5000);
        timer.restart();bool cancelled=false;
        while(timer.elapsed()<45000){
            if(refresh->isEnabled())refresh->click();QTest::qWait(300);
            if(status->toPlainText().contains(": cancelled.")){cancelled=true;break;}
        }
        QVERIFY2(cancelled,qPrintable(status->toPlainText()));QVERIFY(!stop->isEnabled());
    }
    void preparedJobValidation() {
        QTemporaryDir tmp;YerbasAIPage page;page.connectAgent(QString());
        const QString path=tmp.path()+"/job.json";
        QJsonObject job{{"schema",1},{"run_id",QString(32,'b')},{"contribution","text-approved"},{"provider",QSysInfo::machineHostName()},{"recipe","byte-context-mlp-v1"},{"simulated_credits_reserved",9},{"lease_until",double(QDateTime::currentSecsSinceEpoch()+120)}};
        auto write=[&](const QJsonObject& value){QFile f(path);QVERIFY(f.open(QIODevice::WriteOnly|QIODevice::Truncate));f.write(QJsonDocument(value).toJson());};
        write(job);QVERIFY(page.loadPreparedJob(path));
        QCOMPARE(page.findChild<QLineEdit*>("aiProviderRun")->text(),QString(32,'b'));
        QCOMPARE(page.findChild<QLineEdit*>("aiContribution")->text(),QString("text-approved"));
        QVERIFY(!page.findChild<QPushButton*>("aiProviderSubmit")->isEnabled());
        QVERIFY(page.findChild<QLabel*>("aiPreparedDetails")->text().contains("loading starts nothing"));
        for(const QString field:QStringList{"provider","recipe","run_id","command","lease_until"}){
            auto bad=job;if(field=="lease_until")bad[field]=double(QDateTime::currentSecsSinceEpoch()-1);else bad[field]="invalid";
            write(bad);QVERIFY(!page.loadPreparedJob(path));QVERIFY(page.findChild<QLineEdit*>("aiProviderRun")->text().isEmpty());
        }
        write(job);QVERIFY(QFile::link(path,tmp.path()+"/link.json"));QVERIFY(!page.loadPreparedJob(tmp.path()+"/link.json"));
        QFile oversized(path);QVERIFY(oversized.open(QIODevice::WriteOnly|QIODevice::Truncate));oversized.write(QByteArray(8193,'x'));oversized.close();QVERIFY(!page.loadPreparedJob(path));
    }
    void importPreparedToolFile() {
        const QString path=qEnvironmentVariable("YERBAS_TEST_JOB_FILE");if(path.isEmpty())QSKIP("Fresh preparation integration is opt-in");
        YerbasAIPage page;page.connectAgent(QString());QVERIFY(page.loadPreparedJob(path));
        QVERIFY(!page.findChild<QLineEdit*>("aiProviderRun")->text().isEmpty());
        QVERIFY(!page.findChild<QPushButton*>("aiProviderSubmit")->isEnabled());
    }
    void cleanupTestCase() { QSettings().clear(); }
};
QTEST_MAIN(PageTests)
#include "page_test.moc"
