#include <QtTest>
#include <QLocalServer>
#include <QTemporaryDir>
#include "workpurchasewidget.h"
class PurchaseTest:public QObject {
 Q_OBJECT
 QTemporaryDir dir;QLocalServer server;QJsonObject cap,quote,preview;WorkFunding::Context context;QStringList actions;int payments=0;QString corruptSchedule;bool badSchedule=false;QStringList scheduleIds;bool badAck=false,disabled=false,recoveryDisabled=false,terminalRecovery=false;
 std::unique_ptr<WorkPurchaseWidget> widget;
 void click(const char* name){auto* button=widget->findChild<QPushButton*>(name);QVERIFY(button);QVERIFY(button->isEnabled());button->click();}
private Q_SLOTS:
 void init(){
  actions.clear();scheduleIds.clear();corruptSchedule.clear();badSchedule=false;payments=0;badAck=false;disabled=false;recoveryDisabled=false;terminalRecovery=false;QVERIFY(server.listen(dir.path()+"/owner"));
  QFile f(QFINDTESTDATA("purchase-quote.json"));QVERIFY(f.open(QIODevice::ReadOnly));quote=QJsonDocument::fromJson(f.readAll()).object();auto t=quote["terms"].toObject();context.buyer="buyer";context.caSha256=QString(64,'c');context.recipe=t["recipe_identity"].toObject();
  cap={{"schema",1},{"buyer",context.buyer},{"coordinator_ca_sha256",context.caSha256},{"recipe_identity",context.recipe},{"network",t["network"]},{"genesis",t["genesis"]},{"funding_protocol","private-testnet-work-deposit-v1"},{"quote_schema",3},{"maximum_units",2},{"automatic_dispatch",false},{"chain_checked",false},{"coins_sent",false}};
  connect(&server,&QLocalServer::newConnection,this,[this]{auto* s=server.nextPendingConnection();auto bytes=std::make_shared<QByteArray>();connect(s,&QLocalSocket::readyRead,this,[this,s,bytes]{*bytes+=s->readAll();if(!bytes->contains('\n'))return;auto frame=QJsonDocument::fromJson(*bytes).object();auto method=frame["method"].toString();actions<<method;auto p=frame["params"].toObject();QJsonObject result;
   if(method=="marketplace.capabilities"){result=cap;if(!recoveryDisabled)result["order_recovery_protocol"]="private-testnet-order-recovery-v1";result["refund_review_protocol"]="private-testnet-refund-review-v1";if(disabled)result["funding_protocol"]=QJsonValue();}
   else if(method=="marketplace.paidquote"){
    auto t=quote["terms"].toObject();t["quote_id"]=p["quote_id"];t["units"]=p["units"];t["parallelism"]=p["parallelism"];t["maximum_work_cost_base_units"]=101000*p["units"].toInt();t["issued_at"]=double(QDateTime::currentSecsSinceEpoch());t["accept_before"]=double(QDateTime::currentSecsSinceEpoch()+180);quote={{"terms",t},{"quote_sha256",QString::fromLatin1(QCryptographicHash::hash(QJsonDocument(t).toJson(QJsonDocument::Compact),QCryptographicHash::Sha256).toHex())}};result=quote;
   }else if(method=="marketplace.acceptquote")result={{"quote_id",p["quote_id"]},{"quote_sha256",badAck?QJsonValue(QString(64,'0')):p["reviewed_digest"]},{"accepted",true},{"funds_reserved",false},{"execution_enabled",false},{"payment_enabled",true}};
   else if(method=="marketplace.deposit")result={{"quote_id",p["quote_id"]},{"gpu_started",false},{"coins_sent",false}};
   else if(method=="marketplace.scheduleslotwork"){
    scheduleIds<<p["request_id"].toString();
    result={{"protocol",badSchedule?"legacy":"gpu-slots-v1"},{"historical_acknowledgement",true},{"quote_id",p["quote_id"]},{"request_id",p["request_id"]},{"provider_acceptance_required",true},{"gpu_started",false},{"payment_sent",false},{"assignments",QJsonArray{QJsonObject{{"assignment_id",QString(32,'a')},{"ordinal",0},{"provider","provider"},{"slot","gpu-1"},{"gpu_uuid","GPU-00000000-0000-0000-0000-000000000001"},{"terms_sha256",QString(64,'a')},{"deadline",double(QDateTime::currentSecsSinceEpoch()+100)}}}}};
   }else if(method=="marketplace.refundpreview"){
    auto t=quote["terms"].toObject();QJsonObject plan={{"quote_id",t["quote_id"]},{"quote_sha256",quote["quote_sha256"]},{"buyer",context.buyer},{"genesis",t["genesis"]},{"coordinator_ca_sha256",context.caSha256},{"deposit_txid",QString(64,'e')},{"deposit_vout",0},{"deposit_base_units",t["maximum_work_cost_base_units"]},{"receiving_script",t["payment_policy"].toObject()["receiving_script"]},{"refund_script","76a914"+QString(40,'b')+"88ac"},{"refund_base_units",t["maximum_work_cost_base_units"].toInt()-1000},{"fee_base_units",1000},{"minimum_confirmations",6}};
    preview={{"plan",plan},{"plan_sha256",QString::fromLatin1(QCryptographicHash::hash(QJsonDocument(plan).toJson(QJsonDocument::Compact),QCryptographicHash::Sha256).toHex())},{"cancelled",false},{"coins_sent",false}};result=preview;
   }else if(method=="marketplace.refundconfirm"){result=preview;result["cancelled"]=true;result["signing_performed"]=false;}
   else if(method=="marketplace.orderrecovery"){
    auto t=quote["terms"].toObject();QJsonArray us;for(int i=0;i<t["units"].toInt();++i)us.append(QJsonObject{{"ordinal",i},{"state","funded"},{"provider",QJsonValue()},{"receipt",QJsonValue()}});
    result={{"quote_id",p["quote_id"]},{"buyer",context.buyer},{"quote",quote},{"accepted",true},{"work_units",us},{"deposit",QJsonObject{{"txid",QString(64,'e')},{"vout",0},{"amount",t["maximum_work_cost_base_units"]},{"cancelled",0}}},{"payment",QJsonValue()},{"refund",QJsonValue()},{"ever_scheduled",false},{"enrolled_identity",QJsonObject{{"address","test-address"},{"proof_sha256",QString(64,'f')}}},{"live_chain_checked",false},{"refund_eligibility_checked",false},{"coins_sent",false}};
   }
   if(method=="marketplace.scheduleslotwork"&&!corruptSchedule.isEmpty()){
    if(corruptSchedule=="payment_sent")result["payment_sent"]=true;
    else {auto rows=result["assignments"].toArray();auto a=rows[0].toObject();a[corruptSchedule]="invalid";rows[0]=a;result["assignments"]=rows;}
   }
   if(method=="marketplace.orderrecovery"&&terminalRecovery){auto us=result["work_units"].toArray();for(int i=0;i<us.size();++i){auto u=us[i].toObject();u["state"]="refunded";us[i]=u;}result["work_units"]=us;result["refund"]=QJsonObject{{"digest",QString(64,'a')},{"txid",QString(64,'b')}};}
   s->write(QJsonDocument(QJsonObject{{"v",1},{"id",frame["id"]},{"ok",true},{"result",result}}).toJson(QJsonDocument::Compact)+"\n");s->flush();connect(s,&QLocalSocket::disconnected,s,&QObject::deleteLater);
  });});
  widget.reset(new WorkPurchaseWidget);widget->setDispatchDirectory(dir.path()+"/dispatch");widget->setPayment([this](const QJsonObject& q,const WorkFunding::Context& c,const WorkFunding::Review& r){++payments;WorkFunding::Review again;auto fresh=c;fresh.now=QDateTime::currentSecsSinceEpoch();if(!WorkFunding::validate(q,fresh,again).isEmpty()||again.digest!=r.digest)throw std::runtime_error("Invalid callback terms");return QJsonObject{{"submitted",true},{"txid",QString(64,'e')},{"vout",0}};});widget->setAgent(server.fullServerName(),true,context);
 }
 void cleanup(){widget.reset();server.close();server.disconnect(this);QLocalServer::removeServer(dir.path()+"/owner");}
 void funding_path_and_check_never_resends(){
  click("paidQuote");QTRY_VERIFY(widget->findChild<QPushButton*>("paidFund")->isEnabled());
  QTimer::singleShot(0,[]{for(auto* w:QApplication::topLevelWidgets())if(auto* d=dynamic_cast<WorkFundingDialog*>(w))d->findChild<QPushButton*>("workDepositContinue")->click();});click("paidFund");
  QTRY_COMPARE(payments,1);QVERIFY(!widget->findChild<QPushButton*>("paidFund")->isEnabled());click("paidCheck");QTRY_COMPARE(actions.count("marketplace.deposit"),1);QTRY_VERIFY(widget->findChild<QPushButton*>("paidCheck")->isEnabled());click("paidCheck");QTRY_COMPARE(actions.count("marketplace.deposit"),2);QCOMPARE(payments,1);QCOMPARE(actions.count("marketplace.acceptquote"),1);QCOMPARE(actions.count("marketplace.capabilities"),2);QCOMPARE(actions.count("marketplace.paidquote"),1);
 }
 void invalid_slot_acknowledgement_data(){QTest::addColumn<QString>("field");for(const auto& field:{"slot","gpu_uuid","terms_sha256","payment_sent"})QTest::newRow(field)<<QString(field);}
 void invalid_slot_acknowledgement(){
  QFETCH(QString,field);funding_path_and_check_never_resends();corruptSchedule=field;click("paidSchedule");
  QTRY_VERIFY(widget->findChild<QPlainTextEdit*>("paidDetails")->toPlainText().contains("Scheduling acknowledgment uncertain"));
  QCOMPARE(payments,1);QCOMPARE(scheduleIds.size(),1);
 }
 void slot_scheduling_uses_retained_id_after_uncertain_reply(){
  funding_path_and_check_never_resends();
  badSchedule=true;click("paidSchedule");
  QTRY_VERIFY(widget->findChild<QPlainTextEdit*>("paidDetails")->toPlainText().contains("Scheduling acknowledgment uncertain"));
  QCOMPARE(scheduleIds.size(),1);QCOMPARE(actions.count("marketplace.schedulework"),0);
  badSchedule=false;click("paidCheck");QTRY_VERIFY(widget->findChild<QPushButton*>("paidSchedule")->isEnabled());click("paidSchedule");
  QTRY_VERIFY(widget->findChild<QPlainTextEdit*>("paidDetails")->toPlainText().contains("Scheduling recorded"));
  QCOMPARE(scheduleIds.size(),2);QCOMPARE(scheduleIds[0],scheduleIds[1]);QCOMPARE(payments,1);
  QVERIFY(!widget->findChild<QPushButton*>("paidSchedule")->isEnabled());
 }
 void deposit_stays_bound_to_original_agent(){
  click("paidQuote");QTRY_VERIFY(widget->findChild<QPushButton*>("paidFund")->isEnabled());
  QTimer::singleShot(0,[]{for(auto* w:QApplication::topLevelWidgets())if(auto* d=dynamic_cast<WorkFundingDialog*>(w))d->findChild<QPushButton*>("workDepositContinue")->click();});click("paidFund");QTRY_COMPARE(payments,1);
  QTRY_VERIFY(widget->findChild<QPushButton*>("paidCheck")->isEnabled());
  auto altered=context;altered.caSha256=QString(64,'d');widget->setAgent(server.fullServerName(),true,altered);
  QVERIFY(!widget->findChild<QPushButton*>("paidCheck")->isEnabled());QCOMPARE(actions.count("marketplace.deposit"),0);
  widget->setAgent(server.fullServerName(),true,context);QVERIFY(widget->findChild<QPushButton*>("paidCheck")->isEnabled());
  widget->setAgent(server.fullServerName()+"-different",true,context);QVERIFY(!widget->findChild<QPushButton*>("paidCheck")->isEnabled());
  widget->setAgent(server.fullServerName(),false,{});QVERIFY(!widget->findChild<QPushButton*>("paidCheck")->isEnabled());
  widget->setAgent(server.fullServerName(),true,context);click("paidCheck");QTRY_COMPARE(actions.count("marketplace.deposit"),1);QCOMPARE(payments,1);
 }
 void selected_saved_order_reads_without_payment(){
  click("paidQuote");QTRY_VERIFY(widget->findChild<QPushButton*>("paidFund")->isEnabled());auto t=quote["terms"].toObject();
  QJsonObject saved={{"quote_id",t["quote_id"]},{"quote_sha256",quote["quote_sha256"]},{"receiving_script",t["payment_policy"].toObject()["receiving_script"]},{"amount_base_units",t["maximum_work_cost_base_units"]},{"txid",QString(64,'e')}};
  widget->setSavedSelector([saved]{return saved;});click("paidHistory");QTRY_VERIFY(widget->findChild<QPlainTextEdit*>("paidDetails")->toPlainText().contains("Recovered saved order"));QCOMPARE(actions.count("marketplace.orderrecovery"),1);QCOMPARE(payments,0);QVERIFY(!widget->findChild<QPushButton*>("paidFund")->isEnabled());QVERIFY(!widget->findChild<QPushButton*>("paidCheck")->isEnabled());
 }
 void refund_review_requires_explicit_confirmation(){
  selected_saved_order_reads_without_payment();
  widget->setRefundContext([this](const QJsonObject& r,const QJsonObject& j,const WorkFunding::Context& b){WorkRefund::Context c;c.buyer=b.buyer;c.ca=b.caSha256;c.quote=j["quote_id"].toString();c.quoteDigest=j["quote_sha256"].toString();c.txid=j["txid"].toString();c.receivingScript=j["receiving_script"].toString();c.vout=0;c.units=r["quote"].toObject()["terms"].toObject()["units"].toInt();c.address="test-address";c.refundScript="76a914"+QString(40,'b')+"88ac";return c;});
  QTimer timer;timer.setInterval(5);connect(&timer,&QTimer::timeout,[]{for(auto* w:QApplication::topLevelWidgets())if(auto* d=dynamic_cast<WorkRefundDialog*>(w))d->reject();});timer.start();click("paidRefund");QTRY_VERIFY(widget->findChild<QPlainTextEdit*>("paidDetails")->toPlainText().contains("Refund review cancelled"));timer.stop();QCOMPARE(actions.count("marketplace.refundconfirm"),0);
  timer.disconnect();connect(&timer,&QTimer::timeout,[]{for(auto* w:QApplication::topLevelWidgets())if(auto* d=dynamic_cast<WorkRefundDialog*>(w))d->findChild<QPushButton*>("refundConfirm")->click();});timer.start();click("paidRefund");QTRY_VERIFY(widget->findChild<QPlainTextEdit*>("paidDetails")->toPlainText().contains("Cancellation recorded"));timer.stop();QCOMPARE(actions.count("marketplace.refundconfirm"),1);QCOMPARE(payments,0);QVERIFY(!widget->findChild<QPushButton*>("paidRefund")->isEnabled());
 }
 void native_refund_validation_failure_blocks_confirmation(){selected_saved_order_reads_without_payment();widget->setRefundContext([](const QJsonObject&,const QJsonObject&,const WorkFunding::Context&)->WorkRefund::Context{throw std::runtime_error("Native address invalid");});click("paidRefund");QTRY_VERIFY(widget->findChild<QPlainTextEdit*>("paidDetails")->toPlainText().contains("Native wallet could not validate"));QCOMPARE(actions.count("marketplace.refundconfirm"),0);QCOMPARE(payments,0);}
 void unsupported_recovery_never_requests_order(){recoveryDisabled=true;widget->setSavedSelector([]{return QJsonObject{{"quote_id",QString(32,'a')}};});click("paidHistory");QTRY_VERIFY(widget->findChild<QPlainTextEdit*>("paidDetails")->toPlainText().contains("does not advertise supported order recovery"));QCOMPARE(actions.count("marketplace.orderrecovery"),0);QCOMPARE(actions.count("marketplace.paidquote"),0);QCOMPARE(payments,0);}
 void local_history_needs_no_agent_or_payment(){int opened=0;widget->setHistory([&]{++opened;});widget->setAgent(server.fullServerName(),false,{});click("paidHistory");QCOMPARE(opened,1);QCOMPARE(payments,0);QVERIFY(actions.isEmpty());}
 void wrong_acceptance_never_calls_wallet(){badAck=true;click("paidQuote");QTRY_VERIFY(widget->findChild<QPushButton*>("paidFund")->isEnabled());QTimer::singleShot(0,[]{for(auto* w:QApplication::topLevelWidgets())if(auto* d=dynamic_cast<WorkFundingDialog*>(w))d->findChild<QPushButton*>("workDepositContinue")->click();});click("paidFund");QTRY_VERIFY(widget->findChild<QPlainTextEdit*>("paidDetails")->toPlainText().contains("not confirmed"));QCOMPARE(payments,0);}
 void finished_recovery_allows_new_request_without_replay(){terminalRecovery=true;selected_saved_order_reads_without_payment();QVERIFY(widget->findChild<QPushButton*>("paidNewWork")->isEnabled());auto before=actions;click("paidNewWork");QCOMPARE(actions,before);QCOMPARE(payments,0);QVERIFY(!widget->findChild<QPushButton*>("paidNewWork")->isEnabled());click("paidQuote");QTRY_COMPARE(actions.count("marketplace.paidquote"),2);QTRY_VERIFY(widget->findChild<QPushButton*>("paidFund")->isEnabled());QCOMPARE(payments,0);}
 void unfinished_recovery_cannot_clear_deposit_guard(){selected_saved_order_reads_without_payment();QVERIFY(!widget->findChild<QPushButton*>("paidNewWork")->isEnabled());QCOMPARE(payments,0);}
 void funding_rechecks_support_without_replacing_quote(){
  click("paidQuote");QTRY_VERIFY(widget->findChild<QPushButton*>("paidFund")->isEnabled());auto original=quote;disabled=true;
  QTimer::singleShot(0,[]{for(auto* w:QApplication::topLevelWidgets())if(auto* d=dynamic_cast<WorkFundingDialog*>(w))d->findChild<QPushButton*>("workDepositContinue")->click();});click("paidFund");
  QTRY_VERIFY(widget->findChild<QPlainTextEdit*>("paidDetails")->toPlainText().contains("funding support changed"));QCOMPARE(actions.count("marketplace.capabilities"),2);QCOMPARE(actions.count("marketplace.paidquote"),1);QCOMPARE(actions.count("marketplace.acceptquote"),0);QCOMPARE(quote,original);QCOMPARE(payments,0);
 }
 void unsupported_coordinator_never_requests_paid_quote(){disabled=true;click("paidQuote");QTRY_COMPARE(actions.size(),1);QVERIFY(!widget->findChild<QPushButton*>("paidFund")->isEnabled());QCOMPARE(payments,0);}
 void reconnect_updates_status_without_payment(){
  widget->setAgent(server.fullServerName(),false,{});
  QVERIFY(widget->findChild<QLabel*>("paidStatus")->text().contains("Setup"));
  widget->setAgent(server.fullServerName(),true,context);
  QVERIFY(widget->findChild<QLabel*>("paidStatus")->text().startsWith("Connected."));
  QVERIFY(widget->findChild<QPushButton*>("paidQuote")->isEnabled());QCOMPARE(payments,0);
 }
 void automatic_workflow_default_is_off(){auto* c=widget->findChild<QCheckBox*>("paidAutomaticWorkflow");QVERIFY(c);QVERIFY(!c->isChecked());QVERIFY(!c->isVisible());}
 void automatic_workflow_requires_installed_controller(){widget->setWorkflowDirectory(dir.path()+"/missing-controller");auto* c=widget->findChild<QCheckBox*>("paidAutomaticWorkflow");QVERIFY(!c->isVisible());QVERIFY(!c->isChecked());}
 void automatic_workflow_receives_exact_wallet_binding(){
  QTemporaryDir helper;QFile f(helper.path()+"/control.py");QVERIFY(f.open(QIODevice::WriteOnly));
  f.write("import sys,json\nr=json.load(sys.stdin)\nassert r['slot']=='gpu-1' and r['maximum_base_units']==101000 and r['automatic_settlement'] is True\nprint(json.dumps(dict(quote=r['quote'],retained=True,started=True,automatic_retry=False)))\n");f.close();
  widget->setWorkflowDirectory(helper.path());auto* c=widget->findChild<QCheckBox*>("paidAutomaticWorkflow");QVERIFY(!c->isChecked());c->setChecked(true);
  funding_path_and_check_never_resends();click("paidSchedule");
  QTRY_VERIFY(widget->findChild<QPlainTextEdit*>("paidDetails")->toPlainText().contains("Automatic workflow requested"));QCOMPARE(payments,1);
 }
 void progress_refresh_is_read_only(){selected_saved_order_reads_without_payment();auto before=actions.size();click("paidRefresh");QTRY_COMPARE(actions.size(),before+1);QCOMPARE(actions.last(),QString("marketplace.orderrecovery"));QCOMPARE(payments,0);QVERIFY(scheduleIds.isEmpty());}
 void progress_timer_observes_without_execution(){selected_saved_order_reads_without_payment();auto* timer=widget->findChild<QTimer*>("rentalProgressTimer");QVERIFY(timer);QVERIFY(timer->isActive());int before=actions.size();QMetaObject::invokeMethod(timer,"timeout",Qt::DirectConnection);QTRY_COMPARE(actions.size(),before+1);QCOMPARE(actions.last(),QString("marketplace.orderrecovery"));QCOMPARE(payments,0);QVERIFY(scheduleIds.isEmpty());}
 void progress_stops_when_finished(){terminalRecovery=true;selected_saved_order_reads_without_payment();QVERIFY(!widget->findChild<QTimer*>("rentalProgressTimer")->isActive());QVERIFY(widget->findChild<QPushButton*>("paidRefresh")->isEnabled());}
 void progress_cannot_follow_changed_authority(){selected_saved_order_reads_without_payment();auto altered=context;altered.caSha256=QString(64,'d');widget->setAgent(server.fullServerName(),true,altered);QVERIFY(!widget->findChild<QTimer*>("rentalProgressTimer")->isActive());QVERIFY(!widget->findChild<QPushButton*>("paidRefresh")->isEnabled());int before=actions.size();QMetaObject::invokeMethod(widget->findChild<QTimer*>("rentalProgressTimer"),"timeout",Qt::DirectConnection);QTest::qWait(30);QCOMPARE(actions.size(),before);QCOMPARE(payments,0);}
 void disconnect_clears_review(){click("paidQuote");QTRY_VERIFY(widget->findChild<QPushButton*>("paidFund")->isEnabled());widget->setAgent(server.fullServerName(),false,{});QVERIFY(!widget->findChild<QPushButton*>("paidFund")->isEnabled());QCOMPARE(payments,0);}
};
QTEST_MAIN(PurchaseTest)
#include "purchase_test.moc"
