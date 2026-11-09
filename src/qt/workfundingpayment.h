#ifndef YERBAS_QT_WORKFUNDINGPAYMENT_H
#define YERBAS_QT_WORKFUNDINGPAYMENT_H
#include "workfundingnative.h"
#include "workorderrecovery.h"
#include "workrefunddialog.h"
#include <QMessageBox>
#include <QDir>
#include <QInputDialog>
#include <QDialog>
#include <QVBoxLayout>
#include <QPlainTextEdit>
#include <QDialogButtonBox>
// Called only by the local wallet UI after exact coordinator acceptance.
// Network agents never receive wallet keys or a signing RPC.
inline QJsonObject fundWorkFromWallet(WalletModel& model,const QJsonObject& quote,WorkFunding::Context context,const WorkFunding::Review& approved,const QString& journalPath,QWidget* parent){
 context.now=QDateTime::currentSecsSinceEpoch();WorkFunding::Review current;
 if(!WorkFunding::validate(quote,context,current).isEmpty()||current.digest!=approved.digest)throw std::runtime_error("Reviewed quote changed");
 QDir dir(journalPath);if(!dir.exists()){
  if(!QDir().mkdir(journalPath)||!QFile::setPermissions(journalPath,QFileDevice::ReadOwner|QFileDevice::WriteOwner|QFileDevice::ExeOwner))throw std::runtime_error("Cannot create private deposit journal");
 }
 WorkDepositJournal journal(journalPath);
 if(!journal.status(current.quoteId).isEmpty())throw std::runtime_error("Existing deposit must be reconciled; no replacement payment");
 auto unlock=model.requestUnlock();if(!unlock.isValid())return {{"cancelled",true}};
 WorkFundingNative native(model,quote,context);CCoinControl control;native.prepare(current.digest,control);
 QString txid=native.preparedTxid();qint64 fee=native.transactionFee();
 auto amount=[](qint64 n){return QString::number(n/100000000)+"."+QString::number(n%100000000).rightJustified(8,'0')+" tYERB";};
 QMessageBox confirmation(QMessageBox::Question,QObject::tr("Confirm AI work payment"),QObject::tr("Send %1 for %2 approved work units?\n\nDeposit transaction fee: %3\nTotal wallet debit: %4\n\nThe private-testnet operator holds this deposit; this is not trustless escrow.\n\nTransaction: %5").arg(amount(current.amount)).arg(context.units).arg(amount(fee),amount(current.amount+fee),txid),QMessageBox::Yes|QMessageBox::Cancel,parent);
 confirmation.setTextFormat(Qt::PlainText);confirmation.setDefaultButton(QMessageBox::Cancel);
 if(confirmation.exec()!=QMessageBox::Yes)return {{"cancelled",true}};
 auto sent=native.sendReviewed(current.digest,txid,fee,journal);
 if(sent.status!=WalletModel::OK)throw std::runtime_error("Deposit commit uncertain; reconcile pinned transaction");
 return {{"submitted",true},{"txid",txid},{"vout",double(native.outputIndex())}};
}
// Local retained records only: no network request, signing, or transaction replay.
inline void showSavedWorkDeposits(const QString& journalPath,QWidget* parent){
 QDialog dialog(parent);dialog.setWindowTitle(QObject::tr("Saved AI work deposits"));dialog.resize(760,460);auto* layout=new QVBoxLayout(&dialog);auto* text=new QPlainTextEdit(&dialog);text->setReadOnly(true);layout->addWidget(text);
 QStringList lines;lines<<QObject::tr("Local send records, not live payment or work status. A submitted record does not prove confirmation. Never send a replacement for an uncertain transaction.");
 try{
  if(!QFileInfo::exists(journalPath)&&!QFileInfo(journalPath).isSymLink())lines<<QObject::tr("No saved deposits in this wallet data directory.");
  else {WorkDepositJournal journal(journalPath);auto entries=journal.entries();if(entries.isEmpty())lines<<QObject::tr("No saved deposits.");for(const auto& value:entries){auto r=value.toObject();lines<<QString("\n%1: %2\n%3: %4\n%5: %6\n%7: %8").arg(QObject::tr("Work request"),r["quote_id"].toString(),QObject::tr("Transaction"),r["txid"].toString(),QObject::tr("Recorded state"),r["state"].toString(),QObject::tr("Deposit (tYERB)"),QString::number(r["amount_base_units"].toDouble()/1e8,'f',8));}}
 }catch(const std::exception&){lines.clear();lines<<QObject::tr("Saved deposit history could not be validated. Preserve the journal and reconcile wallet transactions before sending again.");}
 text->setPlainText(lines.join("\n"));auto* buttons=new QDialogButtonBox(QDialogButtonBox::Close,&dialog);layout->addWidget(buttons);QObject::connect(buttons,&QDialogButtonBox::rejected,&dialog,&QDialog::reject);dialog.exec();
}
inline QJsonObject selectSavedWorkDeposit(const QString& journalPath,QWidget* parent){
 try{if(!QFileInfo::exists(journalPath)&&!QFileInfo(journalPath).isSymLink()){QMessageBox::information(parent,QObject::tr("Saved deposits"),QObject::tr("No saved deposits in this wallet."));return {};}
 WorkDepositJournal journal(journalPath);auto entries=journal.entries();QStringList choices;for(auto v:entries){auto o=v.toObject();choices<<o["quote_id"].toString()+" · "+o["state"].toString()+" · "+o["txid"].toString();}
 if(choices.isEmpty())return {};bool ok=false;auto choice=QInputDialog::getItem(parent,QObject::tr("Recover saved AI order"),QObject::tr("Select the original deposit. Recovery reads saved status and sends no coins."),choices,0,false,&ok);if(!ok)return {};int i=choices.indexOf(choice);if(i<0)return {};return journal.status(entries[i].toObject()["quote_id"].toString());
 }catch(const std::exception&){QMessageBox::warning(parent,QObject::tr("Saved deposits"),QObject::tr("Could not validate the private deposit journal. Preserve it and reconcile the original transaction."));return {};}
}
// Native validation of the retained deposit output and enrolled destination.
// The enrolled identity can belong to a separate provider wallet; this does not
// claim that the currently open wallet owns that identity's private key.
inline WorkRefund::Context validateWorkRefundContext(WalletModel& model,const QJsonObject& recovered,const QJsonObject& journal,const WorkFunding::Context& binding){
 if(!WorkOrderRecovery::validate(recovered,journal,binding,QDateTime::currentSecsSinceEpoch()).isEmpty())throw std::runtime_error("Recovery binding changed");
 if(Params().NetworkIDString()!="test"||!gArgs.GetBoolArg("-testnetfastcollateral",false)||Params().GetConsensus().hashGenesisBlock.GetHex()!="e3a4fabed29dfc45e9aebe696453545ee2e198bae150e4c115fcc80ef3298554")throw std::runtime_error("Private testnet required");
 WorkRefund::Context c;auto t=recovered["quote"].toObject()["terms"].toObject();auto d=recovered["deposit"].toObject();
 c.buyer=binding.buyer;c.ca=binding.caSha256;c.quote=journal["quote_id"].toString();c.quoteDigest=journal["quote_sha256"].toString();c.txid=journal["txid"].toString();c.vout=d["vout"].toInt();c.units=t["units"].toInt();c.receivingScript=journal["receiving_script"].toString();c.address=recovered["enrolled_identity"].toObject()["address"].toString();
 CBitcoinAddress address(c.address.toStdString());CKeyID key;
 if(!address.IsValid()||!address.GetKeyID(key)||address.ToString()!=c.address.toStdString())throw std::runtime_error("Invalid enrolled testnet address");
 auto script=GetScriptForDestination(address.Get());c.refundScript=QString::fromStdString(HexStr(script));
 CWallet* wallet=model.getWallet();if(!wallet)throw std::runtime_error("Wallet unavailable");
 LOCK2(cs_main,wallet->cs_wallet);auto it=wallet->mapWallet.find(uint256S(c.txid.toStdString()));
 if(it==wallet->mapWallet.end()||!it->second.tx||c.vout<0||size_t(c.vout)>=it->second.tx->vout.size())throw std::runtime_error("Original deposit missing from wallet");
 const auto& out=it->second.tx->vout[c.vout];
 if(out.nValue!=journal["amount_base_units"].toDouble()||QString::fromStdString(HexStr(out.scriptPubKey))!=c.receivingScript)throw std::runtime_error("Original deposit output differs");
 return c;
}
#endif
