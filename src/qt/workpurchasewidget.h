#ifndef YERBAS_QT_WORKPURCHASEWIDGET_H
#define YERBAS_QT_WORKPURCHASEWIDGET_H
#include "workfundingsession.h"
#include "workdispatchjournal.h"
#include <QStandardPaths>
#include <QSet>
#include "workfundingdialog.h"
#include "workorderrecovery.h"
#include "workrefunddialog.h"
#include <QLocalSocket>
#include <QSpinBox>
#include <QPlainTextEdit>
#include <QHBoxLayout>
#include <QUuid>
#include <QCheckBox>
#include <QFileInfo>
#include <QProcess>
#ifdef Q_OS_LINUX
#include <sys/socket.h>
#include <unistd.h>
#endif
#include <memory>

// Buyer protocol UI. Keys and WalletModel remain in WalletView's callback.
class WorkPurchaseWidget:public QWidget {
public:
 using RefundContext=std::function<WorkRefund::Context(const QJsonObject&,const QJsonObject&,const WorkFunding::Context&)>;
 using Pay=std::function<QJsonObject(const QJsonObject&,const WorkFunding::Context&,const WorkFunding::Review&)>;
 std::function<void(bool)> capabilityChanged;
private:
 QCheckBox* automaticWorkflow;QProcess workflowProcess;QByteArray workflowReply;QJsonObject workflowRequest;
 QString workflowDirectory=QCoreApplication::applicationDirPath()+"/wallet-workflow";
 void startWorkflow(const QJsonArray& rows){
  if(!automaticWorkflow->isChecked())return;
  auto terms=quote["terms"].toObject();
  if(rows.size()!=1||context.units!=1||context.parallelism!=1||rows[0].toObject()["slot"]!=QJsonValue("gpu-1")||terms["maximum_work_cost_base_units"]!=QJsonValue(101000)||terms["network"]!=QJsonValue("yerbas-private-reduced-collateral-testnet")){
   details->appendPlainText(tr("Automatic workflow supports one enrolled testnet GPU1 unit. The assignment is retained for review; no automatic execution requested."));return;
  }
  auto a=rows[0].toObject();workflowRequest={{"schema",1},{"network",terms["network"]},{"quote",quoteId},{"assignment",a["assignment_id"]},{"terms_sha256",a["terms_sha256"]},{"deposit_txid",deposit["txid"]},{"deposit_vout",deposit["vout"]},{"maximum_base_units",101000},{"provider_reward_base_units",100000},{"slot","gpu-1"},{"automatic_settlement",true}};
  workflowReply.clear();workflowProcess.setProgram("/usr/bin/python3");workflowProcess.setArguments({"-I","-B",workflowDirectory+"/control.py"});workflowProcess.start();
 }
 QPushButton* schedule;bool depositConfirmed=false;QString scheduleId;QString dispatchDirectory=QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation)+"/yerbas-ai-dispatch";
 QTimer progressTimer;QPushButton* refresh;QString recoveryAgent;WorkFunding::Context recoveryContext;bool recoverySupported=false;
 bool sameRecoveryBinding()const{return path==recoveryAgent&&context.buyer==recoveryContext.buyer&&context.caSha256==recoveryContext.caSha256&&context.recipe==recoveryContext.recipe;}
 void refreshProgress(){if(ready&&request.isEmpty()&&!modal&&recoverySupported&&!recoveryJournal.isEmpty()&&sameRecoveryBinding())send("orderrecovery",{{"quote_id",recoveryJournal["quote_id"]}});}
 RefundContext refundContext;QPushButton* refund;QPushButton* newWork;QJsonObject recoveredOrder,refundPreview;WorkRefund::Context refundBinding;bool refundSupported=false;
 std::function<QJsonObject()> selectSaved;QJsonObject recoveryJournal;
 std::function<void()> history;QPushButton* saved;
 Pay pay;WorkFunding::Context context;std::unique_ptr<WorkFundingSession> session;
 QLocalSocket socket;QTimer deadline;QSpinBox *units,*parallel;QPushButton *get,*fund,*check;QLabel* heading;QPlainTextEdit* details;
 WorkFunding::Context depositContext;QString depositAgent;
 QString path,request,action,quoteId;QByteArray buffer;QJsonObject quote,deposit;WorkFunding::Review reviewed;
 bool ready=false,attempted=false,modal=false,recoverAfterNegotiation=false, fundAfterNegotiation=false;
 bool sameDepositBinding() const {return path==depositAgent&&context.buyer==depositContext.buyer&&context.caSha256==depositContext.caSha256&&context.recipe==depositContext.recipe;}
 bool recoveredFinished()const{
  auto rows=recoveredOrder["work_units"].toArray();if(rows.isEmpty())return false;
  bool refunded=true,verified=true;for(auto row:rows){auto state=row.toObject()["state"].toString();refunded&=state=="refunded";verified&=state=="verified";}
  return (refunded&&recoveredOrder["refund"].toObject()["txid"].isString())||(verified&&recoveredOrder["payment"].toObject()["txid"].isString());
 }
 void controls(){bool idle=request.isEmpty()&&!modal;bool supported=ready&&bool(session);automaticWorkflow->setEnabled(idle&&ready&&units->value()==1&&parallel->value()==1&&QFileInfo::exists(workflowDirectory+"/control.py"));refresh->setEnabled(idle&&ready&&recoverySupported&&!recoveryJournal.isEmpty()&&sameRecoveryBinding());schedule->setEnabled(idle&&ready&&depositConfirmed&&!deposit.isEmpty()&&deposit["quote_id"]==QJsonValue(quoteId)&&sameDepositBinding());newWork->setEnabled(idle&&ready&&recoveredFinished());refund->setEnabled(idle&&ready&&refundSupported&&session&&session->available(QDateTime::currentSecsSinceEpoch())&&!recoveredOrder.isEmpty()&&bool(refundContext)&&recoveredOrder["ever_scheduled"]==QJsonValue(false)&&recoveredOrder["payment"].isNull()&&recoveredOrder["refund"].isNull());get->setEnabled(idle&&ready);units->setEnabled(idle&&!attempted);parallel->setEnabled(idle&&!attempted);fund->setText(!reviewed.digest.isEmpty()&&reviewed.acceptBefore<=QDateTime::currentSecsSinceEpoch()?tr("Quote expired · request a new quote"):tr("Review and pay…"));fund->setEnabled(idle&&supported&&!attempted&&!reviewed.digest.isEmpty()&&reviewed.acceptBefore>QDateTime::currentSecsSinceEpoch()&&bool(pay));check->setEnabled(idle&&ready&&!deposit.isEmpty()&&sameDepositBinding());}
 void fail(const QString& message){progressTimer.stop();depositConfirmed=false;fundAfterNegotiation=false;recoverAfterNegotiation=false;recoveredOrder={};refundSupported=false;request.clear();deadline.stop();socket.abort();if(session)session->reset();reviewed={};details->setPlainText(message);controls();}
 void send(const QString& method,const QJsonObject& params){
  if(!request.isEmpty()||!ready)return;
  action=method;request=QUuid::createUuid().toString(QUuid::Id128);buffer.clear();socket.abort();
  pending=params;deadline.start(12000);controls();socket.connectToServer(path);
 }
 QJsonObject pending;
 void read(){
  buffer+=socket.readAll();if(buffer.size()>16384){fail(tr("Response too large. No automatic payment retry."));return;}if(!buffer.contains('\n'))return;
  auto doc=QJsonDocument::fromJson(buffer);auto frame=doc.object();
  if(!doc.isObject()||buffer.count('\n')!=1||!buffer.endsWith('\n')||frame["v"]!=QJsonValue(1)||frame["id"]!=request||frame["ok"]!=QJsonValue(true)||!frame["result"].isObject()){
   fail(deposit.isEmpty()?tr("Funding service unavailable. No automatic payment retry."):tr("Deposit acknowledgment failed. Confirmations, service availability, or deposit reconciliation may require attention. Check the original transaction; do not send a replacement."));return;
  }
  auto result=frame["result"].toObject();QString completed=action;request.clear();deadline.stop();socket.abort();auto now=QDateTime::currentSecsSinceEpoch();
  if(completed=="orderrecovery"){
   if(!sameRecoveryBinding()||!WorkOrderRecovery::validate(result,recoveryJournal,context,now).isEmpty()){fail(tr("Recovered order does not match the saved wallet deposit. No payment or refund requested."));return;}
   recoveredOrder=result;QStringList lines;lines<<tr("Recovered saved order: %1").arg(result["quote_id"].toString())<<tr("Original deposit: %1").arg(recoveryJournal["txid"].toString())<<tr("Saved coordinator records; live confirmations and refund eligibility have not been checked.");
   for(auto v:result["work_units"].toArray()){auto u=v.toObject();lines<<tr("Work unit %1: %2").arg(u["ordinal"].toInt()+1).arg(u["state"].toString());}
   for(auto key:{"payment","refund"})if(result[key].isObject())lines<<QString::fromLatin1(key)+": "+result[key].toObject()["txid"].toString();
   lines<<tr("No replacement deposit, signing, or refund request was performed.");details->setPlainText(lines.join("\n"));
   if(recoveredFinished())progressTimer.stop();else progressTimer.start();
  }else if(completed=="refundpreview"){
   try{refundBinding=refundContext(recoveredOrder,recoveryJournal,context);}catch(const std::exception&){fail(tr("Native wallet could not validate the original deposit or enrolled refund address."));return;}
   if(!WorkRefund::validate(result,refundBinding).isEmpty()){fail(tr("Refund preview differs from the saved deposit or enrolled address."));return;}
   refundPreview=result;modal=true;controls();WorkRefundDialog dialog(result,refundBinding,this);dialog.exec();auto digest=dialog.reviewedDigest();modal=false;
   if(!digest.isEmpty()){send("refundconfirm",{{"quote_id",refundBinding.quote},{"fee_base_units",result["plan"].toObject()["fee_base_units"]},{"reviewed_digest",digest}});return;}
   details->setPlainText(tr("Refund review cancelled. No cancellation request or coins sent."));
  }else if(completed=="refundconfirm"){
   if(!WorkFunding::keys(result,{"plan","plan_sha256","cancelled","coins_sent","signing_performed"})||result["plan"]!=refundPreview["plan"]||result["plan_sha256"]!=refundPreview["plan_sha256"]||result["cancelled"]!=QJsonValue(true)||result["coins_sent"]!=QJsonValue(false)||result["signing_performed"]!=QJsonValue(false)){fail(tr("Refund acknowledgment uncertain. Recover the original order; do not send a replacement deposit."));return;}
   recoveredOrder={};details->setPlainText(tr("Cancellation recorded; the reviewed refund is pending operator payment. No coins were signed or sent by this request."));
  }else if(completed=="capabilities"){
   refundSupported=result["refund_review_protocol"]==QJsonValue("private-testnet-refund-review-v1");
   recoverySupported=result["order_recovery_protocol"]==QJsonValue("private-testnet-order-recovery-v1");
   auto base=result;base.remove("order_recovery_protocol");base.remove("refund_review_protocol");
   bool supported=session->negotiate(base,now);
   if(recoverAfterNegotiation){recoverAfterNegotiation=false;if(!supported||!recoverySupported){fail(tr("Saved deposit retained. This coordinator does not advertise supported order recovery. No coins sent."));return;}send("orderrecovery",{{"quote_id",recoveryJournal["quote_id"]}});return;}
   if(fundAfterNegotiation){fundAfterNegotiation=false;
    WorkFunding::Review fresh;auto expected=context;expected.now=now;
    if(!supported||!WorkFunding::validate(quote,expected,fresh).isEmpty()||fresh.digest!=reviewed.digest||!session->quote(quote,quoteId,context.units,context.parallelism,now)){fail(tr("The reviewed quote expired or funding support changed. No coins sent. Request a fresh quote."));return;}
    send("acceptquote",{{"quote_id",quoteId},{"reviewed_digest",reviewed.digest}});return;
   }
   if(capabilityChanged)capabilityChanged(supported);
   heading->setText(supported?tr("Pay per verified AI work unit · Private testnet"):tr("Wallet funding unavailable on this coordinator"));
   if(supported){quoteId=QUuid::createUuid().toString(QUuid::Id128);context.quoteId=quoteId;context.units=units->value();context.parallelism=parallel->value();context.now=now;attempted=false;quote={};deposit={};reviewed={};send("paidquote",{{"quote_id",quoteId},{"units",context.units},{"parallelism",context.parallelism}});return;}
   details->setPlainText(tr("Planning remains available. This coordinator does not advertise the supported wallet funding protocol."));
  }else if(completed=="paidquote"){
   if(result.value("status")==QJsonValue("deposit_addresses_unavailable")){
    if(!WorkFunding::keys(result,{"schema","quote_id","status","coins_sent","gpu_started"})||result["schema"]!=QJsonValue(1)||result["quote_id"]!=quoteId||result["coins_sent"]!=QJsonValue(false)||result["gpu_started"]!=QJsonValue(false)){fail(tr("Invalid funding availability response. No coins sent."));return;}
    fail(tr("New work quotes are temporarily unavailable: the coordinator needs fresh deposit addresses. No coins were sent. Contact the operator, then request a new quote."));return;
   }
   context.now=now;
   if(!session->quote(result,quoteId,context.units,context.parallelism,now)||!WorkFunding::validate(result,context,reviewed).isEmpty()){fail(tr("Quote did not match your request or trusted coordinator binding."));return;}
   quote=result;details->setPlainText(tr("%1 approved work units, up to %2 in parallel.\nDeposit: %3 tYERB, including settlement fees. Your wallet transaction fee is additional.\n\nThe operator holds the deposit. Review custody and cancellation terms before funding.\nQuote: %4").arg(context.units).arg(context.parallelism).arg(QString::number(reviewed.amount/1e8,'f',8),quoteId));
  }else if(completed=="acceptquote"){
   if(result["quote_id"]!=quoteId||result["quote_sha256"]!=reviewed.digest||result["accepted"]!=QJsonValue(true)||result["funds_reserved"]!=QJsonValue(false)||result["payment_enabled"]!=QJsonValue(true)||result["execution_enabled"]!=QJsonValue(false)||!session->acknowledge(quoteId,reviewed.digest,now)){
    fail(tr("Exact quote acceptance was not confirmed. No coins sent."));return;
   }
   attempted=true;modal=true;controls();QJsonObject sent;
   try{sent=pay(session->acceptedQuote(now),context,reviewed);}catch(const std::exception&){sent={{"error",true}};}
   modal=false;
   if(sent["submitted"]!=QJsonValue(true)||!QRegularExpression("^[a-f0-9]{64}$").match(sent["txid"].toString()).hasMatch()||!WorkFunding::integer(sent["vout"],0,65535)){
    if(sent["cancelled"]==QJsonValue(true))attempted=false;
    details->setPlainText(sent["cancelled"]==QJsonValue(true)?tr("Wallet payment cancelled. No automatic retry."):tr("Payment outcome requires wallet reconciliation. Do not send a replacement deposit. The wallet retains any send intent."));controls();return;
   }
   depositContext=context;depositAgent=path;recoveryAgent=path;recoveryContext=context;
   const auto terms=quote["terms"].toObject();recoveryJournal={{"quote_id",quoteId},{"quote_sha256",reviewed.digest},{"receiving_script",terms["payment_policy"].toObject()["receiving_script"]},{"amount_base_units",terms["maximum_work_cost_base_units"]},{"txid",sent["txid"]}};
   deposit={{"quote_id",quoteId},{"reviewed_digest",reviewed.digest},{"txid",sent["txid"]},{"vout",sent["vout"]}};
   details->setPlainText(tr("Deposit submitted: %1\nWait for six confirmations, then check this deposit. No replacement transaction will be created by Check deposit.").arg(sent["txid"].toString()));
  }else if(completed=="deposit"){
   if(result["quote_id"]!=quoteId||result["gpu_started"]!=QJsonValue(false)||result["coins_sent"]!=QJsonValue(false)){fail(tr("Unexpected deposit acknowledgment; reconcile original transaction."));return;}
   depositConfirmed=true;
   details->setPlainText(tr("Deposit confirmed and bound to this work request. GPU dispatch has not started.\nWork request: %1\nDeposit: %2").arg(quoteId,deposit["txid"].toString()));
  }else if(completed=="scheduleslotwork"){
   bool valid=result["protocol"]==QJsonValue("gpu-slots-v1")&&result["historical_acknowledgement"]==QJsonValue(true)&&result["quote_id"]==quoteId&&result["request_id"]==scheduleId&&result["provider_acceptance_required"]==QJsonValue(true)&&result["gpu_started"]==QJsonValue(false)&&result["payment_sent"]==QJsonValue(false)&&result["assignments"].isArray();
   QSet<QString> ids;QSet<int> ordinals;QStringList lines;const auto rows=result["assignments"].toArray();valid&=rows.size()<=context.units;
   for(auto row:rows){auto a=row.toObject();auto id=a["assignment_id"].toString();int ordinal=a["ordinal"].toInt(-1);
    valid&=QRegularExpression("^[a-f0-9]{32}$").match(id).hasMatch()&&!ids.contains(id)&&!ordinals.contains(ordinal)&&WorkFunding::integer(a["ordinal"],0,context.units-1)&&!a["provider"].toString().isEmpty()&&WorkFunding::integer(a["deadline"],1,9007199254740991.0);
    valid&=QRegularExpression("^gpu-[0-9]{1,2}$").match(a["slot"].toString()).hasMatch()&&QRegularExpression("^GPU-[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$").match(a["gpu_uuid"].toString()).hasMatch()&&QRegularExpression("^[a-f0-9]{64}$").match(a["terms_sha256"].toString()).hasMatch();
    ids.insert(id);ordinals.insert(ordinal);lines<<tr("Work unit %1: assignment recorded for %2.").arg(ordinal+1).arg(a["provider"].toString());
   }
   if(!valid){fail(tr("Scheduling acknowledgment uncertain. Check the original deposit before retrying; the saved scheduling ID will be reused."));return;}
   depositConfirmed=false;if(recoverySupported)progressTimer.start();
   details->setPlainText(tr("Scheduling recorded. Providers must accept before execution. This acknowledgment is not live job status. No additional coins sent.\n")+lines.join("\n")+(rows.isEmpty()?tr("No GPU assignments were returned. Recover this order before another scheduling attempt."):QString()));
   startWorkflow(rows);
  }
  controls();
 }
public:
 explicit WorkPurchaseWidget(QWidget* parent=nullptr):QWidget(parent){
  automaticWorkflow=new QCheckBox(tr("Automatically run, verify and pay this testnet work unit"),this);automaticWorkflow->setObjectName("paidAutomaticWorkflow");automaticWorkflow->setChecked(false);
  automaticWorkflow->setVisible(QFileInfo::exists(workflowDirectory+"/control.py"));
  connect(&workflowProcess,&QProcess::started,this,[this]{workflowProcess.write(QJsonDocument(workflowRequest).toJson(QJsonDocument::Compact));workflowProcess.closeWriteChannel();});
  connect(&workflowProcess,&QProcess::readyReadStandardOutput,this,[this]{auto b=workflowProcess.readAllStandardOutput();if(workflowReply.size()<=16384)workflowReply+=b;});
  connect(&workflowProcess,&QProcess::readyReadStandardError,this,[this]{workflowProcess.readAllStandardError();});
  connect(&workflowProcess,qOverload<int,QProcess::ExitStatus>(&QProcess::finished),this,[this](int code,QProcess::ExitStatus status){
   auto r=QJsonDocument::fromJson(workflowReply).object();
   if(code||status!=QProcess::NormalExit||workflowReply.size()>16384||r["quote"]!=workflowRequest["quote"]||r["retained"]!=QJsonValue(true)||r["automatic_retry"]!=QJsonValue(false))details->appendPlainText(tr("Workflow acknowledgment uncertain. Keep the original deposit; no automatic launch or payment retry."));
   else details->appendPlainText(r["started"]==QJsonValue(true)?tr("Automatic workflow requested. Follow rental progress for verification and payment; closing the wallet does not cancel accepted work."):tr("This workflow was already requested. Existing records were preserved; no second worker started."));
  });
  connect(&workflowProcess,&QProcess::errorOccurred,this,[this](QProcess::ProcessError e){if(e==QProcess::FailedToStart)details->appendPlainText(tr("Workflow service unavailable. The original deposit and assignment are retained."));});
  refresh=new QPushButton(tr("Refresh rental progress"),this);refresh->setObjectName("paidRefresh");connect(refresh,&QPushButton::clicked,this,[this]{refreshProgress();});
  progressTimer.setObjectName("rentalProgressTimer");progressTimer.setParent(this);progressTimer.setInterval(15000);connect(&progressTimer,&QTimer::timeout,this,[this]{refreshProgress();});
  schedule=new QPushButton(tr("Schedule funded work"),this);schedule->setObjectName("paidSchedule");
  auto* box=new QVBoxLayout(this);box->setContentsMargins(0,0,0,0);heading=new QLabel(tr("Wallet funding · Connect the owner agent"),this);heading->setObjectName("paidStatus");box->addWidget(heading);
  box->addWidget(automaticWorkflow);
  auto* row=new QHBoxLayout;units=new QSpinBox(this);units->setRange(1,2);units->setPrefix(tr("Work units: "));units->setObjectName("paidUnits");parallel=new QSpinBox(this);parallel->setRange(1,2);parallel->setPrefix(tr("Parallel units: "));parallel->setObjectName("paidParallel");get=new QPushButton(tr("Check price"),this);get->setObjectName("paidQuote");fund=new QPushButton(tr("Review and pay…"),this);fund->setObjectName("paidFund");check=new QPushButton(tr("Check deposit"),this);check->setObjectName("paidCheck");for(auto* w:QList<QWidget*>{units,parallel,get,fund,check})row->addWidget(w);box->addLayout(row);box->addWidget(schedule);box->addWidget(refresh);connect(schedule,&QPushButton::clicked,this,[this]{if(!schedule->isEnabled())return;try{scheduleId=WorkDispatch::intent(dispatchDirectory,{{"buyer",context.buyer},{"ca_sha256",context.caSha256},{"quote_id",quoteId},{"quote_sha256",deposit["reviewed_digest"]},{"deposit",deposit}});}catch(const std::exception&){fail(tr("Scheduling intent could not be saved. No scheduling request sent."));return;}send("scheduleslotwork",{{"quote_id",quoteId},{"request_id",scheduleId}});});saved=new QPushButton(tr("Saved deposits…"),this);saved->setObjectName("paidHistory");saved->setEnabled(false);box->addWidget(saved);connect(saved,&QPushButton::clicked,this,[this]{if(selectSaved){auto selected=selectSaved();if(selected.isEmpty())return;if(!ready){details->setPlainText(tr("Connect the enrolled owner agent to recover this saved order. No coins sent."));return;}if(!request.isEmpty()||modal)return;depositConfirmed=false;scheduleId.clear();recoveredOrder={};refundSupported=false;progressTimer.stop();recoveryAgent=path;recoveryContext=context;recoveryJournal=selected;deposit={};attempted=true;reviewed={};recoverAfterNegotiation=true;send("capabilities",{});}else if(history)history();});
  refund=new QPushButton(tr("Review cancellation and refund…"),this);refund->setObjectName("paidRefund");box->addWidget(refund);connect(refund,&QPushButton::clicked,this,[this]{if(!refund->isEnabled())return;send("refundpreview",{{"quote_id",recoveryJournal["quote_id"]},{"fee_base_units",1000}});});
  newWork=new QPushButton(tr("New work request"),this);newWork->setObjectName("paidNewWork");box->addWidget(newWork);connect(newWork,&QPushButton::clicked,this,[this]{if(!newWork->isEnabled())return;progressTimer.stop();depositConfirmed=false;recoveredOrder={};recoveryJournal={};refundPreview={};refundSupported=false;quote={};deposit={};reviewed={};attempted=false;quoteId.clear();if(session)session->reset();details->setPlainText(tr("Ready for a separate work request. Previous deposit records remain in Saved deposits. No payment was retried or sent."));controls();});
  details=new QPlainTextEdit(this);details->setObjectName("paidDetails");details->setReadOnly(true);details->setMaximumHeight(180);box->addWidget(details);
  deadline.setSingleShot(true);connect(&deadline,&QTimer::timeout,this,[this]{fail(tr("Request timed out. Reconcile the existing order before retrying; no automatic payment retry."));});
  connect(&socket,&QLocalSocket::errorOccurred,this,[this](QLocalSocket::LocalSocketError){if(!request.isEmpty())fail(tr("Owner agent unavailable. No automatic payment retry."));});
  connect(&socket,&QLocalSocket::connected,this,[this]{
#ifdef Q_OS_LINUX
  struct ucred peer;socklen_t n=sizeof(peer);if(::getsockopt(socket.socketDescriptor(),SOL_SOCKET,SO_PEERCRED,&peer,&n)||peer.uid!=::geteuid()){fail(tr("Owner agent authentication failed."));return;}socket.write(QJsonDocument(QJsonObject{{"v",1},{"id",request},{"method","marketplace."+action},{"params",pending}}).toJson(QJsonDocument::Compact)+"\n");
#else
  fail(tr("Owner agent connections are supported only on Linux."));
#endif
  });
  connect(&socket,&QLocalSocket::readyRead,this,[this]{read();});
  connect(get,&QPushButton::clicked,this,[this]{if(parallel->value()>units->value())return;if(attempted){details->setPlainText(tr("An existing deposit attempt must be reconciled before a new work request. Check the wallet transaction and retained deposit journal."));return;}send("capabilities",{});});
  connect(fund,&QPushButton::clicked,this,[this]{if(!fund->isEnabled())return;modal=true;controls();WorkFundingDialog dialog(quote,context,this);auto accepted=dialog.exec()==QDialog::Accepted&&dialog.reviewedTerms(reviewed);modal=false;if(accepted){fundAfterNegotiation=true;send("capabilities",{});}else controls();});
  connect(check,&QPushButton::clicked,this,[this]{if(sameDepositBinding())send("deposit",deposit);});
  auto changed=[this]{reviewed={};if(session)session->reset();controls();};connect(units,qOverload<int>(&QSpinBox::valueChanged),this,changed);connect(parallel,qOverload<int>(&QSpinBox::valueChanged),this,changed);
  auto* clock=new QTimer(this);clock->setInterval(500);connect(clock,&QTimer::timeout,this,[this]{controls();});clock->start();controls();
 }
 void setDispatchDirectory(const QString& directory){dispatchDirectory=directory;}
 void setWorkflowDirectory(const QString& directory){workflowDirectory=directory;automaticWorkflow->setChecked(false);automaticWorkflow->setVisible(QFileInfo::exists(directory+"/control.py"));}
 void setRefundContext(RefundContext callback){refundContext=std::move(callback);controls();}
 void setSavedSelector(std::function<QJsonObject()> callback){selectSaved=std::move(callback);saved->setEnabled(bool(selectSaved)||bool(history));}
 void setHistory(std::function<void()> callback){history=std::move(callback);saved->setEnabled(bool(history));}
 void setPayment(Pay callback){pay=std::move(callback);controls();}
 void setAgent(const QString& agent,bool enabled,const WorkFunding::Context& binding){
  if(modal)return;
  const bool wasReady=ready;
  bool changed=agent!=path||binding.buyer!=context.buyer||binding.caSha256!=context.caSha256||binding.recipe!=context.recipe;
  if(changed||!enabled){progressTimer.stop();recoverySupported=false;depositConfirmed=false;fundAfterNegotiation=false;recoveredOrder={};refundSupported=false;recoverAfterNegotiation=false;request.clear();deadline.stop();socket.abort();if(session)session->reset();reviewed={};}
  path=agent;ready=enabled&&!binding.buyer.isEmpty();context.buyer=binding.buyer;context.caSha256=binding.caSha256;context.recipe=binding.recipe;
  if(!session||changed||!ready)session.reset(new WorkFundingSession(context));
  if(!ready)heading->setText(tr("Connect your owner agent in Setup to check prices and pay."));
  else if(!wasReady||changed)heading->setText(tr("Connected. Check the price before reviewing a payment."));
  controls();
 }
};
#endif
