#ifndef YERBAS_QT_WORKFUNDINGNATIVE_H
#define YERBAS_QT_WORKFUNDINGNATIVE_H
#include "workfundingreview.h"
#include "workdepositjournal.h"
#include "walletmodel.h"
#include "walletmodeltransaction.h"
#include "base58.h"
#include "chainparams.h"
#include "script/standard.h"
#include "util.h"
#include "utilstrencodings.h"
#include "validation.h"
#include "wallet/coincontrol.h"
#include "wallet/wallet.h"
#include <QDateTime>
#include <memory>

// Native wallet bridge. It is not exposed over agent IPC. The caller must retain
// normal wallet unlock and show the prepared fee and txid for confirmation.
class WorkFundingNative {
 WalletModel& model;QJsonObject quote;WorkFunding::Context context;WorkFunding::Review review;
 std::unique_ptr<WalletModelTransaction> transaction;
 QString txid; qint64 fee=0;unsigned int depositIndex=0;
 void validateContext(const QString& acceptedDigest){
  context.now=QDateTime::currentSecsSinceEpoch();
  auto error=WorkFunding::validate(quote,context,review);
  if(!error.isEmpty()||review.digest!=acceptedDigest)throw std::runtime_error("Accepted quote changed or expired");
  if(Params().NetworkIDString()!="test"||!gArgs.GetBoolArg("-testnetfastcollateral",false)||Params().GetConsensus().hashGenesisBlock.GetHex()!="e3a4fabed29dfc45e9aebe696453545ee2e198bae150e4c115fcc80ef3298554"||IsInitialBlockDownload())throw std::runtime_error("Synchronized private testnet required");
 }
 void checkTransaction(){
  CWallet* wallet=model.getWallet();auto* wtx=transaction->getTransaction();
  if(!wallet||!wtx||!wtx->tx||wtx->tx->vin.empty()||wtx->tx->IsCoinBase())throw std::runtime_error("Prepared wallet transaction required");
  auto bytes=ParseHex(review.receivingScript.toStdString());CScript target(bytes.begin(),bytes.end());
  LOCK2(cs_main,wallet->cs_wallet);
  int matches=0;CAmount debit=0;
  for(const auto& in:wtx->tx->vin){if(!(wallet->IsMine(in)&ISMINE_SPENDABLE))throw std::runtime_error("Deposit inputs must belong to this wallet");debit+=wallet->GetDebit(in,ISMINE_SPENDABLE);if(!MoneyRange(debit))throw std::runtime_error("Invalid input sum");}
  for(unsigned int i=0;i<wtx->tx->vout.size();++i){const auto& out=wtx->tx->vout[i];
   if(out.scriptPubKey==target){if(out.nValue!=review.amount)throw std::runtime_error("Deposit amount changed");++matches;depositIndex=i;}
   else if(!(wallet->IsMine(out)&ISMINE_SPENDABLE))throw std::runtime_error("Unexpected non-wallet output");
  }
  if(matches!=1||debit-wtx->tx->GetValueOut()!=fee||transaction->getTransactionFee()!=fee||QString::fromStdString(wtx->GetHash().GetHex())!=txid)throw std::runtime_error("Prepared transaction or fee changed");
 }
public:
 WorkFundingNative(WalletModel& wallet,QJsonObject terms,WorkFunding::Context expected):model(wallet),quote(terms),context(expected){}
 void prepare(const QString& acceptedDigest,const CCoinControl& coinControl){
  if(transaction)throw std::runtime_error("Transaction already prepared");validateContext(acceptedDigest);
  auto bytes=ParseHex(review.receivingScript.toStdString());CScript script(bytes.begin(),bytes.end());CTxDestination destination;
  if(!ExtractDestination(script,destination)||GetScriptForDestination(destination)!=script)throw std::runtime_error("Unsupported deposit destination");
  SendCoinsRecipient recipient(QString::fromStdString(CBitcoinAddress(destination).ToString()),"Yerbas AI work deposit",review.amount,"Work quote "+review.quoteId);
  recipient.fSubtractFeeFromAmount=false;
  auto prepared=std::unique_ptr<WalletModelTransaction>(new WalletModelTransaction({recipient}));
  auto result=model.prepareTransaction(*prepared,coinControl);
  if(result.status!=WalletModel::OK)throw std::runtime_error("Native wallet could not prepare deposit");
  fee=prepared->getTransactionFee();if(fee<0||fee>100000000)throw std::runtime_error("Deposit transaction fee outside bound");
  txid=QString::fromStdString(prepared->getTransaction()->GetHash().GetHex());transaction=std::move(prepared);checkTransaction();
 }
 QString preparedTxid()const{return txid;}
 qint64 transactionFee()const{return fee;}
 unsigned int outputIndex()const{return depositIndex;}
 WalletModel::SendCoinsReturn sendReviewed(const QString& acceptedDigest,const QString& reviewedTxid,qint64 reviewedFee,WorkDepositJournal& journal){
  if(!transaction||reviewedTxid!=txid||reviewedFee!=fee)throw std::runtime_error("Exact prepared transaction review required");
  validateContext(acceptedDigest);checkTransaction();
  // Durable intent first. Any exception or commit error after this point leaves
  // an immutable txid to reconcile and prevents creation of a second deposit.
  journal.begin(review,txid,fee);
  auto result=model.sendCoins(*transaction);
  if(result.status==WalletModel::OK)journal.submitted(review.quoteId,txid);
  return result;
 }
};
#endif
