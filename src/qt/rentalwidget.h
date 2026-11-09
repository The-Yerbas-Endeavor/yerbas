#ifndef YERBAS_QT_RENTALWIDGET_H
#define YERBAS_QT_RENTALWIDGET_H
#include "offerwidget.h"
#include <QSpinBox>
#include <QLabel>
#include <QJsonArray>
#include <cmath>

// Buyer planning controls only; never signs, funds or dispatches a GPU job.
class RentalWidget : public QWidget {
public:
 explicit RentalWidget(QWidget* parent=nullptr):QWidget(parent){
  setSizePolicy(QSizePolicy::Preferred,QSizePolicy::Maximum);auto* box=new QVBoxLayout(this);box->setContentsMargins(0,0,0,0);box->setSpacing(12);box->setAlignment(Qt::AlignTop);
  box->addWidget(new QLabel(tr("Request AI work · Wallet funding is not enabled yet."),this));
  auto* row=new QHBoxLayout;
  id=new QLineEdit(this);id->setObjectName("rentalId");id->setMaxLength(32);id->setPlaceholderText(tr("Order ID"));
  units=new QSpinBox(this);units->setObjectName("rentalUnits");units->setRange(1,64);units->setPrefix(tr("Work units: "));
  parallel=new QSpinBox(this);parallel->setObjectName("rentalParallel");parallel->setRange(1,8);parallel->setPrefix(tr("Parallel work units: "));
  auto* fresh=new QPushButton(tr("New work request"),this);row->addWidget(id);id->hide();row->addWidget(fresh);row->addWidget(units);row->addWidget(parallel);box->addLayout(row);
  row=new QHBoxLayout;
  review=button(row,"rentalReview",tr("Get quote"),"quote");
  accept=button(row,"rentalAccept",tr("Accept quote"),"acceptquote");
  status=button(row,"rentalStatus",tr("Refresh"),"order");
  pool=button(row,"rentalPool",tr("Available GPUs"),"pool");
  withdraw=button(row,"rentalWithdraw",tr("Withdraw"),"withdraw");box->addLayout(row);
  row=new QHBoxLayout;refund=button(row,"rentalRefundStatus",tr("Refund status"),"refundstatus");box->addLayout(row);
  details=new QPlainTextEdit(this);details->setObjectName("rentalDetails");details->setReadOnly(true);details->setMaximumHeight(170);box->addWidget(details);
  details->setMinimumHeight(160);details->setPlainText(tr("Connect the owner agent to check marketplace availability.\n\nPay per verified approved work unit. Available providers perform your work; you do not rent a particular GPU. Multiple independent units can run in parallel. GPU memory is not combined."));
  auto* advanced=new QPushButton(tr("Order ID and technical details"),this);advanced->setCheckable(true);box->addWidget(advanced,0,Qt::AlignLeft);
  raw=new QPlainTextEdit(this);raw->setObjectName("rentalRaw");raw->setReadOnly(true);raw->setMaximumHeight(220);raw->hide();box->addWidget(raw);
  connect(advanced,&QPushButton::toggled,raw,&QWidget::setVisible);
  connect(advanced,&QPushButton::toggled,id,&QWidget::setVisible);
  accept->setProperty("variant","primary");withdraw->setProperty("variant","danger");
  socket=new QLocalSocket(this);timer=new QTimer(this);timer->setSingleShot(true);
  connect(fresh,&QPushButton::clicked,this,[this]{if(request.isEmpty())id->setText(QUuid::createUuid().toString(QUuid::Id128));});
  connect(id,&QLineEdit::textChanged,this,[this]{invalidate();});
  connect(units,qOverload<int>(&QSpinBox::valueChanged),this,[this]{invalidate();});
  connect(parallel,qOverload<int>(&QSpinBox::valueChanged),this,[this]{invalidate();});
  connect(timer,&QTimer::timeout,this,[this]{fail();});
  connect(socket,&QLocalSocket::errorOccurred,this,[this](QLocalSocket::LocalSocketError){if(!request.isEmpty())fail();});
  connect(socket,&QLocalSocket::connected,this,[this]{
#ifdef Q_OS_LINUX
   struct ucred peer;socklen_t n=sizeof(peer);
   if(::getsockopt(socket->socketDescriptor(),SOL_SOCKET,SO_PEERCRED,&peer,&n)||peer.uid!=::geteuid()){fail();return;}
   socket->write(QJsonDocument(QJsonObject{{"v",1},{"id",request},{"method","marketplace."+action},{"params",params}}).toJson(QJsonDocument::Compact)+"\n");
#else
   fail();
#endif
  });
  connect(socket,&QLocalSocket::readyRead,this,[this]{read();});
  auto* clock=new QTimer(this);clock->setInterval(500);connect(clock,&QTimer::timeout,this,[this]{controls();});clock->start();id->setText(QUuid::createUuid().toString(QUuid::Id128));controls();
 }
 void setAgent(const QString& path,bool enabled){
  if(path!=agentPath||!enabled){request.clear();timer->stop();socket->abort();invalidate();}
  agentPath=path;ready=enabled;
  if(!enabled)details->setPlainText(tr("Marketplace unavailable\n\nThe connected agent does not offer buyer orders yet. Your wallet and local AI remain available. No funds have been reserved."));
  controls();
 }
private:
 QLineEdit* id;QSpinBox *units,*parallel;QPushButton *review,*accept,*status,*pool,*withdraw,*refund;QPlainTextEdit *details,*raw;
 QLocalSocket* socket;QTimer* timer;QString agentPath,request,action,hash;QByteArray buffer;QJsonObject params;bool ready=false;qint64 expiry=0;
 QPushButton* button(QHBoxLayout* row,const char* name,const QString& text,const QString& method){
  auto* b=new QPushButton(text,this);b->setObjectName(name);row->addWidget(b);connect(b,&QPushButton::clicked,this,[this,method]{send(method);});return b;
 }
 void invalidate(){hash.clear();expiry=0;controls();}
 void controls(){
  bool idle=request.isEmpty();id->setEnabled(idle);units->setEnabled(idle);parallel->setEnabled(idle);
  bool can=idle&&ready&&!agentPath.isEmpty()&&QRegularExpression("^[a-f0-9]{32}$").match(id->text()).hasMatch();
  review->setEnabled(can&&parallel->value()<=units->value());status->setEnabled(can);pool->setEnabled(can);withdraw->setEnabled(can);
  refund->setEnabled(can);
  accept->setEnabled(can&&!hash.isEmpty()&&expiry>QDateTime::currentSecsSinceEpoch());
 }
 void fail(){request.clear();timer->stop();socket->abort();invalidate();details->setPlainText(tr("Response unavailable. Refresh this order before retrying. No funding, payment or GPU execution was requested."));}
 void send(const QString& method){
  if(!request.isEmpty()||!ready)return;
  if(method=="acceptquote"&&!accept->isEnabled())return;
  action=method;params={{"quote_id",id->text()}};
  if(method=="quote"){params.insert("units",units->value());params.insert("parallelism",parallel->value());invalidate();}
  if(method=="acceptquote")params.insert("reviewed_digest",hash);
  buffer.clear();request=QUuid::createUuid().toString(QUuid::Id128);controls();timer->start(12000);socket->connectToServer(agentPath);
 }
 void read(){
  buffer+=socket->readAll();if(buffer.size()>16384){fail();return;}if(!buffer.contains('\n'))return;
  auto doc=QJsonDocument::fromJson(buffer);auto frame=doc.object();
  if(!buffer.endsWith('\n')||buffer.count('\n')!=1||!doc.isObject()||frame["v"]!=QJsonValue(1)||frame["id"]!=request||frame["ok"]!=QJsonValue(true)){fail();return;}
  auto result=frame["result"].toObject();raw->setPlainText(QString::fromUtf8(QJsonDocument(result).toJson(QJsonDocument::Indented)));
  if(action=="refundstatus"){
   auto state=result["state"].toString();
   if(result["quote_id"]!=id->text()||result["live_chain_checked"]!=QJsonValue(false)
      ||!QStringList{"not_requested","prepared","awaiting_reconciliation","confirmed_at_observed_tip"}.contains(state)){fail();return;}
   if(state=="not_requested")details->setPlainText(tr("No refund request recorded for this order.\nNo payment was requested by this check."));
   else {
    auto amount=result["refund_base_units"].toDouble(-1),fee=result["fee_base_units"].toDouble(-1);
    if(amount<1||amount>64e12||std::floor(amount)!=amount||fee<1||fee>1e12||std::floor(fee)!=fee){fail();return;}
    QString label=state=="prepared"?tr("Refund prepared; not yet sent"):tr("Refund transaction pending reconciliation");
    auto observation=result["observation"].toObject();
    if(state=="confirmed_at_observed_tip"){
     auto depth=observation["confirmations"].toDouble(-1);auto at=observation["observed_at"].toDouble(-1);
     if(observation["confirmed"]!=QJsonValue(true)||depth<6||std::floor(depth)!=depth||at<0
        ||!QRegularExpression("^[a-f0-9]{64}$").match(observation["observed_tip"].toString()).hasMatch()){fail();return;}
     label=tr("Refund confirmed in saved observation (%1 confirmations, checked %2)")
        .arg(depth,0,'f',0).arg(QDateTime::fromSecsSinceEpoch(qint64(at)).toString(Qt::ISODate));
    }
    details->setPlainText(tr("%1\n\nRefund: %2 testnet YERB\nNetwork fee: %3 testnet YERB\n\nSaved status only. No live chain check or payment was performed. Confirmations can change after a reorganization.")
      .arg(label,QString::number(amount/1e8,'f',8),QString::number(fee/1e8,'f',8)));
   }
  }else if(action=="quote"){
   auto t=result["terms"].toObject();auto price=t["unit_price_base_units"].toDouble(-1);auto total=t["maximum_work_cost_base_units"].toDouble(-1);
   auto calculated=QString::fromLatin1(QCryptographicHash::hash(QJsonDocument(t).toJson(QJsonDocument::Compact),QCryptographicHash::Sha256).toHex());
   auto now=QDateTime::currentSecsSinceEpoch();
   if(result["quote_sha256"]!=calculated||t["schema"]!=QJsonValue(1)||t["quote_id"]!=id->text()||t["units"]!=QJsonValue(units->value())||t["parallelism"]!=QJsonValue(parallel->value())
      ||t["network"]!="yerbas-private-reduced-collateral-testnet"||t["genesis"]!="e3a4fabed29dfc45e9aebe696453545ee2e198bae150e4c115fcc80ef3298554"
      ||t["billing"]!="fixed-price-per-verified-approved-work-unit"||t["provider_selection"]!="pooled"||t["recipe"]!="byte-context-mlp-v1"
      ||t["payment_enabled"]!=QJsonValue(false)||t["funding_required"]!=QJsonValue(true)||t["fees"]!="not-included-no-payment-enabled"
      ||price<1||price>1e12||std::floor(price)!=price||total!=price*units->value()
      ||t["issued_at"].toDouble()>now||t["accept_before"].toDouble()<=now||t["accept_before"].toDouble()>now+180){fail();return;}
   hash=calculated;expiry=qint64(t["accept_before"].toDouble());
   details->setPlainText(tr("%1 testnet YERB per verified work unit\n%2 testnet YERB maximum for %3 units\n\nUp to %4 GPUs may process independent units. Network fees are excluded.\n\nAccepting saves an unfunded order. No GPU starts and no coins are sent.")
      .arg(QString::number(price/100000000.0,'f',8),QString::number(total/100000000.0,'f',8)).arg(units->value()).arg(parallel->value()));
  }else{
   bool bound=result["quote_id"]==id->text()||(action=="order"&&result["terms"].toObject()["quote_id"]==id->text());
   if(!bound||(action=="acceptquote"&&(result["quote_sha256"]!=hash||result["funds_reserved"]!=QJsonValue(false)))
      ||(action!="pool"&&result["payment_enabled"]!=QJsonValue(false))){fail();return;}
   invalidate();
   if(action=="acceptquote")details->setPlainText(tr("Order saved · Awaiting funding\n\nNo funds have been reserved. Execution is disabled. You can withdraw this unfunded order at any time."));
   else if(action=="withdraw")details->setPlainText(tr("Order withdrawn\n\nUnfunded work has been withdrawn. No refund is due because no coins were collected."));
   else if(action=="pool")details->setPlainText(tr("%1 available provider matches\n\nThis is an availability preview, not a reservation. GPUs are assigned only when funded scheduling becomes available.").arg(result["matches"].toArray().size()));
   else {int waiting=0,withdrawn=0;for(auto unit:result["work_units"].toArray()){auto state=unit.toObject()["state"].toString();if(state=="withdrawn")++withdrawn;else if(state=="awaiting_funding")++waiting;}
    details->setPlainText(tr("Your order\n\n%1 units awaiting funding\n%2 units withdrawn\n\nNo payment or GPU execution is enabled.").arg(waiting).arg(withdrawn));}
  }
  request.clear();timer->stop();socket->abort();controls();
 }
};
#endif
