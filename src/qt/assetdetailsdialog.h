// Copyright (c) 2026 The Yerbas developers
// Distributed under the MIT software license, see the accompanying COPYING file.
#ifndef YERBAS_QT_ASSETDETAILSDIALOG_H
#define YERBAS_QT_ASSETDETAILSDIALOG_H

#include <QDialog>
#include <QNetworkProxy>
#include <QUrl>

// Read-only metadata snapshot. No network activity until Load preview is clicked.
class AssetDetailsDialog : public QDialog
{
public:
    AssetDetailsDialog(const QString& details, const QString& hash, const QString& gateway,
                       const QNetworkProxy& proxy, QWidget* parent = nullptr);
    static QUrl contentUrl(const QString& hash, const QString& gateway);
};
#endif
