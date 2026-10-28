// Copyright (c) 2026 The Yerbas developers
// Distributed under the MIT software license, see the accompanying COPYING file.
#ifndef YERBAS_QT_ASSETMANAGERPAGE_H
#define YERBAS_QT_ASSETMANAGERPAGE_H

#include <QWidget>
#include <QModelIndex>
class QAbstractItemModel;
class QLabel;
class QPushButton;
class QTableView;
class AssetFilterProxy;

// Wallet-scoped holdings view. External metadata is never fetched by this page.
class AssetManagerPage : public QWidget
{
    Q_OBJECT
public:
    explicit AssetManagerPage(QWidget* parent = nullptr);
    void setModel(QAbstractItemModel* model);
Q_SIGNALS:
    void sendRequested(const QModelIndex& index);
    void detailsRequested(const QModelIndex& index);
    void historyRequested();
    void backupRequested();
private:
    void updateSelection();
    void updateCount();
    AssetFilterProxy* filter;
    QTableView* table;
    QLabel* count;
    QLabel* selection;
    QPushButton* send;
    QPushButton* details;
};
#endif
