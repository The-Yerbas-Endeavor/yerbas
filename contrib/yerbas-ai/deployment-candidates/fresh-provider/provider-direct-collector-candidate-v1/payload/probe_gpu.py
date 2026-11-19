"""Disposable verified-HTTPS GPU job and lost-ack recovery; no live ledger."""
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import uuid
from direct_attempt import run
from direct_evidence import bind
from sustained_training import atomic_json
from text_neural import identity
from text_worker import run_once
from text_https import Client, create_server
from text_credits import ContributionStore

EXPECTED='b45353d27546bcb88b6fe77c973a1a29b973868da79d1f6abe1161377a2a93fe'

def exercise(base, private, run_id, *, executor=run):
    approved=identity(base/'dataset');provider=socket.gethostname();gpu=os.environ['CUDA_VISIBLE_DEVICES']
    store=ContributionStore(private/'disposable-ledger.sqlite3');store.register(provider);store.fund('test-buyer',9)
    store.create('isolated-chain',approved,6000);store.assign('isolated-chain','isolated-job',provider,6000,buyer='test-buyer',amount=9)
    token=uuid.uuid4().hex;cert=private/'cert.pem';key=private/'key.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1',
        '-subj','/CN=isolated-test','-addext','subjectAltName=IP:127.0.0.1'],check=True,capture_output=True)
    server=create_server(store,{hashlib.sha256(token.encode()).hexdigest():provider},str(cert),str(key))
    thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.05});thread.start()
    stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,lambda *_:stop.set())
    executions=[];attempt=private/'attempt';attempt.mkdir(mode=0o700)
    def execute(m,state,remaining,stop,guard):
        executions.append(m['contribution'])
        atomic_json(attempt/'start.json',dict(schema=1,attempt_id=run_id,manifest=m,physical_gpu=gpu,start_step=0,initial_checkpoint_sha256=None))
        executor(base/'dataset',state,attempt,6000,min(100,int(remaining)),stop=stop,check=guard.check)
    def lose_ack(stage):
        if stage=='after_receipt_response':raise RuntimeError('injected lost acknowledgement')
    try:
        client=Client('https://127.0.0.1:'+str(server.server_port),token,str(cert))
        args=(private/'worker',client,provider,'isolated-job','disposable-origin',approved,execute,stop)
        try:run_once(*args,_fault=lose_ack)
        except RuntimeError as exc:
            if str(exc)!='injected lost acknowledgement':raise
        else:raise ValueError('Lost-ack injection did not execute')
        receipt=run_once(*args);again=run_once(*args)
        if receipt!=again or executions!=['isolated-job']:raise ValueError('Replay repeated execution or changed receipt')
        if receipt['sha256']!=EXPECTED:raise ValueError('Final model differs')
        start=json.loads((attempt/'start.json').read_text());measurement=json.loads((attempt/'measurement.json').read_text())
        report=json.loads((attempt/'report.json').read_text());evidence=bind(start,measurement,report,receipt)
        audit=store.audit()
        if audit['settlements']!=1 or audit['totals']!=dict(funded=9,available=0,reserved=0,earned=9):raise ValueError('Duplicate or unreconciled settlement')
        result=dict(steps=6000,kernel_records=measurement['direct']['kernel_records'],transcript_valid=True,known_checkpoint_matches=True,
            scope='isolated loopback HTTPS GPU executor and lost-ack replay; not live deployment or two-host network acceptance',
            receipt=receipt,evidence=evidence,executions=len(executions),lost_ack_recovered=True,duplicate_replay_matches=True,
            disposable_accounting=audit,observed_kernel_union_ns=measurement['direct']['observed_kernel_union_ns'],
            live_contribution_created=False,capture_completeness_verified=False,calibration_verified=False,reward_eligible=False)
        atomic_json(private/'result.json',result)
        return result
    finally:
        server.shutdown();server.server_close();thread.join()

if __name__=='__main__':
    base,private,cupti,run_id,runtime=sys.argv[1:]
    print(json.dumps(exercise(Path(base),Path(private),run_id),indent=2))
