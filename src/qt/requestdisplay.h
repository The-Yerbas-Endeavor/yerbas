#ifndef YERBAS_REQUEST_DISPLAY_H
#define YERBAS_REQUEST_DISPLAY_H
#include <QJsonObject>
#include <QRegularExpression>
#include <QStringList>
#include <cmath>
inline QString requestStatusText(const QJsonObject& r,const QString& receipt,const QString& provider,qint64 now) {
 auto integer=[](QJsonValue v) {return v.isDouble() && std::isfinite(v.toDouble()) && std::floor(v.toDouble())==v.toDouble() && std::abs(v.toDouble())<=9007199254740991.0;};
 auto hash=[](QJsonValue v) {return QRegularExpression("^[a-f0-9]{64}$").match(v.toString()).hasMatch();};
 if(r.value("receipt").toString()!=receipt || r.value("provider").toString()!=provider || !hash(r.value("request_id")) || r.value("payment_authorized")!=QJsonValue(false) || r.value("gpu_time_approved")!=QJsonValue(false) || !integer(r.value("requested_at")) || r.value("requested_at").toInteger()<=0 || r.value("requested_at").toInteger()>now)return {};
 const auto state=r.value("status").toString();
 if(r.value("schema")==QJsonValue(1) && state=="pending_review")return QStringLiteral("Request recorded for %1 — pending review. No payment or GPU-time approval yet.").arg(receipt);
 if(r.value("schema")!=QJsonValue(2) || !r.value("lifecycle").isObject())return {};
 const auto d=r.value("lifecycle").toObject();if(d.value("status").toString()!=state)return {};
 if(state=="rejected") {
  const auto reason=d.value("reason").toString();if(!QStringList{"duplicate_payment","verification_failed","operator_declined"}.contains(reason))return {};
  return QStringLiteral("Request rejected: %1.").arg(reason);
 }
 const auto amount=d.value("amount_base_units");
 if(!integer(amount) || amount.toInteger()<546 || amount.toInteger()>100000000 || d.value("basis").toString()!="fixed_private_testnet_allowance" || !hash(d.value("verification_sha256")))return {};
 const auto n=amount.toInteger();const auto units=QString::number(n/100000000)+"."+QString::number(n%100000000).rightJustified(8,'0');
 const auto prefix=QStringLiteral("Fixed test allowance: %1 testnet YERB. ").arg(units);
 if(state=="approved")return prefix+QStringLiteral("Approved; payment not yet recorded. GPU time remains uncalibrated.");
 if(!hash(d.value("plan_sha256")) || !hash(d.value("txid")))return {};
 const auto tx=QStringLiteral(" Transaction: %1").arg(d.value("txid").toString());
 if(state=="payment_recorded")return prefix+QStringLiteral("Payment recorded; broadcast and confirmation not yet established.")+tx;
 if(!integer(d.value("observed_at")) || d.value("observed_at").toInteger()<=0 || d.value("observed_at").toInteger()>now)return {};
 const auto stale=now-d.value("observed_at").toInteger()>300 ? QStringLiteral(" Saved observation is stale.") : QString();
 if(state=="unknown" || state=="reorged") {
  for(const auto k:{"confirmations","block_height","tip_height","blockhash"})if(!d.value(k).isNull())return {};
  return prefix+(state=="reorged" ? QStringLiteral("Confirmation lost after a reorg. Original payment remains bound; no replacement sent.") : QStringLiteral("Payment status unavailable; do not treat it as unpaid."))+stale+tx;
 }
 if(state!="confirmed" && state!="confirming")return {};
 for(const auto k:{"confirmations","block_height","tip_height"})if(!integer(d.value(k)))return {};
 const auto depth=d.value("confirmations").toInteger(),block=d.value("block_height").toInteger(),tip=d.value("tip_height").toInteger();
 if(block<0 || tip<block || depth!=tip-block+1 || depth<=0 || (state=="confirmed")!=(depth>=6) || !hash(d.value("blockhash")))return {};
 return prefix+QStringLiteral("%1 — %2/6 confirmations at height %3. Reorgs can change confirmations.").arg(state).arg(depth).arg(tip)+stale+tx;
}
#endif
