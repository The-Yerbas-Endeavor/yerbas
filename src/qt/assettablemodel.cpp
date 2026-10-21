// Copyright (c) 2011-2016 The Bitcoin Core developers
// Copyright (c) 2017-2020 The Raven Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include "assettablemodel.h"
#include "assetrecord.h"

#include "guiconstants.h"
#include "guiutil.h"
#include "walletmodel.h"
#include "wallet/wallet.h"

#include "core_io.h"

#include "amount.h"
#include "assets/assets.h"
#include "validation.h"
#include "platformstyle.h"

#include <QDebug>
#include <QStringList>



class AssetTablePriv {
public:
    AssetTablePriv(AssetTableModel *_parent) :
            parent(_parent)
    {
    }

    AssetTableModel *parent;

    QList<AssetRecord> cachedBalances;

    // loads all current balances into cache
#ifdef ENABLE_WALLET
    void refreshWallet() {
        qDebug() << "AssetTablePriv::refreshWallet";
        cachedBalances.clear();
        LOCK(cs_main);
        auto currentActiveAssetCache = GetCurrentAssetCache();
        if (currentActiveAssetCache) {
            {
                std::map<std::string, CAmount> balances;
                std::map<std::string, std::vector<COutput> > outputs;
                CWallet* wallet = parent->walletModel ? parent->walletModel->getWallet() : nullptr;
                if (!wallet) {
                    qWarning("AssetTablePriv::refreshWallet: Error retrieving asset balances");
                    return;
                }
                LOCK(wallet->cs_wallet);
                wallet->AvailableAssets(outputs, true, nullptr, 1, MAX_ASSET_MONEY, MAX_ASSET_MONEY);
                for (const auto& entry : outputs) {
                    for (const auto& output : entry.second) {
                        CAssetOutputEntry data;
                        if (GetAssetData(output.tx->tx->vout[output.i].scriptPubKey, data))
                            balances[entry.first] += data.nAmount;
                    }
                }
                std::set<std::string> setAssetsToSkip;
                auto bal = balances.begin();
                for (; bal != balances.end(); bal++) {
                    // retrieve units for asset
                    uint8_t units = OWNER_UNITS;
                    bool fIsAdministrator = true;
                    std::string ipfsHash = "";

                    if (setAssetsToSkip.count(bal->first))
                        continue;

                    if (!IsAssetNameAnOwner(bal->first)) {
                        // Asset is not an administrator asset
                        CNewAsset assetData;
                        if (!currentActiveAssetCache->GetAssetMetaDataIfExists(bal->first, assetData)) {
                            qWarning("AssetTablePriv::refreshWallet: Error retrieving asset data");
                            units = MAX_UNIT;
                        } else {
                            units = assetData.units;
                            ipfsHash = assetData.strIPFSHash;
                        }
                        // If we have the administrator asset, add it to the skip list
                        if (balances.count(bal->first + OWNER_TAG)) {
                            setAssetsToSkip.insert(bal->first + OWNER_TAG);
                        } else {
                            fIsAdministrator = false;
                        }
                    } else {
                        // Asset is an administrator asset, if we own assets that is administrators, skip this balance
                        std::string name = bal->first;
                        name.pop_back();
                        if (balances.count(name)) {
                            setAssetsToSkip.insert(bal->first);
                            continue;
                        }
                    }
                    cachedBalances.append(AssetRecord(bal->first, bal->second, units, fIsAdministrator, EncodeAssetData(ipfsHash)));
                }
            }
        }
    }
#endif


    int size() {
        return cachedBalances.size();
    }

    AssetRecord *index(int idx) {
        if (idx >= 0 && idx < cachedBalances.size()) {
            return &cachedBalances[idx];
        }
        return 0;
    }

};

AssetTableModel::AssetTableModel(WalletModel *parent) :
        QAbstractTableModel(parent),
        walletModel(parent),
        priv(new AssetTablePriv(this))
{
    columns << tr("Name") << tr("Quantity");
#ifdef ENABLE_WALLET
    priv->refreshWallet();
#endif
};

AssetTableModel::~AssetTableModel()
{
    delete priv;
};

void AssetTableModel::checkBalanceChanged() {
    qDebug() << "AssetTableModel::CheckBalanceChanged";
    // TODO: optimize by 1) updating cache incrementally; and 2) emitting more specific dataChanged signals
    beginResetModel();
#ifdef ENABLE_WALLET
    priv->refreshWallet();
#endif
    endResetModel();
}

int AssetTableModel::rowCount(const QModelIndex &parent) const
{
    return parent.isValid() ? 0 : priv->size();
}

int AssetTableModel::columnCount(const QModelIndex &parent) const
{
    return parent.isValid() ? 0 : columns.size();
}

QVariant AssetTableModel::data(const QModelIndex &index, int role) const
{
    Q_UNUSED(role);
    if(!index.isValid() || index.model() != this || index.row() >= priv->size() || index.column() >= columns.size())
        return QVariant();
    const AssetRecord *rec = priv->index(index.row());

    switch (role)
    {
        case AmountRole:
            return QVariant::fromValue<qlonglong>(rec->quantity);
        case AssetNameRole:
            return QString::fromStdString(rec->name);
        case FormattedAmountRole:
            return QString::fromStdString(rec->formattedQuantity());
        case AdministratorRole:
            return rec->fIsAdministrator;
        case AssetIPFSHashRole:
            return QString::fromStdString(rec->ipfshash);
        case AssetIPFSHashDecorationRole:
        {
            if (index.column() == Quantity)
                return QVariant();

            if (rec->ipfshash.size() == 0)
                return QVariant();

            QPixmap pixmap;

            //if (darkModeEnabled)
            //    pixmap = QPixmap::fromImage(QImage(":/icons/external_link_dark"));
            //else
                pixmap = QPixmap::fromImage(QImage(":/icons/external_link"));

            return pixmap;
        }
        case Qt::DecorationRole:
        {
            if (index.column() == Quantity)
                return QVariant();

            if (!rec->fIsAdministrator)
                return QVariant();

            QPixmap pixmap;

            //if (darkModeEnabled)
            //    pixmap = QPixmap::fromImage(QImage(":/icons/asset_administrator_dark"));
           // else
                pixmap = QPixmap::fromImage(QImage(":/icons/asset_administrator"));

            return pixmap;
        }
        case Qt::DisplayRole: {
            if (index.column() == Name)
                return QString::fromStdString(rec->name);
            else if (index.column() == Quantity)
                return QString::fromStdString(rec->formattedQuantity());
        }
        case Qt::ToolTipRole:
            return formatTooltip(rec);
        case Qt::TextAlignmentRole:
        {
            if (index.column() == Quantity) {
                return Qt::AlignRight + Qt::AlignVCenter;
            }
        }
        default:
            return QVariant();
    }
}

QVariant AssetTableModel::headerData(int section, Qt::Orientation orientation, int role) const
{
    if (role == Qt::DisplayRole)
    {
        if (orientation == Qt::Horizontal) {
            if (section >= 0 && section < columns.size())
                return columns.at(section);
        } else {
            return section;
        }
    } else if (role == Qt::SizeHintRole) {
        if (orientation == Qt::Vertical)
            return QSize(30, 50);
    } else if (role == Qt::TextAlignmentRole) {
        if (orientation == Qt::Vertical)
            return Qt::AlignLeft + Qt::AlignVCenter;

        return Qt::AlignHCenter + Qt::AlignVCenter;
    }

    return QVariant();
}

QModelIndex AssetTableModel::index(int row, int column, const QModelIndex &parent) const
{
    if (parent.isValid() || column < 0 || column >= columns.size())
        return QModelIndex();
    AssetRecord *data = priv->index(row);
    if(data)
    {
        QModelIndex idx = createIndex(row, column, priv->index(row));
        return idx;
    }

    return QModelIndex();
}

QString AssetTableModel::formatTooltip(const AssetRecord *rec) const
{
    QString tooltip = formatAssetName(rec) + QString("\n") + formatAssetQuantity(rec) + QString("\n") + formatAssetData(rec);
    return tooltip;
}

QString AssetTableModel::formatAssetName(const AssetRecord *wtx) const
{
    return QString::fromStdString(wtx->name);
}

QString AssetTableModel::formatAssetQuantity(const AssetRecord *wtx) const
{
    return QString::fromStdString(wtx->formattedQuantity());
}

QString AssetTableModel::formatAssetData(const AssetRecord *wtx) const
{
    return QString::fromStdString(wtx->ipfshash);
}