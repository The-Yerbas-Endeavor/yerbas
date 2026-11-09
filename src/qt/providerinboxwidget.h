#ifndef YERBAS_QT_PROVIDERINBOXWIDGET_H
#define YERBAS_QT_PROVIDERINBOXWIDGET_H
#include <QWidget>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QPushButton>
#include <QLabel>
#include <QComboBox>
#include <QPlainTextEdit>
#include <QLocalSocket>
#include <QTimer>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>
#include <QDateTime>
#include <QSysInfo>
#include <QRegularExpression>
#include <QUuid>
#include <QSet>
#include <QProcess>
#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <QMessageBox>
#include <cmath>
#ifdef Q_OS_LINUX
#include <sys/socket.h>
#include <unistd.h>
#endif
// Inbox with explicit acceptance through the packaged durable controller. No payment route.
class ProviderInboxWidget : public QWidget {
 QLocalSocket socket;QTimer timeout;QString path,id,method,selected;QByteArray bytes;
 bool ready=false;QComboBox* assignments;QPushButton *refresh,*review,*status,*accept;QPlainTextEdit* details;
 QComboBox* saved;QPushButton *history,*release;
 QProcess worker;QByteArray workerBytes;QJsonObject reviewed;QString workerOperation,workerAssignment,workerDigest;
 QString helperDirectory=QCoreApplication::applicationDirPath()+"/provider-control";
 bool helperBusy=false,modal=false,helperStale=false;
 QString expectedAgent=QDir::homePath()+"/.local/share/yerbas-ai-control-v1/state/control.sock";
 bool ownAgent()const{return path==expectedAgent;}
 void startHelper(const QString& operation,const QString& assignment,const QString& hash){
  if(helperBusy||!ownAgent()||!QFileInfo::exists(helperDirectory+"/provider_start.py"))return;
  helperBusy=true;helperStale=false;workerBytes.clear();workerOperation=operation;workerAssignment=assignment;workerDigest=hash;reviewed={};controls();
  worker.setProgram("/usr/bin/python3");worker.setArguments({"-I","-B",helperDirectory+"/provider_start.py"});worker.start();
 }
 void finishHelper(int code,QProcess::ExitStatus exit){
  workerBytes+=worker.readAllStandardOutput();helperBusy=false;auto r=QJsonDocument::fromJson(workerBytes).object();reviewed={};
  if(helperStale){details->setPlainText(tr("Connection changed during review or submission. Reconcile the original assignment before another attempt."));controls();return;}
  if(code!=0||exit!=QProcess::NormalExit||workerBytes.size()>16384||r.isEmpty()){
   details->setPlainText(tr("Review or submission could not be confirmed. Check local execution and the retained assignment journal before retrying. No automatic retry."));controls();return;
  }
  if(workerOperation=="history"){
   auto rows=r["jobs"].toArray();if(!r["jobs"].isArray()||rows.size()>10||r["historical"]!=QJsonValue(true)){details->setPlainText(tr("Saved provider history unavailable."));controls();return;}
   QSet<QString> seen;for(auto value:rows){auto v=value.toObject();auto a=v["assignment"].toString();if(!identifier(a)||seen.contains(a)||!QRegularExpression("^[a-f0-9]{64}$").match(v["reviewed_digest"].toString()).hasMatch()){details->setPlainText(tr("Invalid saved provider history."));controls();return;}seen.insert(a);}
   saved->clear();for(auto value:rows){auto v=value.toObject();saved->addItem(v["assignment"].toString(),v["assignment"].toString());saved->setItemData(saved->count()-1,v["reviewed_digest"].toString(),Qt::UserRole+1);}
   details->setPlainText(tr("%1 saved submission(s). These are historical records, not completion or payment confirmation. Release checks the selected job is completed and safely stopped; the coordinator requires verified work and a recorded payout.").arg(rows.size()));
  }else if(workerOperation=="release"){
   if(r["assignment"]!=workerAssignment||r["released"]!=QJsonValue(true)||r["gpu_started"]!=QJsonValue(false)||r["payment_sent"]!=QJsonValue(false)||r["scope"]!="trusted-private-pilot-shutdown-report"){details->setPlainText(tr("Release acknowledgment uncertain. Refresh the same saved job before retrying."));controls();return;}
   details->setPlainText(tr("Completed slot released for %1. The job remains fenced against restart. No GPU work or payment started. Check GPU availability before offering new work.").arg(workerAssignment));
  }else if(workerOperation=="preview"){
   if(r["review_ready"]!=QJsonValue(true)||r["assignment"]!=workerAssignment||r["reviewed_digest"]!=workerDigest||r["provider"]!=QSysInfo::machineHostName()||r["steps"]!=QJsonValue(6000)||r["provider_reward_base_units"]!=QJsonValue(100000)||r["gpu_started"]!=QJsonValue(false)||r["payment_sent"]!=QJsonValue(false)||!integer(r["deadline"],QDateTime::currentSecsSinceEpoch()+1,9007199254740991.0)){details->setPlainText(tr("Provider policy review failed. No work started."));controls();return;}
   reviewed=r;details->appendPlainText(tr("\nProvider policy checked: 6,000-step public-text recipe. Potential verified-work reward: 0.00100000 tYERB. Accept and start rechecks funding, deadline and GPU readiness. Payment is subject to independent verification."));
  }else{
   if(r["assignment"]!=workerAssignment||r["phase"]!="submitted"||!r["new_submission"].isBool()){details->setPlainText(tr("Submission acknowledgment uncertain. Reconcile the saved assignment; do not create another job."));controls();return;}
   details->setPlainText(tr("Submission recorded for %1. Check local execution for progress. This acknowledgment does not prove completion, independent verification or payment.").arg(workerAssignment));
  }
  controls();
 }
 static bool identifier(const QString& s){return QRegularExpression("^[a-f0-9]{32}$").match(s).hasMatch();}
 static bool integer(const QJsonValue& v,double low,double high){return v.isDouble()&&std::isfinite(v.toDouble())&&std::floor(v.toDouble())==v.toDouble()&&v.toDouble()>=low&&v.toDouble()<=high;}
 void controls(){const bool idle=ready&&id.isEmpty()&&!helperBusy&&!modal;history->setEnabled(idle&&ownAgent());release->setEnabled(idle&&ownAgent()&&identifier(saved->currentData().toString()));saved->setEnabled(idle);accept->setEnabled(idle&&ownAgent()&&reviewed["assignment"].toString()==assignments->currentData().toString()&&reviewed["deadline"].toDouble()>QDateTime::currentSecsSinceEpoch());refresh->setEnabled(idle);review->setEnabled(idle&&assignments->currentIndex()>=0&&assignments->currentData(Qt::UserRole+1).toLongLong()>QDateTime::currentSecsSinceEpoch());status->setEnabled(idle&&identifier(assignments->currentData().toString()));assignments->setEnabled(idle);}
 void fail(){reviewed={};id.clear();timeout.stop();socket.abort();assignments->clear();details->setPlainText(tr("Assignment status unavailable. Refresh to recover. No work was accepted or started."));controls();}
 void send(const QString& action){
  if(!ready||!id.isEmpty()||helperBusy)return;
  reviewed={};
  selected=assignments->currentData().toString();
  if(action!="marketplace.pendingwork"&&!identifier(selected))return;
  method=action;bytes.clear();id=QUuid::createUuid().toString(QUuid::Id128);controls();timeout.start(12000);socket.connectToServer(path);
 }
 void read(){
  bytes+=socket.readAll();if(bytes.size()>32768){fail();return;}if(!bytes.contains('\n'))return;
  const auto doc=QJsonDocument::fromJson(bytes);const auto frame=doc.object();
  if(!doc.isObject()||bytes.count('\n')!=1||!bytes.endsWith('\n')||frame["v"]!=QJsonValue(1)||frame["id"]!=id||frame["ok"]!=QJsonValue(true)||!frame["result"].isObject()){fail();return;}
  const auto result=frame["result"].toObject();const auto now=QDateTime::currentSecsSinceEpoch();
  if(method=="marketplace.pendingwork"){
   if(!result["assignments"].isArray()||result["assignments"].toArray().size()>10||result["gpu_started"]!=QJsonValue(false)){fail();return;}
   QSet<QString> seen;const auto rows=result["assignments"].toArray();
   for(auto value:rows){const auto row=value.toObject();const auto key=row["assignment_id"].toString();if(!value.isObject()||!identifier(key)||seen.contains(key)||!QStringList{"reserved","accepted"}.contains(row["state"].toString())||!integer(row["deadline"],1,9007199254740991.0)){fail();return;}seen.insert(key);}
   assignments->clear();for(auto value:rows){const auto row=value.toObject();assignments->addItem(tr("%1 · %2").arg(row["state"].toString(),row["assignment_id"].toString()),row["assignment_id"].toString());assignments->setItemData(assignments->count()-1,qint64(row["deadline"].toDouble()),Qt::UserRole+1);}
   details->setPlainText(rows.isEmpty()?tr("No pending assignments returned. Completed jobs are not listed here.\nChecked %1").arg(QDateTime::currentDateTime().toString(Qt::ISODate)):tr("%1 assigned work unit(s). Review an assignment to inspect its terms.\nThis is a snapshot; availability and deadlines can change. No work has been accepted or started here.").arg(rows.size()));
  }else if(method=="marketplace.workassignment"){
   const auto t=result["terms"].toObject();
   if(t["assignment_id"]!=selected||t["run_id"]!=selected||t["provider"]!=QSysInfo::machineHostName()||!QRegularExpression("^[a-f0-9]{64}$").match(result["assignment_sha256"].toString()).hasMatch()||!integer(t["deadline"],1,9007199254740991.0)||!integer(t["steps"],1,6000)||!integer(t["unit_price_base_units"],1,2100000000000000.0)||t["payment_enabled"]!=QJsonValue(true)||t["execution_enabled"]!=QJsonValue(true)){fail();return;}
   const auto until=qint64(t["deadline"].toDouble());
   details->setPlainText(tr("Assignment: %1\nProvider: %2\nSteps: %3\nQuoted work-unit price: %4 tYERB\nDeadline: %5%6\n\nReported terms digest: %7\n\nReviewing terms starts no work. The packaged controller must validate provider policy before Accept and start becomes available.")
    .arg(selected,t["provider"].toString()).arg(t["steps"].toInt()).arg(t["unit_price_base_units"].toDouble()/100000000.0,0,'f',8).arg(QDateTime::fromSecsSinceEpoch(until).toString(Qt::ISODate),until<=now?tr(" · expired"):QString(),result["assignment_sha256"].toString()));
  }else if(method=="provider.status"){
   if(result["id"]!=selected||!QStringList{"queued","starting","running","completed","failed","cancelled","uncertain","stopping","training"}.contains(result["state"].toString())){fail();return;}
   details->setPlainText(tr("Local execution snapshot\nAssignment: %1\nState: %2\nChecked: %3\n\nLocal completion alone does not establish independent verification, payment, or released capacity.").arg(selected,result["state"].toString(),QDateTime::currentDateTime().toString(Qt::ISODate)));
  }else{fail();return;}
  const bool preview=method=="marketplace.workassignment";const auto hash=result["assignment_sha256"].toString();
  id.clear();timeout.stop();socket.abort();controls();
  if(preview)startHelper("preview",selected,hash);
 }
public:
 explicit ProviderInboxWidget(QWidget* parent=nullptr):QWidget(parent){
  accept=new QPushButton(tr("Accept and start approved work…"),this);accept->setObjectName("providerInboxAccept");
  auto* box=new QVBoxLayout(this);box->setContentsMargins(0,0,0,0);auto* title=new QLabel(tr("Assigned work"),this);title->setProperty("role","sectionTitle");box->addWidget(title);
  auto* row=new QHBoxLayout;assignments=new QComboBox(this);assignments->setObjectName("providerAssignments");assignments->setMinimumContentsLength(24);assignments->setSizeAdjustPolicy(QComboBox::AdjustToMinimumContentsLengthWithIcon);row->addWidget(assignments,1);
  refresh=new QPushButton(tr("Refresh assignments"),this);refresh->setObjectName("providerInboxRefresh");review=new QPushButton(tr("Review terms"),this);review->setObjectName("providerInboxReview");status=new QPushButton(tr("Check local execution"),this);status->setObjectName("providerInboxStatus");for(auto* button:{refresh,review,status})row->addWidget(button);box->addLayout(row);box->addWidget(accept);
  auto* savedRow=new QHBoxLayout;saved=new QComboBox(this);saved->setObjectName("providerSavedJobs");savedRow->addWidget(saved,1);history=new QPushButton(tr("Saved provider jobs"),this);history->setObjectName("providerHistory");release=new QPushButton(tr("Release completed slot"),this);release->setObjectName("providerRelease");savedRow->addWidget(history);savedRow->addWidget(release);box->addLayout(savedRow);
  details=new QPlainTextEdit(this);details->setReadOnly(true);details->setObjectName("providerInboxDetails");details->setMaximumHeight(220);details->setPlainText(tr("Connect the owner agent to see work assigned to this provider."));box->addWidget(details);
  connect(refresh,&QPushButton::clicked,this,[this]{send("marketplace.pendingwork");});connect(review,&QPushButton::clicked,this,[this]{if(review->isEnabled())send("marketplace.workassignment");});connect(status,&QPushButton::clicked,this,[this]{send("provider.status");});
  connect(assignments,qOverload<int>(&QComboBox::currentIndexChanged),this,[this]{reviewed={};details->clear();controls();});timeout.setSingleShot(true);connect(&timeout,&QTimer::timeout,this,[this]{fail();});
  connect(&worker,&QProcess::started,this,[this]{QJsonObject input{{"operation",workerOperation}};if(workerOperation!="history"){input["assignment"]=workerAssignment;input["reviewed_digest"]=workerDigest;}worker.write(QJsonDocument(input).toJson(QJsonDocument::Compact));worker.closeWriteChannel();});
  connect(&worker,&QProcess::readyReadStandardOutput,this,[this]{auto b=worker.readAllStandardOutput();if(workerBytes.size()<=16384)workerBytes+=b;});
  connect(&worker,&QProcess::readyReadStandardError,this,[this]{worker.readAllStandardError();});
  connect(&worker,qOverload<int,QProcess::ExitStatus>(&QProcess::finished),this,[this](int code,QProcess::ExitStatus exit){finishHelper(code,exit);});
  connect(&worker,&QProcess::errorOccurred,this,[this](QProcess::ProcessError error){if(error==QProcess::FailedToStart){helperBusy=false;reviewed={};details->setPlainText(tr("Packaged provider controller unavailable. No work started."));controls();}});
  connect(history,&QPushButton::clicked,this,[this]{if(history->isEnabled())startHelper("history",{},{});});
  connect(saved,qOverload<int>(&QComboBox::currentIndexChanged),this,[this]{controls();});
  connect(release,&QPushButton::clicked,this,[this]{if(release->isEnabled())startHelper("release",saved->currentData().toString(),saved->currentData(Qt::UserRole+1).toString());});
  connect(accept,&QPushButton::clicked,this,[this]{
   if(!accept->isEnabled())return;
   auto approved=reviewed;modal=true;controls();
   auto answer=QMessageBox::question(this,tr("Start approved GPU work?"),tr("Accept this assigned 6,000-step public-text job and use this computer's GPU? The potential reward is 0.00100000 testnet YERB after independent verification. This action sends no coins."));
   modal=false;controls();if(answer!=QMessageBox::Yes||reviewed!=approved||!accept->isEnabled())return;
   startHelper("run",approved["assignment"].toString(),approved["reviewed_digest"].toString());
  });
  connect(&socket,&QLocalSocket::errorOccurred,this,[this](QLocalSocket::LocalSocketError){if(!id.isEmpty())fail();});
  connect(&socket,&QLocalSocket::connected,this,[this]{
#ifdef Q_OS_LINUX
   struct ucred peer;socklen_t n=sizeof(peer);if(::getsockopt(socket.socketDescriptor(),SOL_SOCKET,SO_PEERCRED,&peer,&n)||peer.uid!=::geteuid()){fail();return;}
   QJsonObject params;if(method=="marketplace.workassignment")params["assignment_id"]=selected;else if(method=="provider.status")params["run_id"]=selected;
   socket.write(QJsonDocument(QJsonObject{{"v",1},{"id",id},{"method",method},{"params",params}}).toJson(QJsonDocument::Compact)+"\n");
#else
   fail();
#endif
  });connect(&socket,&QLocalSocket::readyRead,this,[this]{read();});auto* clock=new QTimer(this);clock->setInterval(1000);connect(clock,&QTimer::timeout,this,[this]{controls();});clock->start();controls();
 }
#ifdef YERBAS_PROVIDER_TEST
 void setTestOwnerPath(const QString& value){expectedAgent=value;}
#endif
 void setHelperDirectory(const QString& directory){helperDirectory=directory;reviewed={};controls();}
 void setAgent(const QString& agent,bool enabled){if(agent==path&&enabled==ready)return;reviewed={};if(helperBusy)helperStale=true;id.clear();timeout.stop();socket.abort();assignments->clear();saved->clear();path=agent;ready=enabled&&!path.isEmpty();details->setPlainText(ready?tr("Refresh to inspect assigned work. Nothing starts automatically."):tr("Owner agent disconnected. Previous snapshots cleared."));controls();}
};
#endif
