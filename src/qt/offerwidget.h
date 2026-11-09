#ifndef YERBAS_QT_OFFERWIDGET_H
#define YERBAS_QT_OFFERWIDGET_H
#include <QWidget>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QLineEdit>
#include <QPushButton>
#include <QPlainTextEdit>
#include <QLocalSocket>
#include <QTimer>
#include <QJsonDocument>
#include <QJsonObject>
#include <QCryptographicHash>
#include <QDateTime>
#include <QRegularExpression>
#include <QSysInfo>
#include <QUuid>
#ifdef Q_OS_LINUX
#include <sys/socket.h>
#include <unistd.h>
#endif

// Local owner-agent IPC only. No wallet keys, HTTPS credentials or GPU submission.
class OfferWidget : public QWidget {
public:
    explicit OfferWidget(QWidget* parent=nullptr):QWidget(parent) {
        setSizePolicy(QSizePolicy::Preferred,QSizePolicy::Maximum);auto* layout=new QVBoxLayout(this);layout->setContentsMargins(0,0,0,0);
        auto* row=new QHBoxLayout;
        id=new QLineEdit(this);id->setObjectName("aiOfferId");id->setMaxLength(32);id->setPlaceholderText(tr("Assigned offer ID"));
        preview=new QPushButton(tr("Review offer"),this);preview->setObjectName("aiOfferPreview");
        accept=new QPushButton(tr("Accept reviewed terms"),this);accept->setObjectName("aiOfferAccept");
        retry=new QPushButton(tr("Recover acceptance"),this);retry->setObjectName("aiOfferRetry");
        row->addWidget(id);row->addWidget(preview);row->addWidget(accept);row->addWidget(retry);layout->addLayout(row);
        details=new QPlainTextEdit(this);details->setObjectName("aiOfferDetails");details->setReadOnly(true);details->setMinimumHeight(150);details->setMaximumHeight(280);
        details->setPlainText(tr("Offer service unavailable. Review starts nothing; acceptance reserves simulated credits without starting GPU work."));layout->addWidget(details);
        auto* technical=new QPushButton(tr("Exact offer terms"),this);technical->setCheckable(true);layout->addWidget(technical,0,Qt::AlignLeft);
        raw=new QPlainTextEdit(this);raw->setReadOnly(true);raw->setMaximumHeight(240);raw->hide();layout->addWidget(raw);connect(technical,&QPushButton::toggled,raw,&QWidget::setVisible);
        accept->setProperty("variant","primary");
        socket=new QLocalSocket(this);timer=new QTimer(this);timer->setSingleShot(true);
        connect(id,&QLineEdit::textChanged,this,[this]{clearReview();details->setPlainText(tr("Review this offer before accepting. Recover acceptance only retries an existing owner intent."));controls();});
        connect(preview,&QPushButton::clicked,this,[this]{send("offers.preview");});
        connect(accept,&QPushButton::clicked,this,[this]{send("offers.accept");});
        connect(retry,&QPushButton::clicked,this,[this]{send("offers.retry");});
        connect(timer,&QTimer::timeout,this,[this]{fail();});
        connect(socket,&QLocalSocket::errorOccurred,this,[this](QLocalSocket::LocalSocketError){if(!requestId.isEmpty())fail();});
        connect(socket,&QLocalSocket::connected,this,[this]{
#ifdef Q_OS_LINUX
            struct ucred peer; socklen_t size=sizeof(peer);
            if(::getsockopt(socket->socketDescriptor(),SOL_SOCKET,SO_PEERCRED,&peer,&size)||peer.uid!=::geteuid()){fail();return;}
            QJsonObject params{{"offer_id",requestedOffer}};
            if(method=="offers.accept")params.insert("offer_sha256",reviewedDigest);
            socket->write(QJsonDocument(QJsonObject{{"v",1},{"id",requestId},{"method",method},{"params",params}}).toJson(QJsonDocument::Compact)+"\n");
#else
            fail();
#endif
        });
        connect(socket,&QLocalSocket::readyRead,this,[this]{read();});
        auto* expiry=new QTimer(this);expiry->setInterval(500);connect(expiry,&QTimer::timeout,this,[this]{controls();});expiry->start();controls();
    }
    void setAgent(const QString& path,bool available) {
        if(path!=agentPath){requestId.clear();socket->abort();timer->stop();clearReview();}
        agentPath=path;ready=available;controls();
    }
private:
    QLineEdit* id;QPushButton *preview,*accept,*retry;QPlainTextEdit *details,*raw;
    QLocalSocket* socket;QTimer* timer;
    QString agentPath,requestId,method,requestedOffer,reviewedDigest;QByteArray buffer;
    qint64 expires=0;bool ready=false;
    bool validId()const{return QRegularExpression("^[a-f0-9]{32}$").match(id->text()).hasMatch();}
    void clearReview(){reviewedDigest.clear();expires=0;}
    void controls(){bool idle=requestId.isEmpty();id->setEnabled(idle);bool can=idle&&ready&&!agentPath.isEmpty()&&validId();preview->setEnabled(can);retry->setEnabled(can);accept->setEnabled(can&&!reviewedDigest.isEmpty()&&expires>QDateTime::currentSecsSinceEpoch());}
    void fail(){requestId.clear();timer->stop();socket->abort();clearReview();details->setPlainText(tr("Offer response unavailable or invalid. Acceptance may have been recorded. Recover acceptance for the same offer; no GPU start was requested."));controls();}
    void send(const QString& action){
        if(action=="offers.accept"&&!accept->isEnabled())return;
        if(action!="offers.accept"&&!preview->isEnabled())return;
        method=action;requestedOffer=id->text();buffer.clear();requestId=QUuid::createUuid().toString(QUuid::Id128);
        if(action=="offers.preview")clearReview();
        controls();timer->start(12000);socket->connectToServer(agentPath);
    }
    void read(){
        buffer+=socket->readAll();if(buffer.size()>16384){fail();return;}if(!buffer.contains('\n'))return;
        if(!buffer.endsWith('\n')||buffer.count('\n')!=1){fail();return;}
        auto doc=QJsonDocument::fromJson(buffer);auto frame=doc.object();
        if(!doc.isObject()||frame.value("v")!=QJsonValue(1)||frame.value("id").toString()!=requestId||!frame.value("ok").isBool()){fail();return;}
        requestId.clear();timer->stop();socket->abort();
        if(frame.value("ok")!=QJsonValue(true)){clearReview();details->setPlainText(tr("Offer request rejected or unavailable. Review again, or recover an existing acceptance for this offer."));controls();return;}
        auto result=frame.value("result").toObject();raw->setPlainText(QString::fromUtf8(QJsonDocument(result).toJson(QJsonDocument::Indented)));
        if(method=="offers.preview"){
            auto t=result.value("terms").toObject();auto reward=t.value("reward").toObject();
            auto hash=QString::fromLatin1(QCryptographicHash::hash(QJsonDocument(t).toJson(QJsonDocument::Compact),QCryptographicHash::Sha256).toHex());
            double until=t.value("accept_before").toDouble();
            if(result.keys()!=QStringList{"offer_sha256","terms"}||result.value("offer_sha256").toString()!=hash
                ||t.value("schema")!=QJsonValue(1)||t.value("offer_id").toString()!=requestedOffer
                ||t.value("provider").toString()!=QSysInfo::machineHostName()||t.value("recipe")!=QJsonValue("byte-context-mlp-v1")
                ||t.value("simulated_credits")!=QJsonValue(9)||reward.value("basis")!=QJsonValue("separate-operator-allowance")
                ||!reward.contains("promised_yerb_base_units")||!reward.value("promised_yerb_base_units").isNull()
                ||reward.value("automatic_gpu_time_rewards")!=QJsonValue(false)
                ||until<=QDateTime::currentSecsSinceEpoch()||until>QDateTime::currentSecsSinceEpoch()+180){fail();return;}
            reviewedDigest=hash;expires=qint64(until);
            details->setPlainText(tr("Review: 9 simulated credits; no promised YERB amount. Separate verification and operator reward approval required. Accepting reserves work but starts no GPU job.\nOpen Exact offer terms to inspect the binding."));
        }else{
            const QString hash=result.value("offer_sha256").toString();
            if(result.value("schema")!=QJsonValue(1)||result.value("offer_id").toString()!=requestedOffer
                ||result.value("provider").toString()!=QSysInfo::machineHostName()
                ||!QRegularExpression("^[a-f0-9]{64}$").match(hash).hasMatch()
                ||(method=="offers.accept"&&hash!=reviewedDigest)
                ||result.value("training_started")!=QJsonValue(false)||result.value("payments_authorized")!=QJsonValue(false)) {fail();return;}
            clearReview();details->setPlainText(tr("Acceptance recorded. This is a historical acknowledgement, not current job status. No GPU job or payment was started.\n"));
        }
        controls();
    }
};
#endif
