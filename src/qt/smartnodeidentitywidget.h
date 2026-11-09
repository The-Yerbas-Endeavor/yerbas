#ifndef YERBAS_QT_SMARTNODEIDENTITYWIDGET_H
#define YERBAS_QT_SMARTNODEIDENTITYWIDGET_H
#include <QWidget>
#include <QVBoxLayout>
#include <QLabel>
#include <QPushButton>
#include <QLocalSocket>
#include <QTimer>
#include <QDateTime>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>
#include <QRegularExpression>
#include <QUuid>
#include <cmath>
#ifdef Q_OS_LINUX
#include <sys/socket.h>
#include <unistd.h>
#endif
/** Displays owner-agent verification, not consensus or payment authorization. */
class SmartnodeIdentityWidget : public QWidget {
public:
 explicit SmartnodeIdentityWidget(QWidget* parent=nullptr):QWidget(parent) {
  auto* layout=new QVBoxLayout(this);layout->setContentsMargins(0,0,0,0);
  label=new QLabel(this);label->setObjectName("smartnodeIdentityStatus");label->setWordWrap(true);label->setTextFormat(Qt::PlainText);layout->addWidget(label);
  refresh=new QPushButton(tr("Check AI identity"),this);refresh->setObjectName("smartnodeIdentityRefresh");layout->addWidget(refresh);
  socket=new QLocalSocket(this);deadline=new QTimer(this);deadline->setSingleShot(true);
  connect(refresh,&QPushButton::clicked,this,[this]{fetch();});
  connect(deadline,&QTimer::timeout,this,[this]{unavailable();});
  connect(socket,&QLocalSocket::errorOccurred,this,[this](QLocalSocket::LocalSocketError){if(!requestId.isEmpty())unavailable();});
  connect(socket,&QLocalSocket::disconnected,this,[this]{if(!requestId.isEmpty())unavailable();});
  connect(socket,&QLocalSocket::connected,this,[this]{
#ifdef Q_OS_LINUX
   struct ucred peer;socklen_t size=sizeof(peer);
   if(::getsockopt(socket->socketDescriptor(),SOL_SOCKET,SO_PEERCRED,&peer,&size)||peer.uid!=::geteuid()){unavailable();return;}
   socket->write(QJsonDocument(QJsonObject{{"v",1},{"id",requestId},{"method","marketplace.discovery"},{"params",QJsonObject{}}}).toJson(QJsonDocument::Compact)+"\n");
#else
   unavailable();
#endif
  });
  connect(socket,&QLocalSocket::readyRead,this,[this]{read();});
  auto* expiry=new QTimer(this);expiry->setInterval(500);connect(expiry,&QTimer::timeout,this,[this]{if(validUntil&&QDateTime::currentSecsSinceEpoch()>=validUntil)unavailable();});expiry->start();
  auto* poll=new QTimer(this);poll->setInterval(30000);connect(poll,&QTimer::timeout,this,[this]{if(isVisible())fetch();});poll->start();
  unavailable();
 }
 ~SmartnodeIdentityWidget() override {
  // Stop socket callbacks while child widgets and member state still exist.
  socket->disconnect(this);deadline->stop();requestId.clear();socket->abort();
 }
 void setAgent(const QString& path,bool enabled){
  if(path!=agentPath||enabled!=ready){unavailable();agentPath=path;ready=enabled;}
  refresh->setEnabled(ready);if(ready)fetch();else unavailable();
 }
private:
 QLabel* label;QPushButton* refresh;QLocalSocket* socket;QTimer* deadline;
 QString agentPath,requestId;QByteArray bytes;bool ready=false;qint64 validUntil=0;
 void unavailable(){requestId.clear();deadline->stop();socket->abort();validUntil=0;refresh->setEnabled(ready);
  label->setText(tr("AI identity: unavailable\nConnect a compatible agent and synchronize the private-testnet wallet to verify the service."));}
 void fetch(){if(!ready||!requestId.isEmpty())return;bytes.clear();requestId=QUuid::createUuid().toString(QUuid::Id128);refresh->setEnabled(false);deadline->start(12000);socket->connectToServer(agentPath);}
 void read(){
  if(requestId.isEmpty())return;
  bytes+=socket->readAll();if(bytes.size()>16384){unavailable();return;}if(!bytes.contains('\n'))return;
  QJsonParseError error;auto doc=QJsonDocument::fromJson(bytes,&error);auto frame=doc.object();auto r=frame["result"].toObject();
  auto integer=[&](const char* key){auto v=r[key];double n=v.toDouble(-1);return v.isDouble()&&n>=0&&n<9007199254740991.0&&std::floor(n)==n;};
  auto hash=[&](const char* key){return r[key].isString()&&QRegularExpression("^[a-f0-9]{64}$").match(r[key].toString()).hasMatch();};
  qint64 now=QDateTime::currentSecsSinceEpoch();double observed=r["observed_at"].toDouble(),expires=r["expires"].toDouble(),certificate=r["certificate_expires"].toDouble();
  if(error.error!=QJsonParseError::NoError||!doc.isObject()||bytes.count('\n')!=1||!bytes.endsWith('\n')||frame["v"]!=QJsonValue(1)||frame["id"]!=requestId||frame["ok"]!=QJsonValue(true)
    ||r["verified"]!=QJsonValue(true)||r["service"]!=QJsonValue("AI")||r["roles"]!=QJsonValue(QJsonArray{"discovery"})
    ||r["coordinator_authority_changed"]!=QJsonValue(false)||r["decentralized_consensus"]!=QJsonValue(false)
    ||!integer("height")||!integer("observed_at")||!integer("expires")||!integer("certificate_expires")||!hash("tip")||!hash("protx")
    ||observed<now-60||observed>now+60||expires<=now||expires>observed+300||certificate<expires){unavailable();return;}
  validUntil=qint64(expires);requestId.clear();deadline->stop();socket->abort();refresh->setEnabled(ready);
  label->setText(tr("AI identity verified by your local wallet\nSmartnode %1… • Block %2\nCertificate valid until %3\nPrivate pilot discovery; this is not decentralized consensus.")
   .arg(r["protx"].toString().left(12)).arg(qint64(r["height"].toDouble())).arg(QDateTime::fromSecsSinceEpoch(qint64(certificate)).toString("MMM d, HH:mm t")));
 }
};
#endif
