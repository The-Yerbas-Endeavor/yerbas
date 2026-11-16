// Copyright (c) 2026 The Yerbas developers
// Distributed under the MIT software license, see the accompanying COPYING file.
#include "assetmanagerpage.h"
#include "assetfilterproxy.h"
#include "assettablemodel.h"
#include <QHeaderView>
#include <QItemSelectionModel>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPushButton>
#include <QTableView>
#include <QVBoxLayout>
#include <QHBoxLayout>

AssetManagerPage::AssetManagerPage(QWidget* parent) : QWidget(parent)
{
    auto* layout = new QVBoxLayout(this);
    auto* title = new QLabel(tr("My Assets"), this);
    QFont titleFont = title->font();
    titleFont.setPointSize(titleFont.pointSize() + 4);
    titleFont.setBold(true);
    title->setFont(titleFont);
    layout->addWidget(title);
    auto* intro = new QLabel(tr("Assets held by this wallet. Select an asset to send it or inspect its properties and metadata."), this);
    intro->setWordWrap(true);
    layout->addWidget(intro);
    auto* search = new QLineEdit(this);
    search->setObjectName("assetManagerSearch");
    search->setPlaceholderText(tr("Search your assets by name"));
    search->setAccessibleName(tr("Search your assets"));
    search->setClearButtonEnabled(true);
    layout->addWidget(search);
    filter = new AssetFilterProxy(this);
    filter->setSortRole(AssetTableModel::AssetNameRole);
    filter->sort(AssetTableModel::Name);

    table = new QTableView(this);
    table->setObjectName("assetManagerTable");
    table->setModel(filter);
    table->setSelectionBehavior(QAbstractItemView::SelectRows);
    table->setSelectionMode(QAbstractItemView::SingleSelection);
    table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    table->setAlternatingRowColors(true);
    table->verticalHeader()->hide();
    table->horizontalHeader()->setStretchLastSection(true);
    layout->addWidget(table, 1);
    count = new QLabel(this);
    count->setObjectName("assetManagerCount");
    layout->addWidget(count);
    selection = new QLabel(this);
    selection->setObjectName("assetManagerSelection");
    selection->setTextFormat(Qt::PlainText);
    selection->setWordWrap(true);
    selection->setTextInteractionFlags(Qt::TextSelectableByMouse);
    layout->addWidget(selection);
    auto* buttons = new QHBoxLayout;
    send = new QPushButton(tr("Send selected asset"), this);
    send->setObjectName("assetManagerSend");
    details = new QPushButton(tr("Details and metadata"), this);
    details->setObjectName("assetManagerDetails");
    auto* history = new QPushButton(tr("Asset history"), this);
    auto* backup = new QPushButton(tr("Backup and recovery"), this);
    buttons->addWidget(send);
    buttons->addWidget(details);
    buttons->addStretch();
    buttons->addWidget(history);
    buttons->addWidget(backup);
    layout->addLayout(buttons);
    connect(search, &QLineEdit::textChanged, this, [this](const QString& text) {
        table->clearSelection();
        filter->setAssetNameContains(text);
        table->setCurrentIndex(QModelIndex());
        table->clearSelection();
        updateSelection();
        updateCount();
    });
    auto clearSelection = [this] {
        table->setCurrentIndex(QModelIndex());
        table->clearSelection();
        updateSelection();
    };
    connect(filter, &QAbstractItemModel::modelAboutToBeReset, this, clearSelection);
    connect(filter, &QAbstractItemModel::rowsAboutToBeRemoved, this, clearSelection);
    connect(table->selectionModel(), &QItemSelectionModel::selectionChanged, this, [this] { updateSelection(); });
    connect(filter, &QAbstractItemModel::modelReset, this, [this] { updateCount(); updateSelection(); });
    connect(filter, &QAbstractItemModel::rowsInserted, this, [this] { updateCount(); });
    connect(filter, &QAbstractItemModel::rowsRemoved, this, [this] { updateCount(); updateSelection(); });
    connect(filter, &QAbstractItemModel::dataChanged, this, [this] { updateSelection(); });
    connect(send, &QPushButton::clicked, this, [this] {
        const auto rows = table->selectionModel()->selectedRows();
        if (!rows.isEmpty()) Q_EMIT sendRequested(rows.first());
    });
    connect(details, &QPushButton::clicked, this, [this] {
        const auto rows = table->selectionModel()->selectedRows();
        if (!rows.isEmpty()) Q_EMIT detailsRequested(rows.first());
    });
    connect(table, &QTableView::doubleClicked, this, [this](const QModelIndex& index) {
        if (index.isValid()) Q_EMIT detailsRequested(index);
    });
    connect(history, &QPushButton::clicked, this, &AssetManagerPage::historyRequested);
    connect(backup, &QPushButton::clicked, this, [this] {
        QMessageBox box(QMessageBox::Information, tr("Asset backup and recovery"),
            tr("Back up this wallet using the wallet backup command. Keep the backup encrypted or in secure offline storage. Never share private keys.\n\n"
               "A wallet backup protects the keys needed to control assets and ownership tokens. After restoring a backup, synchronize the chain and rescan wallet transactions if balances are missing. Verify the restored balances before relying on the backup.\n\n"
               "A metadata reference on the blockchain does not back up the referenced file. Keep a separate copy of any content you publish."),
            QMessageBox::Close, this);
        auto* save = box.addButton(tr("Back up this wallet…"), QMessageBox::ActionRole);
        box.exec();
        if (box.clickedButton() == save) Q_EMIT backupRequested();
    });
    updateCount();
    updateSelection();
}

void AssetManagerPage::setModel(QAbstractItemModel* model)
{
    table->clearSelection();
    filter->setSourceModel(model);
    if (model) table->horizontalHeader()->setSectionResizeMode(AssetTableModel::Name, QHeaderView::Stretch);
    updateCount();
    updateSelection();
}

void AssetManagerPage::updateCount()
{
    const int total = filter->sourceModel() ? filter->sourceModel()->rowCount() : 0;
    count->setText(total == 0 ? tr("No assets are currently listed in this wallet.")
        : tr("Showing %1 of %2 asset entries").arg(filter->rowCount()).arg(total));
}

void AssetManagerPage::updateSelection()
{
    const auto rows = table->selectionModel()->selectedRows();
    const bool selected = !rows.isEmpty();
    send->setEnabled(selected);
    details->setEnabled(selected);
    if (!selected) {
        selection->setText(tr("Select an asset to view its wallet quantity and ownership status."));
        return;
    }
    const auto index = rows.first();
    const QString name = index.data(AssetTableModel::AssetNameRole).toString();
    QString text = tr("%1\nWallet quantity: %2\nAdministrative ownership: %3").arg(name,
        index.data(AssetTableModel::FormattedAmountRole).toString(),
        index.data(AssetTableModel::AdministratorRole).toBool() ? tr("Held by this wallet") : tr("Not held by this wallet"));
    if (name.endsWith('!'))
        text += tr("\nThis is an ownership token. Sending it transfers the administrative rights it represents.");
    selection->setText(text);
}
