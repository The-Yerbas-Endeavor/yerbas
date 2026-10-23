// Copyright (c) 2026 The Yerbas developers
// Distributed under the MIT software license, see the accompanying COPYING file.
#ifndef YERBAS_QT_WALLETRECOVERY_H
#define YERBAS_QT_WALLETRECOVERY_H
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QStringList>
#include <QUuid>

namespace WalletRecovery {
// Never replace an existing wallet. A failed copy cannot change the active wallet.
inline QString copyBackup(const QString& source, const QString& directory)
{
    const QString name = "restored-" + QUuid::createUuid().toString(QUuid::WithoutBraces) + ".dat";
    const QString destination = QDir(directory).filePath(name);
    if (!QFileInfo(source).isFile() || QFileInfo(source).size() == 0 || !QFile::copy(source, destination)) return {};
    if (!QFile::setPermissions(destination, QFile::ReadOwner | QFile::WriteOwner)) {
        QFile::remove(destination);
        return {};
    }
    return name;
}
inline QStringList restartArguments(QStringList arguments, const QString& filename)
{
    if (!arguments.isEmpty()) arguments.removeFirst();
    const QStringList replaced{"-wallet", "-rescan", "-salvagewallet", "-zapwallettxes", "-reindex", "-reindex-chainstate", "-upgradewallet", "-disablewallet"};
    for (int i = arguments.size() - 1; i >= 0; --i) {
        QString key = arguments[i].section('=', 0, 0);
        if (key.startsWith("--")) key.remove(0, 1);
        if (replaced.contains(key)) arguments.removeAt(i);
    }
    arguments << "-wallet=" + filename << "-rescan=1";
    return arguments;
}
}
#endif
