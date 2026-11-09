#ifndef YERBAS_QT_CAPACITYWIDGET_H
#define YERBAS_QT_CAPACITYWIDGET_H
#include "rentalwidget.h"

class CapacityWidget : public QWidget {
public:
 explicit CapacityWidget(QWidget* parent=nullptr):QWidget(parent){
  setSizePolicy(QSizePolicy::Preferred,QSizePolicy::Maximum);
  auto* box=new QVBoxLayout(this);box->setContentsMargins(0,0,0,0);box->setSpacing(12);
  auto* title=new QLabel(tr("GPU availability"),this);title->setProperty("role","sectionTitle");box->addWidget(title);
  auto* help=new QLabel(tr("Advertise one GPU for approved work. Listing does not start a job. Hardware details are self-reported; payment is not enabled."),this);help->setWordWrap(true);box->addWidget(help);
  auto* row=new QHBoxLayout;
  description=new QLineEdit(this);description->setObjectName("capacityDescription");description->setMaxLength(80);description->setPlaceholderText(tr("GPU name, e.g. GTX 1080 Ti"));
  memory=new QSpinBox(this);memory->setObjectName("capacityMemory");memory->setRange(1,1048576);memory->setSuffix(tr(" MiB VRAM"));memory->setValue(11264);
  minutes=new QSpinBox(this);minutes->setObjectName("capacityMinutes");minutes->setRange(1,15);minutes->setValue(5);minutes->setSuffix(tr(" minutes"));
  row->addWidget(description,1);row->addWidget(memory);row->addWidget(minutes);box->addLayout(row);
  row=new QHBoxLayout;
  refresh=new QPushButton(tr("Refresh availability"),this);refresh->setObjectName("capacityRefresh");
  publish=new QPushButton(tr("Make available"),this);publish->setObjectName("capacityPublish");publish->setProperty("variant","primary");
  pause=new QPushButton(tr("Pause new work"),this);pause->setObjectName("capacityPause");
  row->addWidget(refresh);row->addWidget(publish);row->addWidget(pause);row->addStretch();box->addLayout(row);
  summary=new QLabel(tr("Availability service unavailable. Connect a compatible owner agent in Setup."),this);summary->setObjectName("capacitySummary");summary->setWordWrap(true);summary->setTextFormat(Qt::PlainText);summary->setProperty("role","card");box->addWidget(summary);
  socket=new QLocalSocket(this);deadline=new QTimer(this);deadline->setSingleShot(true);
  connect(refresh,&QPushButton::clicked,this,[this]{send("capacity");});
  connect(publish,&QPushButton::clicked,this,[this]{if(publish->isEnabled())send("advertise");});
  connect(pause,&QPushButton::clicked,this,[this]{if(pause->isEnabled())send("pause");});
  connect(description,&QLineEdit::textChanged,this,[this]{controls();});
  connect(deadline,&QTimer::timeout,this,[this]{fail();});
  connect(socket,&QLocalSocket::errorOccurred,this,[this](QLocalSocket::LocalSocketError){if(!id.isEmpty())fail();});
  connect(socket,&QLocalSocket::connected,this,[this]{
#ifdef Q_OS_LINUX
   struct ucred peer;socklen_t n=sizeof(peer);
   if(::getsockopt(socket->socketDescriptor(),SOL_SOCKET,SO_PEERCRED,&peer,&n)||peer.uid!=::geteuid()){fail();return;}
   socket->write(QJsonDocument(QJsonObject{{"v",1},{"id",id},{"method","marketplace."+method},{"params",params}}).toJson(QJsonDocument::Compact)+"\n");
#else
   fail();
#endif
  });
  connect(socket,&QLocalSocket::readyRead,this,[this]{read();});
  auto* tick=new QTimer(this);tick->setInterval(1000);connect(tick,&QTimer::timeout,this,[this]{
   if(known&&until>0&&until<=QDateTime::currentSecsSinceEpoch()&&state=="available"){
    known=false;summary->setText(tr("Availability expired. Refresh before advertising again. Listings are never renewed automatically."));controls();
   }
  });tick->start();controls();
 }
 void setAgent(const QString& path,bool enabled){
  bool changed=path!=agentPath||enabled!=ready;
  if(changed){id.clear();deadline->stop();socket->abort();known=false;}
  agentPath=path;ready=enabled;
  if(!ready)summary->setText(tr("Availability service unavailable. Your current jobs and wallet are unchanged."));
  controls();if(changed&&ready)send("capacity");
 }
private:
 QLineEdit* description;QSpinBox *memory,*minutes;QPushButton *refresh,*publish,*pause;QLabel* summary;
 QLocalSocket* socket;QTimer* deadline;QString agentPath,id,method,state;QJsonObject params;QByteArray bytes;
 bool ready=false,known=false;int revision=0;qint64 until=0;
 void controls(){bool idle=id.isEmpty();bool can=ready&&!agentPath.isEmpty()&&idle;refresh->setEnabled(can);
  description->setEnabled(idle);memory->setEnabled(idle);minutes->setEnabled(idle);
  publish->setEnabled(can&&known&&QRegularExpression("^[A-Za-z0-9 ._()+-]{1,80}$").match(description->text()).hasMatch());
  pause->setEnabled(can&&known&&revision>0&&state!="paused");
 }
 void fail(){id.clear();deadline->stop();socket->abort();known=false;summary->setText(tr("Availability could not be confirmed. A previous change may have succeeded. Refresh to recover its current state before trying again."));controls();}
 void send(const QString& action){
  if(!ready||!id.isEmpty())return;method=action;params={};
  if(action=="advertise")params={{"description",description->text()},{"vram_mib",memory->value()},{"ttl_seconds",minutes->value()*60},{"expected_revision",revision}};
  if(action=="pause")params={{"expected_revision",revision}};
  bytes.clear();id=QUuid::createUuid().toString(QUuid::Id128);controls();deadline->start(12000);socket->connectToServer(agentPath);
 }
 void read(){
  bytes+=socket->readAll();if(bytes.size()>16384){fail();return;}if(!bytes.contains('\n'))return;
  auto doc=QJsonDocument::fromJson(bytes);auto frame=doc.object();
  if(!doc.isObject()||!bytes.endsWith('\n')||bytes.count('\n')!=1||frame["v"]!=QJsonValue(1)||frame["id"]!=id||frame["ok"]!=QJsonValue(true)){fail();return;}
  auto r=frame["result"].toObject();
  if(r["provider"]!=QSysInfo::machineHostName()){fail();return;}
  if(method=="capacity"){
   double rev=r["revision"].toDouble(-1);state=r["state"].toString();
   if(rev<0||rev>2147483647||std::floor(rev)!=rev||!QStringList{"not_listed","available","paused","expired","busy"}.contains(state)
      ||r["gpu_started"]!=QJsonValue(false)||r["payments_enabled"]!=QJsonValue(false)||r["verified_hardware"]!=QJsonValue(false)||r["automatic_renewal"]!=QJsonValue(false)
      ||!r["active_job"].isBool()){fail();return;}
   double observed=r["observed_at"].toDouble(-1), expiry=r["available_until"].toDouble(-1);
   const double now=QDateTime::currentSecsSinceEpoch();
   if(observed<now-60||observed>now+60||std::floor(observed)!=observed
      ||(rev==0&&(state!="not_listed"||!r["available_until"].isNull()))
      ||(rev>0&&(!r["available_until"].isDouble()||expiry<0||expiry>observed+900||std::floor(expiry)!=expiry))
      ||(state=="available"&&(expiry<=now||r["active_job"].toBool()))){fail();return;}
   revision=int(rev);until=rev>0?qint64(expiry):0;known=true;
   if(description->text().isEmpty()&&revision>0){description->setText(r["description"].toString());memory->setValue(r["vram_mib"].toInt(1));}
   const QString label=state=="available"?tr("Available for new offers"):state=="paused"?tr("New work paused"):state=="busy"?tr("Busy with assigned work"):state=="expired"?tr("Availability expired"):tr("Not listed");
   summary->setText(label+"\n\n"+(r["active_job"].toBool()?tr("An assigned job is active. Pausing this listing does not stop that job."):tr("No active assignment is recorded. Listing alone starts no GPU work."))+"\n"+tr("Availability expires automatically. Refresh and explicitly renew to stay listed."));
  }else known=false;
  bool refreshAfter=method!="capacity";id.clear();deadline->stop();socket->abort();controls();if(refreshAfter)send("capacity");
 }
};
#endif
