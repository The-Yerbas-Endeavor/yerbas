#ifndef YERBAS_QT_WORKDEPOSITJOURNAL_H
#define YERBAS_QT_WORKDEPOSITJOURNAL_H
#include "workfundingreview.h"
#include <QDir>
#include <QJsonArray>
#include <QDirIterator>
#include <QFileInfo>
#include <QFile>
#include <QSaveFile>
#include <QLockFile>
#include <stdexcept>
#include <sys/stat.h>
#include <unistd.h>
#include <fcntl.h>
// Caller supplies its existing private wallet directory. One immutable send
// intent per quote. An uncertain send is never automatically retried here.
class WorkDepositJournal {
 QString directory;
 void checkDirectory(){struct stat s;auto bytes=QFile::encodeName(directory);if(::lstat(bytes.constData(),&s)||!S_ISDIR(s.st_mode)||s.st_uid!=::geteuid()||(s.st_mode&0077))throw std::runtime_error("Private wallet journal directory required");}
 QString path(const QString& id){if(!QRegularExpression("^[a-f0-9]{32}$").match(id).hasMatch())throw std::runtime_error("Invalid quote ID");return directory+"/"+id+".json";}
 QJsonObject read(const QString& id){QFileInfo info(path(id));if(!info.exists()&&!info.isSymLink())return {};struct stat s;auto name=QFile::encodeName(path(id));if(::lstat(name.constData(),&s)||!S_ISREG(s.st_mode)||s.st_uid!=::geteuid()||(s.st_mode&0077))throw std::runtime_error("Unsafe deposit intent");QFile f(path(id));if(!f.open(QIODevice::ReadOnly)||f.size()>4096)throw std::runtime_error("Cannot read deposit intent");auto doc=QJsonDocument::fromJson(f.readAll());if(!doc.isObject())throw std::runtime_error("Corrupt deposit intent");auto o=doc.object();if(!WorkFunding::keys(o,{"schema","quote_id","quote_sha256","receiving_script","amount_base_units","transaction_fee_base_units","txid","state"})||o["schema"]!=QJsonValue(1)||o["quote_id"]!=id||(o["state"]!="send_intent"&&o["state"]!="submitted"))throw std::runtime_error("Invalid deposit intent");
 const QRegularExpression hash("^[a-f0-9]{64}$"),script("^76a914[a-f0-9]{40}88ac$");
 if(!hash.match(o["txid"].toString()).hasMatch()||!hash.match(o["quote_sha256"].toString()).hasMatch()||!script.match(o["receiving_script"].toString()).hasMatch()||!WorkFunding::integer(o["amount_base_units"],1,202000)||!WorkFunding::integer(o["transaction_fee_base_units"],0,100000000))throw std::runtime_error("Invalid deposit intent values");return o;}
 void write(const QString& id,const QJsonObject& o){QSaveFile f(path(id));f.setDirectWriteFallback(false);if(!f.open(QIODevice::WriteOnly)||!f.setPermissions(QFileDevice::ReadOwner|QFileDevice::WriteOwner))throw std::runtime_error("Cannot create private intent");auto bytes=QJsonDocument(o).toJson(QJsonDocument::Compact);if(f.write(bytes)!=bytes.size()||!f.commit())throw std::runtime_error("Cannot persist deposit intent");int fd=::open(QFile::encodeName(directory).constData(),O_RDONLY|O_DIRECTORY);if(fd<0)throw std::runtime_error("Cannot sync intent directory");int result=::fsync(fd);::close(fd);if(result)throw std::runtime_error("Cannot sync intent directory");}
public:
 explicit WorkDepositJournal(QString privateDirectory):directory(privateDirectory){checkDirectory();}
 // Must succeed exactly once BEFORE invoking WalletModel::sendCoins.
 void begin(const WorkFunding::Review& r,const QString& txid,qint64 transactionFee){
  checkDirectory();auto name=path(r.quoteId);Q_UNUSED(name);const QRegularExpression hash("^[a-f0-9]{64}$"),script("^76a914[a-f0-9]{40}88ac$");
  if(!hash.match(r.digest).hasMatch()||!hash.match(txid).hasMatch()||!script.match(r.receivingScript).hasMatch()||r.amount<=0||r.amount>202000||transactionFee<0||transactionFee>100000000)throw std::runtime_error("Invalid reviewed transaction");
  QLockFile lock(directory+"/intent.lock");lock.setStaleLockTime(0);if(!lock.tryLock(0))throw std::runtime_error("Deposit intent busy");
  if(!read(r.quoteId).isEmpty())throw std::runtime_error("Existing deposit requires reconciliation; do not resend");
  write(r.quoteId,{{"schema",1},{"quote_id",r.quoteId},{"quote_sha256",r.digest},{"receiving_script",r.receivingScript},{"amount_base_units",double(r.amount)},{"transaction_fee_base_units",double(transactionFee)},{"txid",txid},{"state","send_intent"}});
 }
 void submitted(const QString& id,const QString& txid){checkDirectory();QLockFile lock(directory+"/intent.lock");lock.setStaleLockTime(0);if(!lock.tryLock(0))throw std::runtime_error("Deposit intent busy");auto o=read(id);if(o.isEmpty()||o["txid"]!=txid)throw std::runtime_error("Deposit transaction differs");o["state"]="submitted";write(id,o);}
 // Read-only recovery inventory. Never treats a retained send intent as payment proof.
 QJsonArray entries(){checkDirectory();QJsonArray out;QDirIterator it(directory,QStringList{"*.json"},QDir::Files|QDir::System|QDir::Hidden);
  while(it.hasNext()){it.next();if(out.size()>=1000)throw std::runtime_error("Deposit history exceeds display limit");auto name=it.fileName();auto id=name.left(name.size()-5);auto value=read(id);if(value.isEmpty())throw std::runtime_error("Deposit history changed during read");out.append(value);}return out;}
 QJsonObject status(const QString& id){checkDirectory();return read(id);}
};
#endif
