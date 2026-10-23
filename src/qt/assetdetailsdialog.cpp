// Copyright (c) 2026 The Yerbas developers
// Distributed under the MIT software license, see the accompanying COPYING file.
#include "assetdetailsdialog.h"

#include <QBuffer>
#include <QFileDialog>
#include <QSaveFile>
#include <QMessageBox>
#include <QDesktopServices>
#include <QDialogButtonBox>
#include <QImageReader>
#include <QLabel>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QRegularExpression>
#include <QScrollArea>
#include <QTimer>
#include <QVBoxLayout>
#include <memory>

bool AssetDetailsDialog::saveImage(const QImage& image, const QString& filename)
{
    QSaveFile file(filename);
    return !image.isNull() && file.open(QIODevice::WriteOnly) && image.save(&file, "PNG") && file.commit();
}

QUrl AssetDetailsDialog::contentUrl(const QString& hash, const QString& gateway)
{
    // Yerbas stores CIDv0 hashes or transaction IDs. Only CIDv0 is IPFS content.
    static const QRegularExpression cid("^Qm[1-9A-HJ-NP-Za-km-z]{44}$");
    if (!cid.match(hash).hasMatch() || gateway.count("%s") != 1)
        return QUrl();
    QString expanded = gateway;
    const QUrl url(expanded.replace("%s", hash), QUrl::StrictMode);
    if (!url.isValid() || url.host().isEmpty() || !url.userInfo().isEmpty()
        || (url.scheme() != "https" && url.scheme() != "http"))
        return QUrl();
    return url;
}

AssetDetailsDialog::AssetDetailsDialog(const QString& details, const QString& hash,
                                     const QString& gateway, const QNetworkProxy& proxy, QWidget* parent)
    : QDialog(parent)
{
    setWindowTitle(tr("Asset details"));
    resize(640, 620);
    auto* layout = new QVBoxLayout(this);
    auto* text = new QPlainTextEdit(details, this);
    text->setReadOnly(true);
    layout->addWidget(text);
    auto* notice = new QLabel(tr("Asset ownership is recorded on the blockchain. Images are external content and are not included in wallet.dat backups. Export an image to keep a local copy."), this);
    notice->setWordWrap(true);
    layout->addWidget(notice);
    const QUrl url = contentUrl(hash, gateway);
    auto* status = new QLabel(url.isEmpty() ? tr("No supported IPFS image reference or gateway.")
        : tr("Loading a preview contacts %1 using your network proxy settings.").arg(url.host()), this);
    status->setObjectName("previewStatus");
    status->setWordWrap(true);
    status->setTextFormat(Qt::PlainText);
    layout->addWidget(status);
    auto* load = new QPushButton(tr("Load image preview"), this);
    load->setObjectName("loadPreview");
    load->setEnabled(!url.isEmpty());
    layout->addWidget(load);
    auto* image = new QLabel(this);
    image->setAlignment(Qt::AlignCenter);
    auto* scroll = new QScrollArea(this);
    scroll->setWidget(image);
    scroll->setWidgetResizable(true);
    layout->addWidget(scroll);
    auto* fullSize = new QPushButton(tr("View full-size image"), this);
    fullSize->setObjectName("fullSizeImage");
    fullSize->setEnabled(false);
    layout->addWidget(fullSize);
    auto pixmap = std::make_shared<QPixmap>();
    auto* save = new QPushButton(tr("Export image…"), this);
    save->setObjectName("exportImage");
    save->setEnabled(false);
    layout->addWidget(save);
    connect(save, &QPushButton::clicked, this, [this, pixmap] {
        const QString path = QFileDialog::getSaveFileName(this, tr("Export asset image"), "asset.png", tr("PNG image (*.png)"));
        if (!path.isEmpty() && !saveImage(pixmap->toImage(), path))
            QMessageBox::warning(this, tr("Export failed"), tr("The image could not be saved."));
    });
    connect(fullSize, &QPushButton::clicked, this, [this, pixmap] {
        QDialog viewer(this);
        viewer.setWindowTitle(tr("Asset image"));
        auto* layout = new QVBoxLayout(&viewer);
        auto* image = new QLabel(&viewer);
        image->setPixmap(*pixmap);
        auto* scroll = new QScrollArea(&viewer);
        scroll->setWidget(image);
        layout->addWidget(scroll);
        viewer.resize(800, 600);
        viewer.exec();
    });
    auto* manager = new QNetworkAccessManager(this);
    manager->setProxy(proxy);
    connect(load, &QPushButton::clicked, this, [=] {
        load->setEnabled(false);
        status->setText(tr("Loading image…"));
        QNetworkRequest request(url);
        // Do not silently follow redirects to other hosts or schemes.
        request.setAttribute(QNetworkRequest::RedirectPolicyAttribute, QNetworkRequest::ManualRedirectPolicy);
        auto* reply = manager->get(request);
        reply->setReadBufferSize(1024 * 1024);
        auto bytes = std::make_shared<QByteArray>();
        constexpr int limit = 8 * 1024 * 1024;
        auto* timeout = new QTimer(reply);
        timeout->setSingleShot(true);
        connect(timeout, &QTimer::timeout, reply, &QNetworkReply::abort);
        timeout->start(15000);
        connect(reply, &QIODevice::readyRead, this, [reply, bytes] {
            bytes->append(reply->readAll());
            if (bytes->size() > limit)
                reply->abort();
        });
        connect(reply, &QNetworkReply::finished, this, [=] {
            timeout->stop();
            bytes->append(reply->readAll());
            const bool ok = reply->error() == QNetworkReply::NoError && bytes->size() <= limit
                && reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt() == 200;
            reply->deleteLater();
            load->setEnabled(true);
            if (!ok) {
                status->setText(tr("Preview unavailable: request failed, timed out, redirected, or exceeded 8 MiB."));
                return;
            }
            QBuffer buffer(bytes.get());
            buffer.open(QIODevice::ReadOnly);
            QImageReader reader(&buffer);
            const QSize size = reader.size();
            const QByteArray format = reader.format().toLower();
            if ((format != "png" && format != "jpeg" && format != "jpg" && format != "gif" && format != "webp")
                || !size.isValid() || qint64(size.width()) * size.height() > 16000000) {
                status->setText(tr("Unsupported image format or image exceeds 16 megapixels."));
                return;
            }
            const QImage decoded = reader.read();
            if (decoded.isNull()) {
                status->setText(tr("The IPFS content could not be decoded as an image."));
                return;
            }
            *pixmap = QPixmap::fromImage(decoded);
            image->setPixmap(pixmap->scaled(560, 260, Qt::KeepAspectRatio, Qt::SmoothTransformation));
            fullSize->setEnabled(true);
            save->setEnabled(true);
            status->setText(tr("Image loaded (%1 × %2). Preview content is not verified by the wallet.")
                .arg(decoded.width()).arg(decoded.height()));
        });
    });
    // Closing the dialog also destroys the manager and cancels pending requests.
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Close, this);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    layout->addWidget(buttons);
}
