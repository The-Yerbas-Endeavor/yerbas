// Copyright (c) 2018-2019 The Dash Core developers
// Copyright (c) 2020 The Yerbas developers
// Distributed under the MIT/X11 software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include "quorums_init.h"
#include "quorums_pose.h"

#include "quorums.h"
#include "quorums_blockprocessor.h"
#include "quorums_commitment.h"
#include "quorums_chainlocks.h"
#include "quorums_debug.h"
#include "quorums_dkgsessionmgr.h"
#include "quorums_instantsend.h"
#include "quorums_signing.h"
#include "quorums_signing_shares.h"

#include "dbwrapper.h"
#include "scheduler.h"

namespace llmq
{

CBLSWorker* blsWorker;

CDBWrapper* llmqDb;

void InitLLMQSystem(CEvoDB& evoDb, CScheduler* scheduler, bool unitTests, bool fWipe)
{
    llmqDb = new CDBWrapper(unitTests ? "" : (GetDataDir() / "llmq"), 1 << 20, unitTests, fWipe);
    blsWorker = new CBLSWorker();

    quorumDKGDebugManager = new CDKGDebugManager();
    quorumBlockProcessor = new CQuorumBlockProcessor(evoDb);
    quorumDKGSessionManager = new CDKGSessionManager(*llmqDb, *blsWorker);
    quorumManager = new CQuorumManager(evoDb, *blsWorker, *quorumDKGSessionManager);
    quorumSigSharesManager = new CSigSharesManager();
    quorumSigningManager = new CSigningManager(*llmqDb, unitTests);
    poseManager = new CPoSeManager(*llmqDb);
    chainLocksHandler = new CChainLocksHandler(scheduler);
    quorumInstantSendManager = new CInstantSendManager(*llmqDb);
}

void DestroyLLMQSystem()
{
    delete quorumInstantSendManager;
    quorumInstantSendManager = nullptr;
    delete chainLocksHandler;
    chainLocksHandler = nullptr;
    delete poseManager;
    poseManager = nullptr;
    delete quorumSigningManager;
    quorumSigningManager = nullptr;
    delete quorumSigSharesManager;
    quorumSigSharesManager = nullptr;
    delete quorumManager;
    quorumManager = nullptr;
    delete quorumDKGSessionManager;
    quorumDKGSessionManager = nullptr;
    delete quorumBlockProcessor;
    quorumBlockProcessor = nullptr;
    delete quorumDKGDebugManager;
    quorumDKGDebugManager = nullptr;
    delete blsWorker;
    blsWorker = nullptr;
    delete llmqDb;
    llmqDb = nullptr;
}

void StartLLMQSystem()
{
    if (quorumSigningManager && poseManager) quorumSigningManager->RegisterRecoveredSigsListener(poseManager);
    //quorumBlockProcessor->UpgradeDB();

    if (blsWorker) {
        blsWorker->Start();
    }
    if (quorumDKGSessionManager) {
        quorumDKGSessionManager->StartMessageHandlerPool();
    }
    if (quorumSigSharesManager) {
        quorumSigSharesManager->RegisterAsRecoveredSigsListener();
        quorumSigSharesManager->StartWorkerThread();
    }
    if (chainLocksHandler) {
        chainLocksHandler->Start();
    }
    if (quorumInstantSendManager) {
        quorumInstantSendManager->Start();
    }
}

void StopLLMQSystem()
{
    if (quorumSigningManager && poseManager) quorumSigningManager->UnregisterRecoveredSigsListener(poseManager);
    if (quorumInstantSendManager) {
        quorumInstantSendManager->Stop();
    }
    if (chainLocksHandler) {
        chainLocksHandler->Stop();
    }
    if (quorumSigSharesManager) {
        quorumSigSharesManager->StopWorkerThread();
        quorumSigSharesManager->UnregisterAsRecoveredSigsListener();
    }
    if (quorumDKGSessionManager) {
        quorumDKGSessionManager->StopMessageHandlerPool();
    }
    if (blsWorker) {
        blsWorker->Stop();
    }
}

void InterruptLLMQSystem()
{
    if (quorumSigSharesManager) {
        quorumSigSharesManager->InterruptWorkerThread();
    }
    if (quorumInstantSendManager) {
        quorumInstantSendManager->InterruptWorkerThread();
    }
}

} // namespace llmq
