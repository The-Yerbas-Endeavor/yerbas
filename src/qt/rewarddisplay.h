#ifndef YERBAS_REWARD_DISPLAY_H
#define YERBAS_REWARD_DISPLAY_H
#include <QJsonObject>
#include <QJsonArray>
#include <QStringList>
#include <QRegularExpression>
#include <QSet>
#include <cmath>
inline QStringList walletRewardLines(const QJsonObject& r, const QString& address, const QString& host, qint64 now) {
    const QStringList unavailable{QStringLiteral("Testnet rewards: no valid saved observation.")};
    auto integer=[](QJsonValue v) { return v.isDouble() && std::isfinite(v.toDouble()) && std::floor(v.toDouble())==v.toDouble() && std::abs(v.toDouble())<=9007199254740991.0; };
    if (r.value("available")!=QJsonValue(true) || r.value("historical")!=QJsonValue(true)
        || r.value("live_authorization")!=QJsonValue(false) || r.value("payments_enabled")!=QJsonValue(false)
        || r.value("provider").toString()!=host || address.isEmpty() || r.value("address").toString()!=address
        || r.value("profile").toString()!=QStringLiteral("yerbas-private-reduced-collateral-testnet")
        || !integer(r.value("checked_at")) || !r.value("rewards").isArray()) return unavailable;
    const qint64 checked=r.value("checked_at").toInteger();
    if (checked<=0 || checked>now) return unavailable;
    const auto rows=r.value("rewards").toArray();
    if (rows.size()>20) return unavailable;
    QStringList lines{QStringLiteral("Testnet reward observations (%1). Not a live wallet balance.").arg(now-checked>300 ? QStringLiteral("stale") : QStringLiteral("saved snapshot"))};
    QSet<QString> seen;
    for (const auto& value: rows) {
        if (!value.isObject()) return unavailable;
        const auto row=value.toObject();
        const QString receipt=row.value("receipt").toString(),txid=row.value("txid").toString();
        if (!QRegularExpression("^[a-f0-9]{32}$").match(receipt).hasMatch() || seen.contains(receipt)
            || !QRegularExpression("^[a-f0-9]{64}$").match(txid).hasMatch()) return unavailable;
        seen.insert(receipt);
        for (const auto& key: {"amount_base_units","confirmations","required_confirmations","block_height","tip_height"})
            if (!integer(row.value(key))) return unavailable;
        const qint64 amount=row.value("amount_base_units").toInteger(),depth=row.value("confirmations").toInteger(),required=row.value("required_confirmations").toInteger();
        const qint64 block=row.value("block_height").toInteger(),tip=row.value("tip_height").toInteger();
        if (amount<=0 || amount>21000000LL*100000000 || required<1 || required>100 || block<0 || tip<block || depth!=tip-block+1) return unavailable;
        const QString state=depth>=required ? QStringLiteral("confirmed") : QStringLiteral("confirming");
        if (row.value("state").toString()!=state) return unavailable;
        const QString units=QString::number(amount/100000000)+"."+QString::number(amount%100000000).rightJustified(8,'0');
        lines<<QStringLiteral("%1 testnet YERB — %2; %3/%4 confirmations at height %5").arg(units,state).arg(depth).arg(required).arg(tip);
        lines<<QStringLiteral("Transaction: %1").arg(txid);
    }
    lines<<QStringLiteral("Confirmations can change after a reorg. This page cannot send rewards.");
    return lines;
}
#endif
