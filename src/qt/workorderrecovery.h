#ifndef YERBAS_QT_WORKORDERRECOVERY_H
#define YERBAS_QT_WORKORDERRECOVERY_H
#include "workfundingreview.h"
#include <QJsonArray>
namespace WorkOrderRecovery {
// Historical quote validation only. This result must never authorize a new send.
inline QString validate(const QJsonObject& value,const QJsonObject& journal,WorkFunding::Context context,qint64 now){
 if(!WorkFunding::keys(value,{"quote_id","buyer","quote","accepted","work_units","deposit","payment","refund","ever_scheduled","enrolled_identity","live_chain_checked","refund_eligibility_checked","coins_sent"})||value["live_chain_checked"]!=QJsonValue(false)||value["refund_eligibility_checked"]!=QJsonValue(false)||value["coins_sent"]!=QJsonValue(false)||!value["accepted"].isBool()||!value["ever_scheduled"].isBool())return "Invalid recovery envelope";
 if(value["quote_id"]!=journal["quote_id"]||value["buyer"]!=context.buyer||!value["quote"].isObject())return "Wrong recovered order";
 auto envelope=value["quote"].toObject();auto terms=envelope["terms"].toObject();
 if(envelope["quote_sha256"]!=journal["quote_sha256"]||terms["payment_policy"].toObject()["receiving_script"]!=journal["receiving_script"]||terms["maximum_work_cost_base_units"]!=journal["amount_base_units"]||!WorkFunding::integer(terms["issued_at"],1,now)||!WorkFunding::integer(terms["units"],1,2)||!WorkFunding::integer(terms["parallelism"],1,2))return "Journal binding differs";
 context.quoteId=journal["quote_id"].toString();context.units=terms["units"].toInt();context.parallelism=terms["parallelism"].toInt();context.now=qint64(terms["issued_at"].toDouble());WorkFunding::Review review;
 if(!WorkFunding::validate(envelope,context,review).isEmpty())return "Invalid historical quote";
 const QRegularExpression hash("^[a-f0-9]{64}$");
 if(!hash.match(journal["txid"].toString()).hasMatch())return "Invalid saved transaction";
 if(!value["deposit"].isNull()){
  auto d=value["deposit"].toObject();if(!WorkFunding::keys(d,{"txid","vout","amount","cancelled"})||d["txid"]!=journal["txid"]||d["amount"]!=journal["amount_base_units"]||!WorkFunding::integer(d["vout"],0,65535)||!WorkFunding::integer(d["cancelled"],0,1))return "Deposit does not match saved send";
 }
 if(!value["work_units"].isArray()||value["work_units"].toArray().size()!=context.units)return "Invalid work units";
 int ordinal=0;for(auto unit:value["work_units"].toArray()){auto u=unit.toObject();if(!WorkFunding::keys(u,{"ordinal","state","provider","receipt"})||u["ordinal"]!=QJsonValue(ordinal++)||!u["state"].isString()||u["state"].toString().size()>64)return "Invalid work status";}
 for(auto key:{"payment","refund"})if(!value[key].isNull()){auto p=value[key].toObject();if(!WorkFunding::keys(p,{"digest","txid"})||!hash.match(p["digest"].toString()).hasMatch()||(!p["txid"].isNull()&&!hash.match(p["txid"].toString()).hasMatch()))return "Invalid settlement reference";}
 auto identity=value["enrolled_identity"].toObject();if(!WorkFunding::keys(identity,{"address","proof_sha256"})||identity["address"].toString().isEmpty()||identity["address"].toString().size()>128||!hash.match(identity["proof_sha256"].toString()).hasMatch())return "Invalid enrolled identity";
 return {};
}
}
#endif
