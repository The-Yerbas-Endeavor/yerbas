// Copyright (c) 2026 The Yerbas developers
// Distributed under the MIT software license, see the accompanying COPYING file.
#ifndef YERBAS_QT_TEST_ASSETVIEWTESTS_H
#define YERBAS_QT_TEST_ASSETVIEWTESTS_H
#include <QObject>
class AssetViewTests : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void assetManagerSelection();
    void contentUrls();
    void filteringAndSorting();
    void quantities();
    void detailsWithoutContent();
    void imagePreview_data();
    void imagePreview();
};
#endif
