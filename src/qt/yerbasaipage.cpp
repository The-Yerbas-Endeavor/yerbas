#include "yerbasaipage.h"
#include "rewarddisplay.h"
#include "requestdisplay.h"
#include <QCoreApplication>
#include <QSysInfo>
#include <QSignalBlocker>
#include <cmath>
#include <QDateTime>
#include <QLocalSocket>
#include <QJsonArray>
#include <algorithm>
#include <cerrno>
#include <cstdio>
#include <QRegularExpression>
#include <QUuid>
#ifdef Q_OS_UNIX
#include <fcntl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <unistd.h>
#endif
#include <QCryptographicHash>
#include <QDir>
#include <QDirIterator>
#include <QTemporaryDir>
#include <QFile>
#include <QFileDialog>
#include <QFileInfo>
#include <QHBoxLayout>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QLineEdit>
#include <QPlainTextEdit>
#include <QProcess>
#include <QPushButton>
#include <QSettings>
#include <QStandardPaths>
#include <QTimer>
#include <QVBoxLayout>

namespace {
// Pinned private-pilot release, not an arbitrary Python plugin loader.
const QByteArray RELEASE_SHA256("463d7a783878a4d1554f55952cad5037fd140568a4eece5fa89237643a168051");
bool readBounded(const QString& path, QByteArray& data, qint64 limit)
{
    QFile file(path);
#ifdef Q_OS_UNIX
    const int fd = ::open(QFile::encodeName(path).constData(), O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
    struct stat st;
    if (fd < 0) return false;
    if (::fstat(fd, &st) || !S_ISREG(st.st_mode) || st.st_size > limit) { ::close(fd);return false; }
    if (!file.open(fd, QIODevice::ReadOnly, QFileDevice::AutoCloseHandle)) { ::close(fd);return false; }
#else
    if (!file.open(QIODevice::ReadOnly) || file.size() > limit) return false;
#endif
    data = file.read(limit + 1);
    return data.size() <= limit && file.error() == QFileDevice::NoError;
}
// Linux pilot files are data only. Never import code from the chosen folder.
#ifdef Q_OS_UNIX
struct PilotDirectory {
    int fd = -1;
    explicit PilotDirectory(const QString& root) {
        int current = ::open(QFile::encodeName(root).constData(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        for (const char* name : {"work", "operator"}) {
            if (current < 0) break;
            int next = ::openat(current, name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
            ::close(current);current = next;
        }
        struct stat st;
        if (current >= 0 && (::fstat(current, &st) || st.st_uid != ::geteuid() || (st.st_mode & 0022))) {
            ::close(current);current = -1;
        }
        fd = current;
    }
    ~PilotDirectory() { if (fd >= 0) ::close(fd); }
};
QJsonObject sessionSnapshot(int directory)
{
    if (directory < 0) return {};
    const int lock = ::openat(directory, "session.lock", O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
    struct stat st;
    if (lock < 0) return {};
    if (::fstat(lock, &st) || !S_ISREG(st.st_mode) || st.st_uid != ::geteuid()) { ::close(lock);return {}; }
    bool active = false;
    if (::flock(lock, LOCK_EX | LOCK_NB)) {
        if (errno != EWOULDBLOCK && errno != EAGAIN) { ::close(lock);return {}; }
        active = true;
    }
    int data = ::openat(directory, "active.json", O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
    QByteArray bytes;
    if (data >= 0) {
        if (!::fstat(data, &st) && S_ISREG(st.st_mode) && st.st_uid == ::geteuid() && st.st_size <= 16384) {
            QFile file;
            if (file.open(data, QIODevice::ReadOnly, QFileDevice::DontCloseHandle)) bytes = file.read(16385);
        }
        ::close(data);
    }
    ::close(lock);
    auto result = QJsonDocument::fromJson(bytes).object();
    static const QRegularExpression id("^[a-f0-9]{32}$");
    if (bytes.size() > 16384 || !id.match(result.value("run_id").toString()).hasMatch() ||
        !result.value("phase").isString() || result.value("phase").toString().size() > 80 ||
        !result.value("updated_at").isDouble()) return {};
    result.insert("active", active);
    return result;
}
#endif

}

YerbasAIPage::YerbasAIPage(QWidget* parent) : QWidget(parent)
{
    auto* layout = new QVBoxLayout(this);
    auto* title = new QLabel(tr("Yerbas AI — private pilot"), this);
    layout->addWidget(title);
    auto* explanation = new QLabel(tr("Use the model trained by two Yerbas contributors. Local generation needs no wallet unlock, blockchain sync, GPU or network. This tiny demonstration model produces fragmentary text; it is not a chatbot."), this);
    explanation->setWordWrap(true);layout->addWidget(explanation);
    auto* row = new QHBoxLayout;
    packagePath = new QLineEdit(this);packagePath->setObjectName("aiPackagePath");packagePath->setReadOnly(true);
    choose = new QPushButton(tr("Choose verified model folder…"), this);choose->setObjectName("aiChoosePackage");
    row->addWidget(packagePath);row->addWidget(choose);layout->addLayout(row);
    status = new QLabel(tr("Choose the extracted Yerbas AI text-model 0.1.0 folder to begin."), this);status->setObjectName("aiStatus");status->setWordWrap(true);status->setTextFormat(Qt::PlainText);layout->addWidget(status);
    details = new QLabel(this);details->setObjectName("aiDetails");details->setWordWrap(true);details->setTextFormat(Qt::PlainText);layout->addWidget(details);
    layout->addWidget(new QLabel(tr("Prompt"), this));
    prompt = new QPlainTextEdit(this);prompt->setObjectName("aiPrompt");prompt->setPlainText("Alice was ");prompt->setMaximumHeight(75);layout->addWidget(prompt);
    auto* buttons = new QHBoxLayout;
    generate = new QPushButton(tr("Generate locally"), this);generate->setObjectName("aiGenerate");generate->setEnabled(false);
    stop = new QPushButton(tr("Stop"), this);stop->setObjectName("aiStop");stop->setEnabled(false);
    buttons->addWidget(generate);buttons->addWidget(stop);buttons->addStretch();layout->addLayout(buttons);
    output = new QPlainTextEdit(this);output->setObjectName("aiOutput");output->setReadOnly(true);output->setMaximumHeight(110);layout->addWidget(output);
    auto* scope = new QLabel(tr("Training contributions: supervised pilot. Use the connected provider controls below for preassigned jobs. Job accounting uses simulated credits. This page cannot send YERB payments."), this);scope->setWordWrap(true);layout->addWidget(scope);
    auto* pilotRow = new QHBoxLayout;
    pilotPath = new QLineEdit(this);pilotPath->setReadOnly(true);pilotPath->setObjectName("aiPilotPath");
    auto* choosePilot = new QPushButton(tr("Choose pilot workspace…"), this);
    auto* refresh = new QPushButton(tr("Refresh jobs"), this);refresh->setObjectName("aiRefreshJobs");
    stopJob = new QPushButton(tr("Request training stop"), this);stopJob->setObjectName("aiStopJob");stopJob->setEnabled(false);
    pilotRow->addWidget(pilotPath);pilotRow->addWidget(choosePilot);pilotRow->addWidget(refresh);pilotRow->addWidget(stopJob);layout->addLayout(pilotRow);
    jobs = new QPlainTextEdit(this);jobs->setReadOnly(true);jobs->setObjectName("aiJobs");jobs->setMaximumHeight(65);layout->addWidget(jobs);
    jobs->setPlainText(tr("Choose the local pilot workspace to inspect supervised jobs. Remote GPU activity is not checked here."));
    connect(choosePilot, &QPushButton::clicked, this, [this] {
        const QString path = QFileDialog::getExistingDirectory(this, tr("Choose local pilot workspace (contains outputs and work)"));
        if (!path.isEmpty()) loadPilot(path);
    });
    connect(refresh, &QPushButton::clicked, this, [this] { refreshJobs(); });
    connect(stopJob, &QPushButton::clicked, this, [this] { requestJobStop(); });
    const QString pilot = QSettings().value("yerbasAI/pilotWorkspace").toString();
    if (!pilot.isEmpty()) loadPilot(pilot);
    auto* agentRow = new QHBoxLayout;
    auto* selectAgent = new QPushButton(tr("Connect local agent…"), this);
    agentRefresh = new QPushButton(tr("Refresh agent"), this);agentRefresh->setEnabled(false);
    agentStop = new QPushButton(tr("Request stop through agent"), this);agentStop->setObjectName("aiAgentStop");agentStop->setEnabled(false);
    agentRow->addWidget(selectAgent);agentRow->addWidget(agentRefresh);agentRow->addWidget(agentStop);layout->addLayout(agentRow);
    agentConnection = new QLabel(tr("Local agent disconnected."), this);agentConnection->setObjectName("aiAgentConnection");agentConnection->setWordWrap(true);agentConnection->setTextFormat(Qt::PlainText);layout->addWidget(agentConnection);
    rewardSummary = new QLabel(tr("Testnet rewards: connect the local agent to read saved observations."), this);rewardSummary->setObjectName("aiRewardSummary");rewardSummary->setWordWrap(true);rewardSummary->setTextFormat(Qt::PlainText);rewardSummary->setTextInteractionFlags(Qt::TextSelectableByMouse);rewardSummary->setMargin(8);rewardSummary->setFrameStyle(QFrame::StyledPanel);layout->addWidget(rewardSummary);
    auto* showAgentDetails = new QPushButton(tr("Show connection details and history"), this);showAgentDetails->setObjectName("aiShowAgentDetails");showAgentDetails->setCheckable(true);layout->addWidget(showAgentDetails);
    agentStatus = new QPlainTextEdit(this);agentStatus->setObjectName("aiAgentStatus");agentStatus->setReadOnly(true);agentStatus->setMinimumHeight(120);agentStatus->setMaximumHeight(180);layout->addWidget(agentStatus);agentStatus->hide();
    connect(showAgentDetails, &QPushButton::toggled, this, [this, showAgentDetails](bool visible) { agentStatus->setVisible(visible);showAgentDetails->setText(visible ? tr("Hide connection details and history") : tr("Show connection details and history")); });
    agentStatus->setPlainText(tr("Local agent disconnected. Connect the installed provider agent to check jobs and start preassigned training."));
    auto* providerRow = new QHBoxLayout;
    providerRunInput = new QLineEdit(this);providerRunInput->setObjectName("aiProviderRun");providerRunInput->setPlaceholderText(tr("Local provider run ID"));providerRunInput->setMaxLength(32);
    providerRefresh = new QPushButton(tr("Check provider job"), this);providerRefresh->setObjectName("aiProviderRefresh");providerRefresh->setEnabled(false);
    providerStop = new QPushButton(tr("Stop provider job"), this);providerStop->setObjectName("aiProviderStop");providerStop->setEnabled(false);
    providerRow->addWidget(providerRunInput);providerRow->addWidget(providerRefresh);providerRow->addWidget(providerStop);layout->addLayout(providerRow);
    connect(providerRunInput, &QLineEdit::textChanged, this, [this] { providerStop->setEnabled(false);preparedDeadline=0;if(preparedDetails)preparedDetails->clear();updateProviderControls(); });
    auto* rewardRow = new QHBoxLayout();
    rewardReceipt=new QLineEdit(this);rewardReceipt->setObjectName("aiRewardReceipt");rewardReceipt->setPlaceholderText(tr("Completed contribution receipt ID"));rewardReceipt->setMaxLength(32);
    rewardRequest=new QPushButton(tr("Request testnet reward"),this);rewardRequest->setObjectName("aiRewardRequest");
    rewardCheck=new QPushButton(tr("Check request"),this);rewardCheck->setObjectName("aiRewardCheck");
    rewardRow->addWidget(rewardReceipt,1);rewardRow->addWidget(rewardRequest);rewardRow->addWidget(rewardCheck);layout->addLayout(rewardRow);
    rewardRequestStatus=new QLabel(tr("Reward requests unavailable until the connected agent supports them."),this);rewardRequestStatus->setObjectName("aiRewardRequestStatus");rewardRequestStatus->setWordWrap(true);rewardRequestStatus->setTextFormat(Qt::PlainText);layout->addWidget(rewardRequestStatus);
    connect(rewardReceipt,&QLineEdit::textChanged,this,[this]{
        rewardRequestStatus->setText(tr("Reward status not checked for this receipt. Enter a completed contribution receipt ID, then choose Check request."));
        updateRewardControls();
    });
    connect(rewardRequest,&QPushButton::clicked,this,[this]{agentRequest("rewards.request");});
    connect(rewardCheck,&QPushButton::clicked,this,[this]{agentRequest("rewards.status");});
    updateRewardControls();
    connect(providerRefresh, &QPushButton::clicked, this, [this] { agentRequest("provider.status"); });
    connect(providerStop, &QPushButton::clicked, this, [this] { agentRequest("provider.cancel"); });
    auto* submissionRow = new QHBoxLayout;
    providerContribution = new QLineEdit(this);providerContribution->setObjectName("aiContribution");providerContribution->setMaxLength(64);providerContribution->setPlaceholderText(tr("Preassigned contribution ID"));
    auto* loadJob = new QPushButton(tr("Load prepared job…"), this);loadJob->setObjectName("aiLoadJob");
    auto* newRun = new QPushButton(tr("New run ID"), this);
    providerSubmit = new QPushButton(tr("Start preassigned training"), this);providerSubmit->setObjectName("aiProviderSubmit");providerSubmit->setEnabled(false);
    submissionRow->addWidget(loadJob);submissionRow->addWidget(providerContribution);submissionRow->addWidget(newRun);submissionRow->addWidget(providerSubmit);layout->addLayout(submissionRow);
    preparedDetails=new QLabel(this);preparedDetails->setObjectName("aiPreparedDetails");preparedDetails->setWordWrap(true);preparedDetails->setTextFormat(Qt::PlainText);layout->addWidget(preparedDetails);
    connect(loadJob,&QPushButton::clicked,this,[this] {
        const QString path=QFileDialog::getOpenFileName(this,tr("Choose prepared training job"),QString(),tr("Job files (*.json)"));
        if(!path.isEmpty())loadPreparedJob(path);
    });
    auto* expiryTimer=new QTimer(this);expiryTimer->setInterval(1000);
    connect(expiryTimer,&QTimer::timeout,this,[this] { if(preparedDeadline)updateProviderControls(); });expiryTimer->start();
    layout->addWidget(new QLabel(tr("Fixed approved recipe only; bounded GPU runtime and simulated credits. A contribution must already be assigned to this computer."),this));
    connect(newRun,&QPushButton::clicked,this,[this] { if (agentRequestId.isEmpty()) providerRunInput->setText(QUuid::createUuid().toString(QUuid::Id128)); });
    connect(providerContribution,&QLineEdit::textChanged,this,[this] { preparedDeadline=0;preparedDetails->clear();updateProviderControls(); });
    connect(providerSubmit,&QPushButton::clicked,this,[this] { agentRequest("provider.submit"); });
    agentSocket = new QLocalSocket(this);agentDeadline = new QTimer(this);agentDeadline->setSingleShot(true);
    connect(selectAgent, &QPushButton::clicked, this, [this] {
        const QString path = QFileDialog::getExistingDirectory(this, tr("Choose local agent state folder (contains control.sock)"));
        if (!path.isEmpty()) connectAgent(path + "/control.sock");
    });
    connect(agentRefresh, &QPushButton::clicked, this, [this] { agentRequest("status"); });
    auto* statusPoll = new QTimer(this);statusPoll->setObjectName("aiStatusPoll");statusPoll->setInterval(60000);
    connect(statusPoll, &QTimer::timeout, this, [this] {
        if (isVisible() && agentRequestId.isEmpty() && !agentPath.isEmpty()
            && !providerRunInput->hasFocus() && !providerContribution->hasFocus()) agentRequest("status");
    });
    statusPoll->start();
    agentRefresh->setToolTip(tr("Refresh now. Status also refreshes once a minute while this page is visible and idle."));
    connect(agentStop, &QPushButton::clicked, this, [this] { agentRequest("jobs.cancel"); });
    connect(agentDeadline, &QTimer::timeout, this, [this] { agentFailure(); });
    connect(agentSocket, &QLocalSocket::errorOccurred, this, [this](QLocalSocket::LocalSocketError) { if (!agentRequestId.isEmpty()) agentFailure(); });
    connect(agentSocket, &QLocalSocket::readyRead, this, [this] { agentRead(); });
    connect(agentSocket, &QLocalSocket::connected, this, [this] {
#ifdef Q_OS_LINUX
        struct ucred peer; socklen_t size = sizeof(peer);
        if (::getsockopt(agentSocket->socketDescriptor(), SOL_SOCKET, SO_PEERCRED, &peer, &size) || peer.uid != ::geteuid()) { agentFailure();return; }
        QJsonObject params;
        if (agentMethod == "jobs.cancel") params.insert("run_id", agentRun);
        if (agentMethod.startsWith("provider.")) params.insert("run_id", providerRun);
        if (agentMethod == "provider.submit") params.insert("contribution",submissionContribution);
        if (agentMethod.startsWith("rewards.")) params.insert("receipt",requestedReceipt);
        QJsonObject request{{"v",1},{"id",agentRequestId},{"method",agentMethod},{"params",params}};
        agentSocket->write(QJsonDocument(request).toJson(QJsonDocument::Compact) + "\n");
#else
        agentFailure();
#endif
    });
    pythonCache = new QTemporaryDir();
    process = new QProcess(this);deadline = new QTimer(this);deadline->setSingleShot(true);
    connect(choose, &QPushButton::clicked, this, [this] {
        const QString path = QFileDialog::getExistingDirectory(this, tr("Choose extracted Yerbas AI model package"));
        if (!path.isEmpty()) loadPackage(path);
    });
    connect(generate, &QPushButton::clicked, this, [this] { startGeneration(); });
    connect(stop, &QPushButton::clicked, this, [this] { stopGeneration(); });
    connect(deadline, &QTimer::timeout, this, [this] {
        cancelled = true;status->setText(tr("Generation exceeded its time limit; stopping."));process->kill();
    });
    connect(process, &QProcess::readyReadStandardOutput, this, [this] { consumeOutput(); });
    connect(process, &QProcess::readyReadStandardError, this, [this] { process->readAllStandardError(); });
    connect(process, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart) { deadline->stop();setBusy(false);status->setText(tr("Could not start system Python 3. No model was run.")); }
    });
    connect(process, QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished), this, [this](int code, QProcess::ExitStatus exit) {
        consumeOutput();deadline->stop();setBusy(false);
        if (cancelled) { status->setText(tr("Generation stopped."));return; }
        const QJsonDocument doc = QJsonDocument::fromJson(response);
        if (exit != QProcess::NormalExit || code != 0 || !doc.isObject() || !doc.object().value("text").isString()) {
            status->setText(tr("Generation failed. Check the verified model folder and Python installation."));return;
        }
        output->setPlainText(doc.object().value("text").toString());status->setText(tr("Completed locally on CPU. No funds spent."));
    });
    const QString saved = QSettings().value("yerbasAI/modelPackage").toString();
    const QString bundled = QCoreApplication::applicationDirPath() + "/yerbas-ai-text-model-0.1.0";
    if (!saved.isEmpty()) loadPackage(saved);
    else if (QFileInfo(bundled).isDir()) loadPackage(bundled);
    const QString installedAgent = QStandardPaths::writableLocation(QStandardPaths::GenericDataLocation) + "/yerbas-ai-control-v1/state/control.sock";
    if (QFileInfo::exists(installedAgent)) connectAgent(installedAgent);
}

YerbasAIPage::~YerbasAIPage()
{
    disconnect(agentSocket, nullptr, this, nullptr);agentSocket->abort();
    disconnect(process, nullptr, this, nullptr);
    if (process->state() != QProcess::NotRunning) { process->kill();process->waitForFinished(1000); }
    delete pythonCache;
}

bool YerbasAIPage::loadPackage(const QString& directory)
{
    if (process->state() != QProcess::NotRunning) return false;
    verified = false;generate->setEnabled(false);details->clear();
    const QString root = QFileInfo(directory).canonicalFilePath();
    QByteArray manifest;
    auto fail = [this] { status->setText(tr("Model package is missing, modified or unsupported. Select the original Yerbas AI text-model 0.1.0 package."));return false; };
    if (root.isEmpty() || !readBounded(root + "/RELEASE.json", manifest, 65536) || QCryptographicHash::hash(manifest, QCryptographicHash::Sha256).toHex() != RELEASE_SHA256) return fail();
    const auto files = QJsonDocument::fromJson(manifest).object().value("files").toObject();
    for (auto i = files.begin(); i != files.end(); ++i) {
        const QFileInfo info(root + "/" + i.key());QByteArray bytes;
        if (info.isSymLink() || !info.canonicalFilePath().startsWith(root + "/") || !readBounded(info.filePath(), bytes, 16*1024*1024) || QCryptographicHash::hash(bytes, QCryptographicHash::Sha256).toHex() != i.value().toString().toLatin1()) return fail();
    }
    QDirIterator entries(root, QDir::AllEntries | QDir::Hidden | QDir::NoDotAndDotDot, QDirIterator::Subdirectories);
    while (entries.hasNext()) {
        entries.next();const auto info = entries.fileInfo();
        const QString relative = QDir(root).relativeFilePath(info.filePath());
        if (info.isSymLink()) return fail();
        if (info.isDir()) {
            if (relative != "runtime" && relative != "model" && relative != "source" && relative != "runtime/__pycache__") return fail();
        } else if (!files.contains(relative) && relative != "RELEASE.json") {
            // Existing Python cache files are ignored; execution uses a separate empty cache prefix.
            if (!relative.startsWith("runtime/__pycache__/") || !relative.endsWith(".pyc")) return fail();
        }
    }
    QByteArray metadata;
    if (!readBounded(root + "/model/model.json", metadata, 65536)) return fail();
    const auto model = QJsonDocument::fromJson(metadata).object();
    const auto evaluation = model.value("evaluation").toObject();
    const auto credits = model.value("simulated_credits").toObject();
    details->setText(tr("Accepted two-computer model • Step %1 • Held-out loss %2 bits/byte\nRecorded model-training earnings: %3 simulated credits • Historical model report")
        .arg(model.value("step").toInt()).arg(evaluation.value("heldout_bits_per_byte").toDouble(), 0, 'f', 3).arg(credits.value("earned").toInt()));
    packagePath->setText(root);QSettings().setValue("yerbasAI/modelPackage", root);verified = true;
    status->setText(tr("Verified model ready. Local prompts stay on this computer."));generate->setEnabled(true);return true;
}

void YerbasAIPage::setBusy(bool busy)
{
    choose->setEnabled(!busy);prompt->setEnabled(!busy);generate->setEnabled(!busy && verified);stop->setEnabled(busy);
}

void YerbasAIPage::startGeneration()
{
    if (process->state() != QProcess::NotRunning || !loadPackage(packagePath->text())) return;
    const QString text = prompt->toPlainText();
    if (text.toUtf8().isEmpty() || text.toUtf8().size() > 4096) { status->setText(tr("Enter a prompt of 1–4096 UTF-8 bytes."));return; }
    const QString python = QStandardPaths::findExecutable("python3");
    if (python.isEmpty()) { status->setText(tr("System Python 3 is not installed. No download was started."));return; }
    if (!pythonCache->isValid()) { status->setText(tr("Could not create isolated Python cache directory."));return; }
    cancelled = false;response.clear();output->clear();setBusy(true);status->setText(tr("Generating locally…"));
    process->setWorkingDirectory(packagePath->text());
    process->start(python, QStringList() << "-I" << "-B" << "-X" << "pycache_prefix=" + pythonCache->path() << packagePath->text() + "/generate.py" << "--prompt" << text << "--bytes" << "200" << "--json");
    deadline->start(35000);
}

void YerbasAIPage::stopGeneration()
{
    if (process->state() != QProcess::NotRunning) { cancelled = true;process->kill(); }
}

void YerbasAIPage::consumeOutput()
{
    response += process->readAllStandardOutput();
    if (response.size() > 65536) { response.clear();cancelled = true;process->kill(); }
}

void YerbasAIPage::loadPilot(const QString& directory)
{
    const QString canonical = QFileInfo(directory).canonicalFilePath();
    pilotPath->setText(canonical);
    if (!canonical.isEmpty()) QSettings().setValue("yerbasAI/pilotWorkspace", canonical);
    refreshJobs();
}

void YerbasAIPage::refreshJobs()
{
    displayedRun.clear();stopJob->setEnabled(false);
    QStringList lines;
    lines << tr("Snapshot taken %1. Refresh to update. Remote GPU activity is not checked.").arg(QDateTime::currentDateTime().toString(Qt::ISODate));
#ifdef Q_OS_UNIX
    PilotDirectory directory(pilotPath->text());
    const auto session = sessionSnapshot(directory.fd);
    if (session.isEmpty()) lines << tr("Supervised session unavailable (missing, unreadable or invalid local state).");
    else {
        const bool active = session.value("active").toBool();
        const QString run = session.value("run_id").toString();
        lines << tr("%1: %2 — %3").arg(active ? tr("Operator lock held") : tr("Historical session; operator lock released"), run, session.value("phase").toString());
        lines << tr("Last update: %1; provider: %2").arg(QDateTime::fromSecsSinceEpoch(session.value("updated_at").toInteger()).toString(Qt::ISODate), session.value("provider").toString().left(80));
        if (active) { displayedRun = run;stopJob->setEnabled(true); }
    }
#else
    lines << tr("Supervised pilot session controls require POSIX/Linux.");
#endif
    lines << tr("Session status does not confirm GPU idle. Saved results below are historical reports, not a new audit.");
    const QString outputDir = pilotPath->text() + "/outputs";
    if (pilotPath->text().isEmpty() || QFileInfo(outputDir).isSymLink() || !QFileInfo(outputDir).isDir()) {
        lines << tr("Saved results unavailable.");jobs->setPlainText(lines.join("\n"));return;
    }
    QDirIterator entries(outputDir, QStringList() << "text-handoff-*.json", QDir::Files | QDir::NoSymLinks);
    QList<QFileInfo> results;
    static const QRegularExpression name("^text-handoff-([a-f0-9]{32})\\.json$");
    int scanned = 0;
    while (entries.hasNext() && scanned < 2048) {
        entries.next();++scanned;
        if (name.match(entries.fileName()).hasMatch()) results.append(entries.fileInfo());
    }
    std::sort(results.begin(), results.end(), [](const QFileInfo& a, const QFileInfo& b) { return a.lastModified() > b.lastModified(); });
    if (scanned == 2048) lines << tr("Directory scan limited to 2048 matching entries.");
    int shown = 0;
    for (const auto& file : results) {
        if (shown++ == 20) { lines << tr("Showing at most 20 saved results.");break; }
        QByteArray bytes;
        if (!readBounded(file.filePath(), bytes, 262144)) { lines << tr("Unreadable or oversized saved result.");continue; }
        const auto value = QJsonDocument::fromJson(bytes).object();
        const QString run = name.match(file.fileName()).captured(1);
        if (value.value("run_id").toString() != run || !value.value("passed").isBool()) { lines << tr("Invalid saved result: %1").arg(run);continue; }
        const QString state = value.value("passed").toBool() ? tr("reported passed") : (value.value("owner_stopped").toBool() ? tr("reported stopped") : tr("reported incomplete"));
        lines << tr("%1 | %2 | final step %3").arg(run, state).arg(value.value("final_step").toInt());
    }
    if (results.isEmpty()) lines << tr("No saved text job results.");
    jobs->setPlainText(lines.join("\n"));
}

void YerbasAIPage::requestJobStop()
{
#ifdef Q_OS_UNIX
    const QString expected = displayedRun;
    PilotDirectory directory(pilotPath->text());
    const auto current = sessionSnapshot(directory.fd);
    if (expected.isEmpty() || !current.value("active").toBool() || current.value("run_id").toString() != expected) {
        refreshJobs();jobs->appendPlainText(tr("Stop rejected: the displayed job is no longer the active session."));return;
    }
    const QByteArray temporary = (".wallet-stop-" + QUuid::createUuid().toString(QUuid::WithoutBraces)).toLatin1();
    const QByteArray target = (expected + ".stop").toLatin1();
    const QByteArray payload = QJsonDocument(QJsonObject{{"run_id", expected}, {"requested_at", double(QDateTime::currentSecsSinceEpoch())}}).toJson(QJsonDocument::Compact);
    const int fd = ::openat(directory.fd, temporary.constData(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    bool ok = false;
    if (fd >= 0) {
        ok = ::write(fd, payload.constData(), payload.size()) == payload.size() && ::fsync(fd) == 0;
        ::close(fd);
        if (ok) ok = ::renameat(directory.fd, temporary.constData(), directory.fd, target.constData()) == 0;
        if (!ok) ::unlinkat(directory.fd, temporary.constData(), 0);
    }
    stopJob->setEnabled(false);
    jobs->appendPlainText(ok ? tr("Stop requested for %1. Wait for the supervisor to finish; refresh to check. GPU shutdown is not confirmed.").arg(expected) : tr("Stop request could not be saved; no shutdown is confirmed."));
#endif
}

void YerbasAIPage::connectAgent(const QString& path)
{
    // An explicit selection may supersede automatic discovery reads. Preserve an
    // in-flight stop until its response or timeout makes the outcome visible.
    if (!agentRequestId.isEmpty()) {
        if (agentMethod == "jobs.cancel" || agentMethod == "provider.cancel" || agentMethod == "provider.submit") return;
        agentRequestId.clear();agentDeadline->stop();agentSocket->abort();
    }
    rewardRequestsReady=false;updateRewardControls();
    agentPath = path;agentRun.clear();submissionReady=false;providerStop->setEnabled(false);agentRequest("status");
}

bool YerbasAIPage::loadPreparedJob(const QString& path)
{
    if(!agentRequestId.isEmpty()) { agentStatus->appendPlainText(tr("Wait for the current agent request before loading a job."));return false; }
    QByteArray raw;QJsonObject job;
    if(readBounded(path,raw,8192))job=QJsonDocument::fromJson(raw).object();
    const QStringList required{"contribution","lease_until","provider","recipe","run_id","schema","simulated_credits_reserved"};
    const double lease=job.value("lease_until").toDouble(0);
    const bool valid=job.keys()==required && job.value("schema")==QJsonValue(1) && job.value("recipe")==QJsonValue("byte-context-mlp-v1") && job.value("simulated_credits_reserved")==QJsonValue(9)
        && QRegularExpression("^[a-f0-9]{32}$").match(job.value("run_id").toString()).hasMatch()
        && QRegularExpression("^[a-zA-Z0-9_-]{1,64}$").match(job.value("contribution").toString()).hasMatch()
        && job.value("provider").toString()==QSysInfo::machineHostName()
        && std::isfinite(lease) && std::floor(lease)==lease && lease>QDateTime::currentSecsSinceEpoch() && lease<=QDateTime::currentSecsSinceEpoch()+180;
    if(!valid) {
        preparedDeadline=0;providerRunInput->clear();providerContribution->clear();providerStop->setEnabled(false);
        preparedDetails->setText(tr("Job rejected: invalid, expired, or assigned to another computer. Prepare a fresh job for this provider."));updateProviderControls();return false;
    }
    const QSignalBlocker runBlock(providerRunInput), contributionBlock(providerContribution);
    providerRunInput->setText(job.value("run_id").toString());providerContribution->setText(job.value("contribution").toString());preparedDeadline=qint64(lease);
    providerStop->setEnabled(false);
    preparedDetails->setText(tr("Prepared for %1 • approved public-text recipe • 9 simulated credits reserved • start before %2. The coordinator verifies the assignment; loading starts nothing.").arg(job.value("provider").toString(),QDateTime::fromSecsSinceEpoch(preparedDeadline).toString(Qt::ISODate)));
    updateProviderControls();return true;
}

void YerbasAIPage::updateProviderControls()
{
    providerRefresh->setEnabled(agentRequestId.isEmpty() && !agentPath.isEmpty() && QRegularExpression("^[a-f0-9]{32}$").match(providerRunInput->text()).hasMatch());
    providerSubmit->setEnabled((!preparedDeadline || preparedDeadline>QDateTime::currentSecsSinceEpoch()) && submissionReady && agentRequestId.isEmpty() && !agentPath.isEmpty() && QRegularExpression("^[a-f0-9]{32}$").match(providerRunInput->text()).hasMatch() && QRegularExpression("^[a-zA-Z0-9_-]{1,64}$").match(providerContribution->text()).hasMatch());
}

void YerbasAIPage::updateRewardControls()
{
    const bool ready=rewardRequestsReady && agentRequestId.isEmpty() && !agentPath.isEmpty()
        && QRegularExpression("^[a-f0-9]{32}$").match(rewardReceipt->text()).hasMatch();
    rewardRequest->setEnabled(ready);rewardCheck->setEnabled(ready);
}

void YerbasAIPage::agentRequest(const QString& method)
{
    if (!agentRequestId.isEmpty() || agentPath.isEmpty()) return;
    if (method.startsWith("rewards.")) {
        if(!rewardRequest->isEnabled()) return;
        requestedReceipt=rewardReceipt->text();
        rewardRequestStatus->setText(tr("Contacting coordinator. No payment is being sent."));
    }
    if (method == "jobs.cancel" && agentRun.isEmpty()) return;
    if (method == "provider.submit") {
        if (!providerSubmit->isEnabled() || (preparedDeadline && preparedDeadline<=QDateTime::currentSecsSinceEpoch())) return;
        submissionContribution=providerContribution->text();
        submissionKey="yerbasAI/providerSubmit/"+QString::fromLatin1(QCryptographicHash::hash((agentPath+":"+providerRunInput->text()).toUtf8(),QCryptographicHash::Sha256).toHex());
        QSettings settings;
        const QString previous=settings.value(submissionKey+"/contribution").toString();
        if (!previous.isEmpty() && previous!=submissionContribution) { agentStatus->setPlainText(tr("This run ID is already bound to another contribution. Check its status or choose a new run ID."));return; }
    }
    if (method.startsWith("provider.")) {
        if (!QRegularExpression("^[a-f0-9]{32}$").match(providerRunInput->text()).hasMatch()) return;
        if (method == "provider.cancel" && (providerRun != providerRunInput->text() || !providerStop->isEnabled())) return;
        providerRun = providerRunInput->text();
        providerStopKey = "yerbasAI/providerStop/" + QString::fromLatin1(QCryptographicHash::hash((agentPath + ":" + providerRun).toUtf8(), QCryptographicHash::Sha256).toHex());
    }
    agentSocket->abort();agentResponse.clear();agentMethod = method;
    agentRequestId = QUuid::createUuid().toString(QUuid::Id128);
    if (method == "provider.cancel") {
        QSettings settings;
        const QString pending = settings.value(providerStopKey).toString();
        if (QRegularExpression("^[a-f0-9]{32}$").match(pending).hasMatch()) agentRequestId = pending;
        settings.setValue(providerStopKey, agentRequestId);settings.sync();
        if (settings.status() != QSettings::NoError) { agentFailure();return; }
    }
    if (method == "provider.submit") {
        QSettings settings;const QString previous=settings.value(submissionKey+"/id").toString();
        if (QRegularExpression("^[a-f0-9]{32}$").match(previous).hasMatch()) agentRequestId=previous;
        settings.setValue(submissionKey+"/id",agentRequestId);settings.setValue(submissionKey+"/contribution",submissionContribution);settings.sync();
        if (settings.status()!=QSettings::NoError) { agentFailure();return; }
    }
    updateRewardControls();rewardReceipt->setEnabled(false);
    providerSubmit->setEnabled(false);providerContribution->setEnabled(false);
    providerRefresh->setEnabled(false);providerStop->setEnabled(false);providerRunInput->setEnabled(false);
    agentRefresh->setEnabled(false);agentStop->setEnabled(false);
    if (method == "status") agentStatus->setPlainText(tr("Connecting to local agent…"));
    agentDeadline->start(4000);agentSocket->connectToServer(agentPath);
}

void YerbasAIPage::agentFailure()
{
    rewardRequestsReady=false;rewardReceipt->setEnabled(true);updateRewardControls();
    if(agentMethod.startsWith("rewards.")) rewardRequestStatus->setText(tr("Request outcome unknown. Refresh the agent, then check the same receipt before retrying."));
    agentRequestId.clear();agentDeadline->stop();agentSocket->abort();agentRun.clear();
    providerContribution->setEnabled(true);providerRunInput->setEnabled(true);providerStop->setEnabled(false);updateProviderControls();
    agentRefresh->setEnabled(!agentPath.isEmpty());agentStop->setEnabled(false);
    agentConnection->setText(tr("Local agent unavailable — refresh to reconnect."));
    rewardSummary->setText(tr("Testnet rewards: current observation unavailable. Refresh the agent to check again."));
    agentStatus->setPlainText(tr("Agent unavailable, unauthorized or invalid response. GPU state is unknown. A lost stop response may still have recorded the request; refresh before further action."));
}

void YerbasAIPage::agentRead()
{
    agentResponse += agentSocket->readAll();
    if (agentResponse.size() > 32768) { agentFailure();return; }
    if (!agentResponse.contains('\n')) return;
    if (!agentResponse.endsWith('\n') || agentResponse.count('\n') != 1) { agentFailure();return; }
    const auto doc = QJsonDocument::fromJson(agentResponse);
    const auto value = doc.object();
    if (!doc.isObject() || value.value("v").toInt() != 1 || value.value("id").toString() != agentRequestId || !value.value("ok").isBool()) { agentFailure();return; }
    agentRequestId.clear();agentDeadline->stop();agentSocket->abort();agentRefresh->setEnabled(true);rewardReceipt->setEnabled(true);updateRewardControls();providerContribution->setEnabled(true);providerRunInput->setEnabled(true);updateProviderControls();
    if (!value.value("ok").toBool()) {
        if(agentMethod.startsWith("rewards.")) rewardRequestStatus->setText(tr("Request rejected: %1").arg(value.value("error").toObject().value("code").toString().left(80)));
        agentRun.clear();agentStop->setEnabled(false);agentStatus->appendPlainText(tr("Agent rejected request: %1").arg(value.value("error").toObject().value("code").toString().left(80)));return;
    }
    const auto result = value.value("result").toObject();
    if (agentMethod.startsWith("rewards.")) {
        if(result.value("receipt").toString()!=requestedReceipt || !result.contains("request")) {agentFailure();return;}
        if(result.value("request").isNull()) {
            if(agentMethod!="rewards.status") {agentFailure();return;}
            rewardRequestStatus->setText(tr("No reward request recorded for this receipt."));return;
        }
        const auto request=result.value("request").toObject();
        const auto message=requestStatusText(request,requestedReceipt,QSysInfo::machineHostName(),QDateTime::currentSecsSinceEpoch());
        if(message.isEmpty()) {agentFailure();return;}
        rewardRequestStatus->setText(message);
    } else if (agentMethod == "provider.submit") {
        if (result.value("run_id").toString()!=providerRun || result.value("request_recorded")!=QJsonValue(true) || result.value("training_started")!=QJsonValue(false)) { agentFailure();return; }
        agentStatus->setPlainText(tr("Submission recorded for %1. Check provider job for execution status; training completion is not yet confirmed.").arg(providerRun));
        providerSubmit->setEnabled(false);
    } else if (agentMethod == "provider.status") {
        const QString state = result.value("state").toString();
        const QStringList states{"queued","dispatching","running","stop_requested","uncertain","completed","failed","cancelled"};
        if (result.value("id").toString() != providerRun || !states.contains(state)) { agentFailure();return; }
        agentStatus->setPlainText(tr("Local provider job %1: %2. GPU activity is not independently measured.").arg(providerRun,state));
        providerStop->setEnabled(QStringList{"queued","dispatching","running","stop_requested","uncertain"}.contains(state));
    } else if (agentMethod == "provider.cancel") {
        if (result.value("run_id").toString() != providerRun || result.value("stop_recorded") != QJsonValue(true) || !result.value("shutdown_confirmed").isBool()) { agentFailure();return; }
        QSettings settings;settings.remove(providerStopKey);settings.sync();
        agentStatus->setPlainText(result.value("shutdown_confirmed").toBool() ? tr("Provider reports job %1 is terminal. Check job status for its final outcome.").arg(providerRun) : tr("Stop recorded for %1. Check provider job until shutdown completes.").arg(providerRun));
        providerStop->setEnabled(false);
    } else if (agentMethod == "status") {
        rewardRequestsReady=result.value("reward_requests_ready")==QJsonValue(true);updateRewardControls();
        submissionReady = result.value("submission_ready")==QJsonValue(true);
        const auto session = result.value("session").toObject();
        agentRun.clear();
        if (session.value("available").toBool() && session.value("active").toBool() && QRegularExpression("^[a-f0-9]{32}$").match(session.value("run_id").toString()).hasMatch()) agentRun = session.value("run_id").toString();
        agentConnection->setText(tr("Local agent connected • checked %1").arg(QDateTime::currentDateTime().toString("hh:mm:ss")));
        agentStatus->setPlainText(tr("Connected to owner-authorized local agent (protocol 1). Snapshot: %1").arg(QDateTime::currentDateTime().toString(Qt::ISODate)));
        agentStatus->appendPlainText(session.value("available").toBool() ? tr("%1 | %2 | %3").arg(agentRun.isEmpty() ? tr("Historical operator session") : tr("Operator lock held"), session.value("run_id").toString().left(32),session.value("phase").toString().left(80)) : tr("Operator session unavailable."));
        const auto provider = result.value("provider_broker").toObject();
        if (provider.value("available").toBool() && provider.value("authenticated_root").toBool()) {
            agentStatus->appendPlainText(provider.value("submissions_enabled").toBool()
                ? (submissionReady ? tr("Protected provider connected. Preassigned training submission is enabled.") : tr("Protected provider service connected. Wallet submission is not enabled yet."))
                : tr("Protected provider service connected. GPU submissions are disabled."));
        } else {
            agentStatus->appendPlainText(tr("Protected provider service unavailable or unverified."));
        }
        const auto identity = result.value("wallet_identity").toObject();
        const QString identityAddress = identity.value("address").toString();
        const qint64 checkedAt = identity.value("checked_at").toInteger();
        if (identity.value("available")==QJsonValue(true) && identity.value("historical")==QJsonValue(true)
            && identity.value("live_authorization")==QJsonValue(false)
            && identity.value("provider").toString()==QSysInfo::machineHostName()
            && QRegularExpression("^[1-9A-HJ-NP-Za-km-z]{26,50}$").match(identityAddress).hasMatch()
            && identity.value("active").isBool() && identity.value("required").isBool()
            && checkedAt>0 && checkedAt<=QDateTime::currentSecsSinceEpoch()) {
            agentStatus->appendPlainText(tr("Testnet wallet identity: %1").arg(identityAddress));
            agentStatus->appendPlainText(tr("Saved coordinator check: %1 — %2. This is not live authorization.")
                .arg(QDateTime::fromSecsSinceEpoch(checkedAt).toString(Qt::ISODate),
                     identity.value("active").toBool() && identity.value("required").toBool() ? tr("identity active and required") : tr("identity inactive or not required")));
        } else {
            agentStatus->appendPlainText(tr("Testnet wallet identity: no valid saved coordinator check. The coordinator checks authorization when a job runs."));
        }
        rewardSummary->setText(walletRewardLines(result.value("wallet_rewards").toObject(), identityAddress, QSysInfo::machineHostName(), QDateTime::currentSecsSinceEpoch()).join("\n"));
        for (const auto& line : walletRewardLines(result.value("wallet_rewards").toObject(), identityAddress, QSysInfo::machineHostName(), QDateTime::currentSecsSinceEpoch())) agentStatus->appendPlainText(line);
        agentStatus->appendPlainText(tr("Remote GPU activity is unchecked. This page cannot send rewards."));
        agentRequest("jobs.list");
    } else if (agentMethod == "jobs.list") {
        const auto rows = result.value("jobs").toArray();
        if (rows.size() > 20) { agentFailure();return; }
        agentStatus->appendPlainText(tr("Historical reports: %1 (not a new audit)").arg(rows.size()));
        for (const auto& row : rows) {
            const auto job = row.toObject();
            agentStatus->appendPlainText(job.value("run_id").toString().left(32) + " | " + (job.value("reported_passed").toBool() ? tr("reported passed") : tr("reported incomplete/stopped")));
        }
        agentStop->setEnabled(!agentRun.isEmpty());
    } else if (agentMethod == "jobs.cancel") {
        if (result.value("run_id").toString() != agentRun || !result.value("stop_requested").toBool()) { agentFailure();return; }
        agentStatus->appendPlainText(tr("Stop request recorded for %1. Refresh to check supervisor completion; GPU shutdown is not confirmed.").arg(agentRun));
        agentStop->setEnabled(false);
    }
}
