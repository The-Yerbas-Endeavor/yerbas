// Copyright (c) 2011-2015 The Bitcoin Core developers
// Copyright (c) 2014-2019 The Dash Core developers
// Copyright (c) 2020-2026 The Yerbas developers
// Props to Ramek Wukong
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#if defined(HAVE_CONFIG_H)
#include "config/yerbas-config.h"
#endif

#include "splashscreen.h"

#include "guiutil.h"
#include "networkstyle.h"

#include "clientversion.h"
#include "init.h"
#include "util.h"
#include "ui_interface.h"
#include "version.h"
#ifdef ENABLE_WALLET
#include "wallet/wallet.h"
#endif

#include <QApplication>
#include <QCloseEvent>
#include <QDesktopWidget>
#include <QFontMetrics>
#include <QKeyEvent>
#include <QPainter>
#include <QRect>
#include <QSize>
#include <QtGlobal>

SplashScreen::SplashScreen(Qt::WindowFlags f, const NetworkStyle *networkStyle) :
    QWidget(0, f), curAlignment(0)
{

    // transparent background
    setAttribute(Qt::WA_TranslucentBackground);
    setStyleSheet("background:transparent;");

    // no window decorations
    setWindowFlags(Qt::FramelessWindowHint);

    // define text to place
    QString titleText       = tr(PACKAGE_NAME);
    QString versionText     = QString(tr("Version %1")).arg(QString::fromStdString(FormatFullVersion()));
    QString copyrightText   = QString::fromUtf8(CopyrightHolders("\xc2\xA9", 2014, COPYRIGHT_YEAR).c_str());
    QString titleAddText    = networkStyle->getTitleAddText();

    QFont baseFont = QApplication::font();
    baseFont.setStyleStrategy(QFont::PreferAntialias);

    // load the bitmap for writing some text over it
    pixmap = networkStyle->getSplashImage();

    // Clamp splash size to the current available desktop area.
    // This prevents HiDPI / scaled desktops from turning the splash
    // into a near-fullscreen window.
    QRect screenGeometry = QApplication::desktop()->availableGeometry(this);

    int maxSplashWidth  = qMax(320, qMin(480, int(screenGeometry.width() * 0.55)));
    int maxSplashHeight = qMax(360, qMin(540, int(screenGeometry.height() * 0.72)));

    if (pixmap.width() > maxSplashWidth || pixmap.height() > maxSplashHeight) {
        pixmap = pixmap.scaled(
            QSize(maxSplashWidth, maxSplashHeight),
            Qt::KeepAspectRatio,
            Qt::SmoothTransformation
        );
    }

    const int paddingLeft   = qMax(12, int(pixmap.width() * 0.04));
    const int paddingRight  = paddingLeft;
    const int paddingBottom = qMax(12, int(pixmap.height() * 0.035));
    const int lineGap       = qMax(2, int(pixmap.height() * 0.006));

    float fontFactor = qMax(0.70f, qMin(1.0f, pixmap.width() / 480.0f));

    QPainter pixPaint(&pixmap);
    pixPaint.setRenderHint(QPainter::Antialiasing, true);
    pixPaint.setRenderHint(QPainter::TextAntialiasing, true);
    pixPaint.setRenderHint(QPainter::SmoothPixmapTransform, true);
    pixPaint.setPen(QColor(255,255,255));

    QFont titleFont(baseFont);
    titleFont.setPixelSize(qMax(22, int(25 * fontFactor)));
    titleFont.setWeight(QFont::Normal);

    QFont versionFont(baseFont);
    versionFont.setPixelSize(qMax(11, int(12 * fontFactor)));

    QFont copyrightFont(baseFont);
    copyrightFont.setPixelSize(qMax(8, int(9 * fontFactor)));

    // Shrink title if it does not fit the current splash width.
    pixPaint.setFont(titleFont);
    QFontMetrics fm = pixPaint.fontMetrics();
    int titleTextWidth = fm.width(titleText);
    const int availableTextWidth = pixmap.width() - paddingLeft - paddingRight;

    if (titleTextWidth > availableTextWidth && titleTextWidth > 0) {
        float fitFactor = fontFactor * (float(availableTextWidth) / float(titleTextWidth));
        fontFactor = qMax(0.60f, qMin(fontFactor, fitFactor));

        titleFont = QFont(baseFont);
        titleFont.setPixelSize(qMax(22, int(25 * fontFactor)));
        titleFont.setWeight(QFont::Normal);

        versionFont = QFont(baseFont);
        versionFont.setPixelSize(qMax(11, int(12 * fontFactor)));

        copyrightFont = QFont(baseFont);
        copyrightFont.setPixelSize(qMax(8, int(9 * fontFactor)));
    }

    QFontMetrics titleMetrics(titleFont);
    QFontMetrics versionMetrics(versionFont);
    QFontMetrics copyrightMetrics(copyrightFont);

    QRect copyrightProbeRect(
        0,
        0,
        availableTextWidth,
        pixmap.height()
    );

    QRect copyrightBounds = copyrightMetrics.boundingRect(
        copyrightProbeRect,
        Qt::AlignLeft | Qt::AlignTop | Qt::TextWordWrap,
        copyrightText
    );

    const int copyrightTop = pixmap.height() - paddingBottom - copyrightBounds.height();
    const int versionBaseline = copyrightTop - lineGap - versionMetrics.descent();
    const int titleBaseline = versionBaseline - versionMetrics.ascent() - lineGap - titleMetrics.descent();

    const int footerTop = qMax(0, titleBaseline - titleMetrics.ascent() - 10);

    pixPaint.fillRect(
        QRect(0, footerTop, pixmap.width(), pixmap.height() - footerTop),
        QColor(0, 0, 0, 85)
    );

    QRect copyrightRect(
        paddingLeft,
        copyrightTop,
        availableTextWidth,
        copyrightBounds.height()
    );

    // Draw a subtle shadow first so the text stays readable over the noisy art.
    pixPaint.setPen(QColor(0, 0, 0, 160));

    pixPaint.setFont(titleFont);
    pixPaint.drawText(paddingLeft + 1, titleBaseline + 1, titleText);

    pixPaint.setFont(versionFont);
    pixPaint.drawText(paddingLeft + 1, versionBaseline + 1, versionText);

    pixPaint.setFont(copyrightFont);
    pixPaint.drawText(
        copyrightRect.translated(1, 1),
        Qt::AlignLeft | Qt::AlignTop | Qt::TextWordWrap,
        copyrightText
    );

    // Draw the actual white text.
    pixPaint.setPen(QColor(255, 255, 255));

    pixPaint.setFont(titleFont);
    pixPaint.drawText(paddingLeft, titleBaseline, titleText);

    pixPaint.setFont(versionFont);
    pixPaint.drawText(paddingLeft, versionBaseline, versionText);

    pixPaint.setFont(copyrightFont);
    pixPaint.drawText(
        copyrightRect,
        Qt::AlignLeft | Qt::AlignTop | Qt::TextWordWrap,
        copyrightText
    );

    // draw additional text if special network
    if(!titleAddText.isEmpty()) {
        QFont boldFont(baseFont);
        boldFont.setPixelSize(qMax(9, int(10 * fontFactor)));
        boldFont.setWeight(QFont::Bold);

        pixPaint.setFont(boldFont);
        QFontMetrics addTextMetrics = pixPaint.fontMetrics();
        int titleAddTextWidth = addTextMetrics.width(titleAddText);

        pixPaint.drawText(
            pixmap.width() - titleAddTextWidth - 10,
            pixmap.height() - 25,
            titleAddText
        );
    }

    pixPaint.end();

    // Resize window and move to center of desktop, disallow resizing
    QRect r(QPoint(), pixmap.size());
    resize(r.size());
    setFixedSize(r.size());
    move(screenGeometry.center() - r.center());

    subscribeToCoreSignals();
    installEventFilter(this);
}

SplashScreen::~SplashScreen()
{
    unsubscribeFromCoreSignals();
}

bool SplashScreen::eventFilter(QObject * obj, QEvent * ev) {
    if (ev->type() == QEvent::KeyPress) {
        QKeyEvent *keyEvent = static_cast<QKeyEvent *>(ev);
        if(!keyEvent->text().isEmpty() && keyEvent->text()[0] == 'q' && breakAction != nullptr) {
            breakAction();
        }
    }
    return QObject::eventFilter(obj, ev);
}

void SplashScreen::slotFinish(QWidget *mainWin)
{
    Q_UNUSED(mainWin);

    /* If the window is minimized, hide() will be ignored. */
    /* Make sure we de-minimize the splashscreen window before hiding */
    if (isMinimized())
        showNormal();
    hide();
    deleteLater(); // No more need for this
}

static void InitMessage(SplashScreen *splash, const std::string &message)
{
    QMetaObject::invokeMethod(splash, "showMessage",
        Qt::QueuedConnection,
        Q_ARG(QString, QString::fromStdString(message)),
        Q_ARG(int, Qt::AlignBottom|Qt::AlignHCenter),
        Q_ARG(QColor, QColor(255,255,255)));
}

static void ShowProgress(SplashScreen *splash, const std::string &title, int nProgress)
{
    InitMessage(splash, title + strprintf("%d", nProgress) + "%");
}

void SplashScreen::setBreakAction(const std::function<void(void)> &action)
{
    breakAction = action;
}

static void SetProgressBreakAction(SplashScreen *splash, const std::function<void(void)> &action)
{
    QMetaObject::invokeMethod(splash, "setBreakAction",
        Qt::QueuedConnection,
        Q_ARG(std::function<void(void)>, action));
}

#ifdef ENABLE_WALLET
void SplashScreen::ConnectWallet(CWallet* wallet)
{
    wallet->ShowProgress.connect(boost::bind(ShowProgress, this, _1, _2));
    connectedWallets.push_back(wallet);
}
#endif

void SplashScreen::subscribeToCoreSignals()
{
    // Connect signals to client
    uiInterface.InitMessage.connect(boost::bind(InitMessage, this, _1));
    uiInterface.ShowProgress.connect(boost::bind(ShowProgress, this, _1, _2));
    uiInterface.SetProgressBreakAction.connect(boost::bind(SetProgressBreakAction, this, _1));
#ifdef ENABLE_WALLET
    uiInterface.LoadWallet.connect(boost::bind(&SplashScreen::ConnectWallet, this, _1));
#endif
}

void SplashScreen::unsubscribeFromCoreSignals()
{
    // Disconnect signals from client
    uiInterface.InitMessage.disconnect(boost::bind(InitMessage, this, _1));
    uiInterface.ShowProgress.disconnect(boost::bind(ShowProgress, this, _1, _2));
#ifdef ENABLE_WALLET
    for (CWallet* const & pwallet : connectedWallets) {
        pwallet->ShowProgress.disconnect(boost::bind(ShowProgress, this, _1, _2));
    }
#endif
}

void SplashScreen::showMessage(const QString &message, int alignment, const QColor &color)
{
    curMessage = message;
    curAlignment = alignment;
    curColor = color;
    update();
}

void SplashScreen::paintEvent(QPaintEvent *event)
{
    Q_UNUSED(event);

    QPainter painter(this);
    painter.setRenderHint(QPainter::Antialiasing, true);
    painter.setRenderHint(QPainter::TextAntialiasing, true);
    painter.setRenderHint(QPainter::SmoothPixmapTransform, true);

    painter.drawPixmap(0, 0, pixmap);

    QRect r = rect().adjusted(5, 5, -5, -5);
    painter.setPen(curColor);

    QFont messageFont = QApplication::font();
    messageFont.setStyleStrategy(QFont::PreferAntialias);
    painter.setFont(messageFont);

    painter.drawText(r, curAlignment, curMessage);
}

void SplashScreen::closeEvent(QCloseEvent *event)
{
    StartShutdown(); // allows an "emergency" shutdown during startup
    event->ignore();
}
