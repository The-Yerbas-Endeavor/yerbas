#ifndef YERBAS_QT_WORKFUNDINGSESSION_H
#define YERBAS_QT_WORKFUNDINGSESSION_H
#include "workfundingreview.h"

// Session state only. Caller supplies enrollment/CA/recipe from trusted local
// configuration, never from the response being validated. Reconnect clears it.
class WorkFundingSession {
 WorkFunding::Context trusted;
 qint64 checkedAt=0;
 bool negotiated=false;
 QJsonObject envelope;
 WorkFunding::Review reviewed;
 QString accepted;
public:
 explicit WorkFundingSession(WorkFunding::Context context):trusted(context){}
 void reset(){checkedAt=0;negotiated=false;envelope={};reviewed={};accepted.clear();}
 bool negotiate(const QJsonObject& reply,qint64 now){
  reset();
  if(now<=0||trusted.buyer.isEmpty()||!QRegularExpression("^[a-f0-9]{64}$").match(trusted.caSha256).hasMatch()||trusted.recipe.isEmpty())return false;
  if(!WorkFunding::keys(reply,{"schema","buyer","network","genesis","coordinator_ca_sha256","recipe_identity","funding_protocol","quote_schema","maximum_units","automatic_dispatch","chain_checked","coins_sent"})
    ||reply["schema"]!=QJsonValue(1)||reply["buyer"]!=trusted.buyer||reply["coordinator_ca_sha256"]!=trusted.caSha256||reply["recipe_identity"]!=trusted.recipe
    ||reply["network"]!="yerbas-private-reduced-collateral-testnet"||reply["genesis"]!="e3a4fabed29dfc45e9aebe696453545ee2e198bae150e4c115fcc80ef3298554"
    ||reply["funding_protocol"]!="private-testnet-work-deposit-v1"||reply["quote_schema"]!=QJsonValue(3)||reply["maximum_units"]!=QJsonValue(2)
    ||reply["automatic_dispatch"]!=QJsonValue(false)||reply["chain_checked"]!=QJsonValue(false)||reply["coins_sent"]!=QJsonValue(false))return false;
  checkedAt=now;negotiated=true;return true;
 }
 bool available(qint64 now)const{return negotiated&&now>=checkedAt&&now-checkedAt<=60;}
 bool quote(const QJsonObject& value,const QString& requestId,int units,int parallelism,qint64 now){
  envelope={};reviewed={};accepted.clear();
  if(!available(now))return false;
  auto context=trusted;context.quoteId=requestId;context.units=units;context.parallelism=parallelism;context.now=now;
  if(!WorkFunding::validate(value,context,reviewed).isEmpty())return false;
  envelope=value;return true;
 }
 // Bind the exact acknowledgment to the quote before native preparation. No
 // inference of funding from a successful acceptance or a saved order.
 bool acknowledge(const QString& quoteId,const QString& digest,qint64 now){
  accepted.clear();
  if(!available(now)||reviewed.quoteId!=quoteId||reviewed.digest!=digest||digest.isEmpty()||reviewed.acceptBefore<=now)return false;
  accepted=digest;return true;
 }
 bool fundable(qint64 now)const{return available(now)&&!accepted.isEmpty()&&accepted==reviewed.digest&&reviewed.acceptBefore>now;}
 QJsonObject acceptedQuote(qint64 now)const{return fundable(now)?envelope:QJsonObject();}
};
#endif
