#ifndef YERBAS_QT_WORKFUNDINGDIALOG_H
#define YERBAS_QT_WORKFUNDINGDIALOG_H
#include "workfundingreview.h"
#include <QDialog>
#include <QVBoxLayout>
#include <QLabel>
#include <QDialogButtonBox>
#include <QPushButton>
#include <QTimer>
#include <QDateTime>
#include <functional>
class WorkFundingDialog:public QDialog {
 QJsonObject quote;WorkFunding::Context context;WorkFunding::Review reviewed;
 std::function<qint64()> clock;QLabel* summary;QPushButton* proceed;
 static QString amount(qint64 n){return QString::number(n/100000000)+"."+QString::number(n%100000000).rightJustified(8,'0')+" tYERB";}
 bool refresh(){
  context.now=clock();auto error=WorkFunding::validate(quote,context,reviewed);proceed->setEnabled(error.isEmpty());
  if(!error.isEmpty()){summary->setText(tr("This quote cannot be funded. Refresh the work quote and review it again."));return false;}
  summary->setText(tr("%1 approved work units · Up to %2 in parallel\n\nProvider work: %3\nIncluded settlement fee: %4\nDeposit total: %5\n\nYour wallet’s deposit transaction fee is additional and will be shown in transaction review.\n\nThe testnet operator holds the deposit. This is not trustless escrow. Providers are paid for independently verified results. Cancellation requires deposit reconciliation; partial settlement is not supported yet.\n\nContinuing reviews terms only. No coins are sent here.").arg(context.units).arg(context.parallelism).arg(amount(reviewed.providerAmount),amount(reviewed.settlementFee),amount(reviewed.amount)));
  return true;
 }
public:
 WorkFundingDialog(QJsonObject envelope,WorkFunding::Context expected,QWidget* parent=nullptr,std::function<qint64()> now=[] {return QDateTime::currentSecsSinceEpoch();}):QDialog(parent),quote(envelope),context(expected),clock(now){
  setWindowTitle(tr("Review AI work deposit"));resize(590,420);auto* layout=new QVBoxLayout(this);layout->setSpacing(18);
  summary=new QLabel(this);summary->setObjectName("workDepositSummary");summary->setWordWrap(true);summary->setTextFormat(Qt::PlainText);layout->addWidget(summary);
  auto* buttons=new QDialogButtonBox(QDialogButtonBox::Cancel,this);proceed=buttons->addButton(tr("Continue to transaction review"),QDialogButtonBox::AcceptRole);proceed->setObjectName("workDepositContinue");layout->addWidget(buttons);
  connect(buttons,&QDialogButtonBox::rejected,this,&QDialog::reject);
  connect(proceed,&QPushButton::clicked,this,[this]{if(refresh())QDialog::accept();});
  auto* timer=new QTimer(this);timer->setInterval(500);connect(timer,&QTimer::timeout,this,[this]{refresh();});timer->start();refresh();
 }
 bool reviewedTerms(WorkFunding::Review& out){out=WorkFunding::Review();if(result()!=QDialog::Accepted||!refresh())return false;out=reviewed;return true;}
};
#endif
