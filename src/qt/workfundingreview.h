#ifndef YERBAS_QT_WORKFUNDINGREVIEW_H
#define YERBAS_QT_WORKFUNDINGREVIEW_H
#include <QJsonObject>
#include <QJsonDocument>
#include <QCryptographicHash>
#include <QRegularExpression>
#include <QStringList>
#include <cmath>

// Validation only: no wallet keys, transaction construction, signing or dispatch.
namespace WorkFunding {
struct Context { QString buyer, caSha256, quoteId; QJsonObject recipe; int units=0, parallelism=0; qint64 now=0; };
struct Review { QString quoteId,digest,receivingScript; qint64 amount=0,providerAmount=0,settlementFee=0,acceptBefore=0; };
inline bool integer(const QJsonValue& v,qint64 lo,qint64 hi) {
 if(!v.isDouble())return false;
 double n=v.toDouble();return std::isfinite(n)&&std::floor(n)==n&&n>=lo&&n<=hi;
}
inline bool keys(const QJsonObject& o,QStringList wanted){wanted.sort();return o.keys()==wanted;}
inline QString validate(const QJsonObject& envelope,const Context& c,Review& result){
 result=Review();
 const QRegularExpression id("^[a-f0-9]{32}$"),sha("^[a-f0-9]{64}$"),script("^76a914[a-f0-9]{40}88ac$");
 if(!id.match(c.quoteId).hasMatch()||!sha.match(c.caSha256).hasMatch()||c.buyer.isEmpty()||c.recipe.isEmpty()||c.units<1||c.units>2||c.parallelism<1||c.parallelism>c.units||c.now<=0)return "Trusted request context required";
 if(!keys(envelope,{"terms","quote_sha256"})||!envelope["terms"].isObject())return "Invalid quote envelope";
 auto t=envelope["terms"].toObject();
 if(!keys(t,{"schema","quote_id","buyer","network","genesis","coordinator_ca_sha256","recipe","recipe_identity","units","parallelism","provider_selection","unit_price_base_units","maximum_work_cost_base_units","billing","issued_at","accept_before","funding_required","payment_enabled","execution_enabled","fees","payment_policy","verification","custody","cancellation"}))return "Unsupported paid terms";
 auto hash=QString::fromLatin1(QCryptographicHash::hash(QJsonDocument(t).toJson(QJsonDocument::Compact),QCryptographicHash::Sha256).toHex());
 if(envelope["quote_sha256"]!=hash)return "Quote digest mismatch";
 if(t["schema"]!=QJsonValue(3)||t["quote_id"]!=c.quoteId||t["buyer"]!=c.buyer||t["coordinator_ca_sha256"]!=c.caSha256)return "Quote identity mismatch";
 if(t["network"]!="yerbas-private-reduced-collateral-testnet"||t["genesis"]!="e3a4fabed29dfc45e9aebe696453545ee2e198bae150e4c115fcc80ef3298554")return "Wrong network";
 if(t["recipe"]!="byte-context-mlp-v1"||t["recipe_identity"]!=c.recipe||t["provider_selection"]!="pooled"||t["billing"]!="fixed-price-per-verified-approved-work-unit")return "Unsupported work";
 if(t["units"]!=QJsonValue(c.units)||t["parallelism"]!=QJsonValue(c.parallelism))return "Work request changed";
 if(t["funding_required"]!=QJsonValue(true)||t["payment_enabled"]!=QJsonValue(true)||t["execution_enabled"]!=QJsonValue(true))return "Paid work unavailable";
 if(!integer(t["issued_at"],1,c.now)||!integer(t["accept_before"],c.now+1,c.now+180)||t["accept_before"].toDouble()-t["issued_at"].toDouble()!=180)return "Quote expired or invalid time window";
 auto p=t["payment_policy"].toObject();
 if(!keys(p,{"scope","receiving_script","minimum_confirmations","provider_reward_base_units","payout_fee_base_units_per_unit"})||p["scope"]!="private-testnet-verified-work-v1"||!script.match(p["receiving_script"].toString()).hasMatch()||p["minimum_confirmations"]!=QJsonValue(6))return "Unsupported deposit policy";
 if(p["provider_reward_base_units"]!=QJsonValue(100000)||p["payout_fee_base_units_per_unit"]!=QJsonValue(1000)||t["unit_price_base_units"]!=QJsonValue(101000)||t["maximum_work_cost_base_units"]!=QJsonValue(101000*c.units))return "Price or settlement fee mismatch";
 if(t["fees"]!="1000 base units per unit included; buyer pays deposit transaction fee"||t["verification"]!="independent-enrolled-provider-reproduction"||t["custody"]!="operator-controlled-testnet-treasury; not trustless escrow"||t["cancellation"]!="unstarted orders require deposit reconciliation; partial settlement not enabled")return "Unsupported custody or refund terms";
 result={c.quoteId,hash,p["receiving_script"].toString(),101000*c.units,100000*c.units,1000*c.units,qint64(t["accept_before"].toDouble())};return {};
}
}
#endif
