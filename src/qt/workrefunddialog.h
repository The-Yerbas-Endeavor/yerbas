#ifndef YERBAS_QT_WORKREFUNDDIALOG_H
#define YERBAS_QT_WORKREFUNDDIALOG_H
#include "workfundingreview.h"
#include <QDialog>
#include <QVBoxLayout>
#include <QLabel>
#include <QDialogButtonBox>
#include <QPushButton>
namespace WorkRefund {
struct Context {QString buyer,ca,quote,quoteDigest,txid,receivingScript,refundScript,address;int vout=0,units=0;};
inline QString validate(const QJsonObject& envelope,const Context& c){
 if(!WorkFunding::keys(envelope,{"plan","plan_sha256","cancelled","coins_sent"})||envelope["cancelled"]!=QJsonValue(false)||envelope["coins_sent"]!=QJsonValue(false)||!envelope["plan"].isObject())return "Invalid preview";
 auto p=envelope["plan"].toObject();
 if(!WorkFunding::keys(p,{"quote_id","quote_sha256","buyer","genesis","coordinator_ca_sha256","deposit_txid","deposit_vout","deposit_base_units","receiving_script","refund_script","refund_base_units","fee_base_units","minimum_confirmations"}))return "Unsupported plan";
 auto h=QString::fromLatin1(QCryptographicHash::hash(QJsonDocument(p).toJson(QJsonDocument::Compact),QCryptographicHash::Sha256).toHex());
 const QRegularExpression hash("^[a-f0-9]{64}$"),id("^[a-f0-9]{32}$"),script("^76a914[a-f0-9]{40}88ac$");
 if(c.buyer.isEmpty()||c.address.isEmpty()||c.address.size()>128||!id.match(c.quote).hasMatch()||!hash.match(c.ca).hasMatch()||!hash.match(c.quoteDigest).hasMatch()||!hash.match(c.txid).hasMatch()||!script.match(c.refundScript).hasMatch()||!script.match(c.receivingScript).hasMatch()||c.vout<0||c.vout>65535||c.units<1||c.units>2)return "Trusted wallet context required";
 if(envelope["plan_sha256"]!=h||p["quote_id"]!=c.quote||p["quote_sha256"]!=c.quoteDigest||p["buyer"]!=c.buyer||p["coordinator_ca_sha256"]!=c.ca||p["deposit_txid"]!=c.txid||p["deposit_vout"]!=QJsonValue(c.vout)||p["receiving_script"]!=c.receivingScript||p["refund_script"]!=c.refundScript)return "Refund binding differs";
 if(p["genesis"]!="e3a4fabed29dfc45e9aebe696453545ee2e198bae150e4c115fcc80ef3298554"||p["minimum_confirmations"]!=QJsonValue(6)||p["deposit_base_units"]!=QJsonValue(101000*c.units))return "Wrong network or deposit";
 if(!WorkFunding::integer(p["fee_base_units"],1,1000*c.units)||!WorkFunding::integer(p["refund_base_units"],546,101000*c.units-1)||p["refund_base_units"].toDouble()+p["fee_base_units"].toDouble()!=101000*c.units)return "Refund amount or fee differs";
 return {};
}
}
class WorkRefundDialog:public QDialog {
 QJsonObject preview;WorkRefund::Context context;QPushButton* confirm;
 static QString amount(qint64 n){return QString::number(n/100000000)+"."+QString::number(n%100000000).rightJustified(8,'0')+" tYERB";}
public:
 WorkRefundDialog(QJsonObject value,WorkRefund::Context expected,QWidget* parent=nullptr):QDialog(parent),preview(value),context(expected){
  setWindowTitle(tr("Review AI work refund"));resize(600,380);auto* layout=new QVBoxLayout(this);auto* summary=new QLabel(this);summary->setTextFormat(Qt::PlainText);summary->setWordWrap(true);summary->setObjectName("refundSummary");layout->addWidget(summary);
  auto* buttons=new QDialogButtonBox(QDialogButtonBox::Cancel,this);confirm=buttons->addButton(tr("Confirm cancellation and refund request"),QDialogButtonBox::AcceptRole);confirm->setObjectName("refundConfirm");confirm->setAutoDefault(false);buttons->button(QDialogButtonBox::Cancel)->setDefault(true);layout->addWidget(buttons);
  bool valid=WorkRefund::validate(preview,context).isEmpty();confirm->setEnabled(valid);
  if(valid){auto p=preview["plan"].toObject();summary->setText(tr("Cancel this unstarted work request?\n\nDeposit: %1\nRefund fee deducted: %2\nYou receive: %3\n\nEnrolled refund address:\n%4\n\nWork request: %5\n\nConfirmation asks the coordinator to cancel eligible work and prepare this exact refund. It does not sign or send coins. The operator holds the deposit; payment remains pending until separately sent and confirmed.").arg(amount(p["deposit_base_units"].toDouble()),amount(p["fee_base_units"].toDouble()),amount(p["refund_base_units"].toDouble()),context.address,context.quote));}
  else summary->setText(tr("This refund does not match the wallet's deposit and enrolled destination. Refresh and reconcile the original transaction. No request has been sent."));
  connect(buttons,&QDialogButtonBox::rejected,this,&QDialog::reject);connect(confirm,&QPushButton::clicked,this,[this]{if(WorkRefund::validate(preview,context).isEmpty())accept();});
 }
 QString reviewedDigest()const{return result()==QDialog::Accepted&&WorkRefund::validate(preview,context).isEmpty()?preview["plan_sha256"].toString():QString();}
};
#endif
