#ifndef YERBAS_QT_NETWORKAIWIDGET_H
#define YERBAS_QT_NETWORKAIWIDGET_H
#include "rentalwidget.h"
#include "smartnodeidentitywidget.h"
#include <functional>
/** Read-only coordinator snapshot. Never reads wallet keys or initiates work. */
class NetworkAIWidget : public QFrame {
public:
 std::function<void()> openMarketplace;
 explicit NetworkAIWidget(QWidget* parent=nullptr):QFrame(parent){
  setObjectName("frameNetworkAI");setProperty("role","card");
  auto* layout=new QVBoxLayout(this);layout->setContentsMargins(20,20,20,20);layout->setSpacing(12);
  auto* title=new QLabel(tr("AI network"),this);title->setProperty("role","sectionTitle");layout->addWidget(title);
  status=new QLabel(this);status->setObjectName("networkAIStatus");status->setWordWrap(true);status->setTextFormat(Qt::PlainText);layout->addWidget(status);
  identity=new SmartnodeIdentityWidget(this);layout->addWidget(identity);
  auto* row=new QHBoxLayout;refresh=new QPushButton(tr("Refresh"),this);refresh->setObjectName("networkAIRefresh");row->addWidget(refresh);
  auto* open=new QPushButton(tr("Open marketplace"),this);open->setProperty("variant","primary");row->addWidget(open);layout->addLayout(row);
  connect(open,&QPushButton::clicked,this,[this]{if(openMarketplace)openMarketplace();});
  socket=new QLocalSocket(this);timeout=new QTimer(this);timeout->setSingleShot(true);
  connect(refresh,&QPushButton::clicked,this,[this]{fetch();});
  connect(timeout,&QTimer::timeout,this,[this]{unavailable();});
  connect(socket,&QLocalSocket::errorOccurred,this,[this](QLocalSocket::LocalSocketError){if(!id.isEmpty())unavailable();});
  connect(socket,&QLocalSocket::connected,this,[this]{
#ifdef Q_OS_LINUX
   struct ucred peer;socklen_t n=sizeof(peer);
   if(::getsockopt(socket->socketDescriptor(),SOL_SOCKET,SO_PEERCRED,&peer,&n)||peer.uid!=::geteuid()){unavailable();return;}
   socket->write(QJsonDocument(QJsonObject{{"v",1},{"id",id},{"method","marketplace.summary"},{"params",QJsonObject{}}}).toJson(QJsonDocument::Compact)+"\n");
#else
   unavailable();
#endif
  });
  connect(socket,&QLocalSocket::readyRead,this,[this]{read();});
  auto* poll=new QTimer(this);poll->setInterval(30000);connect(poll,&QTimer::timeout,this,[this]{if(isVisible())fetch();else if(last&&QDateTime::currentSecsSinceEpoch()-last>60)unavailable();});poll->start();
  unavailable();
 }
 void setAgent(const QString& path,bool enabled){
  identity->setAgent(path,enabled);
  if(path!=agentPath||enabled!=ready){unavailable();agentPath=path;ready=enabled;}
  refresh->setEnabled(ready);if(ready&&id.isEmpty())fetch();else if(!ready)unavailable();
 }
private:
 SmartnodeIdentityWidget* identity;
 QLabel* status;QPushButton* refresh;QLocalSocket* socket;QTimer* timeout;
 QString agentPath,id;QByteArray bytes;bool ready=false;qint64 last=0;
 void unavailable(){id.clear();timeout->stop();socket->abort();last=0;refresh->setEnabled(ready);
  status->setText(tr("GPU availability: unavailable\nYour work requests: unavailable\n\nConnect a compatible marketplace agent in Yerbas AI → Setup. No current network data has been confirmed."));}
 void fetch(){if(!ready||!id.isEmpty())return;bytes.clear();id=QUuid::createUuid().toString(QUuid::Id128);refresh->setEnabled(false);timeout->start(12000);socket->connectToServer(agentPath);}
 void read(){
  bytes+=socket->readAll();if(bytes.size()>16384){unavailable();return;}if(!bytes.contains('\n'))return;
  auto doc=QJsonDocument::fromJson(bytes);auto frame=doc.object();auto r=frame["result"].toObject();
  auto count=[&](const char* key){double v=r[key].toDouble(-1);return v>=0&&v<=2147483647&&std::floor(v)==v;};
  double observed=r["observed_at"].toDouble(-1);qint64 now=QDateTime::currentSecsSinceEpoch();
  if(!doc.isObject()||bytes.count('\n')!=1||!bytes.endsWith('\n')||frame["v"]!=QJsonValue(1)||frame["id"]!=id||frame["ok"]!=QJsonValue(true)
     ||!count("available_gpus")||!count("rental_orders")||!count("awaiting_funding_units")||!count("active_units")
     ||observed<now-60||observed>now+60||std::floor(observed)!=observed||r["payments_enabled"]!=QJsonValue(false)) {unavailable();return;}
  last=qint64(observed);id.clear();timeout->stop();socket->abort();refresh->setEnabled(ready);
  status->setText(tr("Available GPU listings: %1\nYour work requests: %2\nWork units awaiting funding: %3 • Active: %4\n\nSelf-reported capacity; availability is not reserved.\nOpen the marketplace to check funding support and review a work quote.\nChecked %5")
    .arg(r["available_gpus"].toInt()).arg(r["rental_orders"].toInt()).arg(r["awaiting_funding_units"].toInt()).arg(r["active_units"].toInt()).arg(QDateTime::fromSecsSinceEpoch(last).toString("HH:mm:ss")));
 }
};
#endif
