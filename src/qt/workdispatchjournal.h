#ifndef YERBAS_WORKDISPATCHJOURNAL_H
#define YERBAS_WORKDISPATCHJOURNAL_H
#include <QDir>
#include <QFile>
#include <QSaveFile>
#include <QLockFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QCryptographicHash>
#include <QUuid>
#include <QRegularExpression>
#include <stdexcept>
#include <fcntl.h>
#include <unistd.h>
namespace WorkDispatch {
inline QString intent(const QString& directory,const QJsonObject& binding){
 if(directory.isEmpty()||!QDir().mkpath(directory))throw std::runtime_error("dispatch directory unavailable");
 const auto data=QJsonDocument(binding).toJson(QJsonDocument::Compact);
 const auto key=QString::fromLatin1(QCryptographicHash::hash(data,QCryptographicHash::Sha256).toHex());
 const QString path=QDir(directory).filePath(key+".json");
 QLockFile lock(path+".lock");lock.setStaleLockTime(0);if(!lock.tryLock(0))throw std::runtime_error("dispatch journal busy");
 if(QFile::exists(path)){
  QFile f(path);if(!f.open(QIODevice::ReadOnly)||f.size()>8192)throw std::runtime_error("invalid dispatch journal");
  const auto value=QJsonDocument::fromJson(f.readAll()).object();
  if(value.size()!=2||value["binding"]!=binding||!QRegularExpression("^[a-f0-9]{32}$").match(value["request_id"].toString()).hasMatch())throw std::runtime_error("dispatch journal mismatch");
  return value["request_id"].toString();
 }
 const auto id=QUuid::createUuid().toString(QUuid::Id128);
 QSaveFile f(path);f.setDirectWriteFallback(false);
 if(!f.open(QIODevice::WriteOnly))throw std::runtime_error("cannot save dispatch intent");
 f.setPermissions(QFile::ReadOwner|QFile::WriteOwner);
 const auto raw=QJsonDocument(QJsonObject{{"binding",binding},{"request_id",id}}).toJson(QJsonDocument::Compact);
 if(f.write(raw)!=raw.size()||!f.commit())throw std::runtime_error("dispatch intent not committed");
 int fd=::open(QFile::encodeName(directory).constData(),O_RDONLY|O_DIRECTORY);
 if(fd<0)throw std::runtime_error("dispatch directory sync unavailable");
 int synced=::fsync(fd);::close(fd);if(synced)throw std::runtime_error("dispatch directory sync failed");
 return id;
}
}
#endif
