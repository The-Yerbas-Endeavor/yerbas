"""One bounded HTTPS training assignment with a durable private retry journal."""
import argparse
import fcntl
import hashlib
import json
import math
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid
import selected_checkpoint as selected
import recovery_checkpoint_v2 as selected_v2
from sustained_training import atomic_json
from training_https import Client


class OwnerStopped(Exception):pass


def validate_assignment(a,provider):
    import re
    if type(a) is not dict or set(a)!={'assignment','job','provider','lease_until','state','recipe','max_steps','max_runtime_seconds','max_artifact_bytes'}:
        raise ValueError('Invalid assignment fields')
    if not isinstance(a['assignment'],str) or not re.fullmatch('[a-f0-9]{32}',a['assignment']):raise ValueError('Invalid assignment ID')
    if not isinstance(a['job'],str) or not re.fullmatch('[a-zA-Z0-9_-]{1,64}',a['job']):raise ValueError('Invalid job ID')
    if a['provider']!=provider or a['recipe'] not in ('validation-v1','validation-v2') or a['state']!='active':raise ValueError('Assignment not runnable')
    for name,low,high in [('max_steps',500,10000),('max_runtime_seconds',1,120),('max_artifact_bytes',1,selected.MAX_BYTES)]:
        if type(a[name]) is not int or not low<=a[name]<=high:raise ValueError('Invalid assignment bound')
    if type(a['lease_until']) not in (int,float) or not math.isfinite(a['lease_until']):raise ValueError('Invalid lease')


def checkpoint_spec(a):
    if a['recipe']=='validation-v1':return selected,'selection.json'
    if a['recipe']=='validation-v2':return selected_v2,'recovery-v2.json'
    raise ValueError('Unknown recipe')


def load_checkpoint(a,state):
    module,name=checkpoint_spec(a)
    other='selection.json' if name=='recovery-v2.json' else 'recovery-v2.json'
    if (state/other).exists():raise ValueError('Checkpoint recipe conflict; no implicit migration')
    bundle=module.load(state/name) if (state/name).exists() else None
    if bundle is not None and a['recipe']=='validation-v2' and bundle['target_step']!=a['max_steps']:
        raise ValueError('Checkpoint target differs from assignment')
    return bundle


def completed(bundle,a):
    step=bundle['latest']['step']
    if step>a['max_steps']:raise ValueError('Training exceeded assignment step bound')
    return bundle['selection']['stopped'] or step==a['max_steps']


def run_once(directory,client,provider,identity,execute,stop,clock=time.time,_fault=lambda stage:None):
    directory=Path(directory);directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (directory/'worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        path=directory/'journal.json'
        if path.exists():
            journal=json.loads(path.read_text())
            if journal['identity']!=identity:raise ValueError('Coordinator identity changed; refusing journal reuse')
        else:
            journal={'identity':identity,'request_id':uuid.uuid4().hex,'phase':'claiming'}
            atomic_json(path,journal)
        def check_stop():
            if stop.is_set():raise OwnerStopped('Owner requested stop; journal retained')
        if journal['phase']=='acknowledged':return journal['receipt']
        check_stop()
        if journal['phase']=='claiming':
            a=client.claim(journal['request_id']);_fault('after_claim_response')
            if a is None:return None
            validate_assignment(a,provider)
            journal.update(assignment=a,phase='assigned');atomic_json(path,journal)
        a=journal['assignment'];validate_assignment(a,provider)
        state=directory/'training';state.mkdir(mode=0o700,exist_ok=True)
        artifact=state/checkpoint_spec(a)[1]
        if journal['phase'] in ('assigned','training'):
            check_stop()
            if clock()>=a['lease_until']-20:raise ValueError('Insufficient lease time to train; journal retained')
            bundle=load_checkpoint(a,state)
            if bundle is None or not completed(bundle,a):
                if 'runtime_deadline' not in journal:
                    journal['runtime_deadline']=min(clock()+a['max_runtime_seconds'],a['lease_until']-20)
                remaining=journal['runtime_deadline']-clock()
                if remaining<=0:raise ValueError('Training runtime budget exhausted')
                journal['phase']='training';atomic_json(path,journal)
                execute(a,state,remaining,stop)
                check_stop()
                bundle=load_checkpoint(a,state)
            if not completed(bundle,a):raise ValueError('Training did not complete assignment')
            with artifact.open('rb') as stream:raw=stream.read(a['max_artifact_bytes']+1)
            if len(raw)>a['max_artifact_bytes']:raise ValueError('Artifact exceeds assignment bound')
            journal.update(phase='result_ready',sha256=hashlib.sha256(raw).hexdigest())
            atomic_json(path,journal);_fault('after_result_ready')
        if journal['phase']!='result_ready':raise ValueError('Unknown journal phase')
        check_stop()
        with artifact.open('rb') as stream:raw=stream.read(a['max_artifact_bytes']+1)
        if len(raw)>a['max_artifact_bytes'] or hashlib.sha256(raw).hexdigest()!=journal['sha256']:
            raise ValueError('Retained result changed')
        receipt=client.submit(a['assignment'],raw);_fault('after_receipt_response')
        if type(receipt) is not dict or set(receipt)!={'receipt','sha256','job'} or receipt['sha256']!=journal['sha256'] or receipt['job']!=a['job']:
            raise ValueError('Receipt does not match submitted result')
        import re
        if type(receipt['receipt']) is not str or not re.fullmatch('[a-f0-9]{32}',receipt['receipt']):raise ValueError('Invalid receipt ID')
        journal.update(phase='acknowledged',receipt=receipt);atomic_json(path,journal)
        return receipt


class CoordinatorUnavailable(RuntimeError):pass


class CoordinatorGuard:
    """Poll in one daemon thread; never block owner-stop or runtime supervision."""
    def __init__(self,client,assignment,clock=time.monotonic):
        self.client=client;self.assignment=assignment;self.clock=clock
        self.pending=None;self.next_poll=0;self.started=0;self.error=None

    def check(self):
        now=self.clock()
        if self.pending is not None:
            if not self.pending.is_set():
                if now-self.started>=5:raise CoordinatorUnavailable('Coordinator status deadline exceeded')
                return
            if self.error is not None:raise CoordinatorUnavailable('Coordinator no longer authorizes training') from self.error
            self.pending=None;self.next_poll=now+2
        if now>=self.next_poll:
            self.started=now;self.pending=threading.Event();done=self.pending
            def poll():
                try:
                    value=self.client.status(self.assignment['assignment'])
                    if (type(value) is not dict or set(value)!={'assignment','state','lease_until'}
                        or value['assignment']!=self.assignment['assignment']
                        or value['state']!='active'
                        or type(value['lease_until']) not in (int,float)
                        or not math.isfinite(value['lease_until'])
                        or value['lease_until']!=self.assignment['lease_until']):
                        raise ValueError('Assignment inactive or status malformed')
                except Exception as exc:self.error=exc
                finally:done.set()
            threading.Thread(target=poll,daemon=True).start()


def execute_gpu(a,state,remaining,stop,guard=None):
    (state/'guard-failure.json').unlink(missing_ok=True)
    bundle=load_checkpoint(a,state)
    start=bundle['latest']['step'] if bundle else 0
    steps=a['max_steps']-start
    if steps<=0:raise ValueError('No training steps remain')
    if a['recipe']=='validation-v2':
        runner='validation_training_v2.py';arguments=['--target-step',str(a['max_steps'])]
    else:
        runner='validation_training.py';arguments=['--max-steps',str(steps)]
    command=['timeout','--signal=TERM','--kill-after=20s',str(max(.1,remaining))+'s',
             sys.executable,str(Path(__file__).with_name(runner)),
             '--state',str(state)]+arguments
    with (state/'runner.log').open('a') as log:
        process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        started=time.monotonic();failure=None
        try:
            while process.poll() is None:
                if stop.is_set():failure='owner stop';break
                if guard is not None:
                    try:guard.check()
                    except CoordinatorUnavailable as exc:failure=exc;break
                if time.monotonic()-started>=remaining:failure='runtime bound reached';break
                values=subprocess.check_output(['nvidia-smi','--id=0','--query-gpu=temperature.gpu','--format=csv,noheader,nounits'],text=True,timeout=10)
                if int(values.strip())>=80:failure='GPU reached 80 C';break
                time.sleep(.5)
        finally:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=20)
                except subprocess.TimeoutExpired:process.kill();process.wait()
        if stop.is_set():raise OwnerStopped('Owner stop; checkpoint retained')
        if isinstance(failure,CoordinatorUnavailable):
            atomic_json(state/'guard-failure.json',{'reason':'coordinator_unavailable','assignment':a['assignment']})
            raise failure
        if failure or process.returncode:raise RuntimeError(failure or 'GPU recipe failed; inspect runner.log')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True);parser.add_argument('--state',type=Path,required=True)
    args=parser.parse_args();config=json.loads(args.config.read_text())
    stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,lambda *_:stop.set())
    client=Client(config['url'],config['token'],config['ca'])
    identity=hashlib.sha256(json.dumps([config['url'],hashlib.sha256(config['token'].encode()).hexdigest(),
                                      hashlib.sha256(Path(config['ca']).read_bytes()).hexdigest(),config['provider']]).encode()).hexdigest()
    try:
        receipt=run_once(args.state,client,config['provider'],identity,
        lambda a,state,remaining,event:execute_gpu(a,state,remaining,event,CoordinatorGuard(client,a)),stop)
        print(json.dumps({'receipt':receipt,'completed':receipt is not None}),flush=True)
    except OwnerStopped as exc:raise SystemExit(str(exc))
