#ifndef YERBAS_QT_CAPACITYWIDGET_H
#define YERBAS_QT_CAPACITYWIDGET_H
#include "rentalwidget.h"
#include <QProcess>
#include <QComboBox>
#include <QMessageBox>
#include <QTableWidget>
#include <QHeaderView>
#include <QCoreApplication>
#include <QFileInfo>

class CapacityWidget : public QWidget {
 QTableWidget* devices;QLabel* summary;QPushButton* refresh;QProcess* worker;QTimer* timeout;
 QJsonArray inventory;QByteArray response;bool busy=false;QString helper;
 void fail(const QString& message){summary->setText(message);inventory={};devices->setRowCount(0);busy=false;refresh->setEnabled(true);timeout->stop();}
 void send(const QJsonObject& request){
  if(busy)return;
  if(!QFileInfo::exists(helper)){fail(tr("GPU controls are not installed. No availability changes were made."));return;}
  busy=true;response.clear();refresh->setEnabled(false);devices->setEnabled(false);
  summary->setText(tr("Checking detected GPUs and current availability…"));
  worker->setProgram("/usr/bin/python3");worker->setArguments({"-I","-B",helper});
  worker->start();
  worker->write(QJsonDocument(request).toJson(QJsonDocument::Compact));worker->closeWriteChannel();timeout->start(30000);
 }
 void render(const QJsonObject& r){
  if(r["protocol"]!="wallet-multi-gpu-v1"||r["provider"]!=QSysInfo::machineHostName()||!r["gpus"].isArray()||r["gpus"].toArray().size()>32||r["gpu_started"]!=QJsonValue(false)||r["coins_sent"]!=QJsonValue(false)) {fail(tr("GPU response could not be verified. Refresh before changing availability."));return;}
  const auto rows=r["gpus"].toArray();QSet<QString> seen;
  for(const auto& value:rows){const auto g=value.toObject();const auto uuid=g["gpu_uuid"].toString();
   if(!QRegularExpression("^GPU-[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$").match(uuid).hasMatch()||seen.contains(uuid)||!g["enrolled"].isBool()||!g["display_active"].isBool()||!QStringList{"offer","paused","reserved"}.contains(g["mode"].toString())||!g["revision"].isDouble()||g["revision"].toDouble()<0){fail(tr("Invalid GPU inventory. No new work was started."));return;}seen.insert(uuid);
  }
  inventory=rows;devices->setRowCount(rows.size());
  for(int i=0;i<rows.size();++i){const auto g=rows[i].toObject();
   auto* name=new QTableWidgetItem(tr("GPU %1 · %2").arg(g["index"].toInt()).arg(g["name"].toString()));name->setToolTip(g["gpu_uuid"].toString());devices->setItem(i,0,name);
   devices->setItem(i,1,new QTableWidgetItem(tr("%1 / %2 MiB free").arg(g["free_mib"].toInt()).arg(g["total_mib"].toInt())));
   devices->setItem(i,2,new QTableWidgetItem(g["display_active"].toBool()?tr("Desktop GPU"):tr("No active display")));
   QString state=g["active_assignment"].toBool()?tr("Busy — current job continues"):g["state"]=="offered"?tr("Offered (up to 10 minutes)"):g["state"]=="reserved"?tr("Reserved for me"):g["state"]=="expired"?tr("Offer expired"):tr("Paused");
   if(!g["enrolled"].toBool())state=tr("Setup required before offering");devices->setItem(i,3,new QTableWidgetItem(state));
   auto* modes=new QComboBox(devices);modes->addItem(tr("Reserve for me"),"reserved");modes->addItem(tr("Pause new offers"),"paused");modes->addItem(tr("Offer this GPU"),"offer");modes->setAccessibleName(tr("Availability for GPU %1").arg(g["index"].toInt()));modes->setCurrentIndex(modes->findData(g["mode"].toString()));devices->setCellWidget(i,4,modes);
   auto* apply=new QPushButton(tr("Apply"),devices);apply->setAccessibleName(tr("Apply availability for GPU %1").arg(g["index"].toInt()));devices->setCellWidget(i,5,apply);apply->setEnabled(g["enrolled"].toBool());
   connect(apply,&QPushButton::clicked,this,[this,g,modes]{
    if(busy)return;const auto mode=modes->currentData().toString();
    if(mode=="offer"&&g["display_active"].toBool()&&QMessageBox::question(this,tr("Offer a display GPU?"),tr("This GPU has an active display. Approved AI work may reduce desktop responsiveness. Offer it for up to 10 minutes?"))!=QMessageBox::Yes)return;
    send(QJsonObject{{"action","set"},{"slot",g["slot"]},{"gpu_uuid",g["gpu_uuid"]},{"mode",mode},{"revision",g["revision"]}});
   });
  }
  devices->resizeRowsToContents();int tableHeight=devices->horizontalHeader()->height()+8;for(int row=0;row<devices->rowCount();++row)tableHeight+=devices->rowHeight(row);devices->setMinimumHeight(qMin(420,qMax(180,tableHeight)));devices->setEnabled(true);busy=false;refresh->setEnabled(true);
  summary->setText(rows.isEmpty()?tr("No supported NVIDIA GPUs detected."):tr("Choose each GPU separately. Reserved GPUs receive no new offers; active jobs continue. Offers expire after 10 minutes and are never renewed automatically. Listing starts no work and sends no coins."));
 }
public:
 explicit CapacityWidget(QWidget* parent=nullptr):QWidget(parent){
  helper=QCoreApplication::applicationDirPath()+"/gpu-control/gpu_control.py";
  auto* box=new QVBoxLayout(this);box->setContentsMargins(0,0,0,0);
  auto* title=new QLabel(tr("Your GPUs"),this);title->setProperty("role","sectionTitle");box->addWidget(title);
  auto* help=new QLabel(tr("GPUs are detected automatically by their stable device IDs. Reserve your desktop GPU and offer other GPUs for approved testnet work."),this);help->setWordWrap(true);box->addWidget(help);
  devices=new QTableWidget(0,6,this);devices->setObjectName("gpuDevices");devices->setHorizontalHeaderLabels({tr("GPU"),tr("Memory"),tr("Desktop"),tr("Availability"),tr("Use"),tr("Control")});devices->setEditTriggers(QAbstractItemView::NoEditTriggers);devices->verticalHeader()->hide();devices->horizontalHeader()->setSectionResizeMode(QHeaderView::ResizeToContents);devices->horizontalHeader()->setSectionResizeMode(0,QHeaderView::Stretch);devices->setMinimumHeight(180);box->addWidget(devices);
  refresh=new QPushButton(tr("Refresh GPUs"),this);refresh->setObjectName("gpuRefresh");box->addWidget(refresh);
  summary=new QLabel(this);summary->setObjectName("gpuSummary");summary->setWordWrap(true);summary->setTextFormat(Qt::PlainText);box->addWidget(summary);
  worker=new QProcess(this);timeout=new QTimer(this);timeout->setSingleShot(true);
  connect(refresh,&QPushButton::clicked,this,[this]{send({{"action","status"}});});
  connect(worker,&QProcess::readyReadStandardOutput,this,[this]{response+=worker->readAllStandardOutput();if(response.size()>65536){worker->kill();fail(tr("GPU response too large. Refresh to recover current settings."));}});
  connect(timeout,&QTimer::timeout,this,[this]{worker->kill();fail(tr("Availability confirmation timed out. A change may have succeeded; refresh before retrying."));});
  connect(worker,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),this,[this](int code,QProcess::ExitStatus status){
   if(!busy)return;timeout->stop();response+=worker->readAllStandardOutput();auto doc=QJsonDocument::fromJson(response);
   if(code||status!=QProcess::NormalExit||!doc.isObject()){fail(tr("GPU availability could not be confirmed. ")+doc.object()["error"].toString().left(200)+tr(" Refresh before retrying."));return;}render(doc.object());
  });
  connect(worker,&QProcess::errorOccurred,this,[this](QProcess::ProcessError e){if(e==QProcess::FailedToStart)fail(tr("GPU detection helper could not start."));});
  QTimer::singleShot(0,this,[this]{send({{"action","status"}});});
 }
 void setAgent(const QString&,bool){}
};
#endif
