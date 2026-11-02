"""Durable schema-4 text worker engine with injected approved executor; no GPU CLI yet."""
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from text_contribution import validate_manifest,verify_result
from text_contribution import decode
from sustained_training import atomic_json
from network_training_worker import OwnerStopped,CoordinatorGuard


def atomic_bytes(path,raw):
    temporary=path.with_suffix('.download')
    with temporary.open('wb') as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def validate_assignment(a,provider,contribution,approved_identity):
    if type(a) is not dict or set(a)!={'manifest','lease_until'}:raise ValueError('Invalid assignment')
    m=validate_manifest(a['manifest'])
    if m['provider']!=provider or m['contribution']!=contribution or m['identity']!=approved_identity:raise ValueError('Assignment identity is not approved')
    if type(a['lease_until']) not in (int,float) or not math.isfinite(a['lease_until']):raise ValueError('Invalid lease')


def run_once(directory,client,provider,contribution,origin_identity,approved_identity,execute,stop,clock=time.time,_fault=lambda stage:None,*,result_only=False):
    """execute(manifest,state,remaining,stop,guard) must enforce stop/budget/guard.

    approved_identity must be established from local approved recipe/data bytes by
    the caller, never copied blindly from the assignment. No arbitrary-code loader.
    """
    directory=Path(directory);directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (directory/'worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        path=directory/'journal.json'
        binding={'origin':origin_identity,'provider':provider,'contribution':contribution,'approved_identity':approved_identity}
        if path.exists():
            j=json.loads(path.read_text())
            if j['binding']!=binding:raise ValueError('Worker identity changed')
        else:
            if result_only:raise ValueError('Result-only recovery requires a retained journal')
            j={'binding':binding,'phase':'assignment'};atomic_json(path,j)
        def check_stop():
            if stop.is_set():raise OwnerStopped('Owner stopped contribution; state retained')
        def now():
            value=clock()
            if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('Invalid clock')
            return value
        if result_only:
            if j['phase'] not in ('result_ready','acknowledged'):raise ValueError('Result-only recovery cannot execute training')
            # Revalidate and replay even a locally cached acknowledgement. Do not
            # rewrite the durable phase until a matching remote receipt returns.
            j=dict(j,phase='result_ready')
        elif j['phase']=='acknowledged':return j['receipt']
        check_stop()
        if j['phase']=='assignment':
            a=client.assignment(contribution);validate_assignment(a,provider,contribution,approved_identity)
            _fault('after_assignment_response')
            j.update(assignment=a,phase='parent',runtime_deadline=min(now()+a['manifest']['max_runtime_seconds'],a['lease_until']-20))
            atomic_json(path,j)
        a=j['assignment'];validate_assignment(a,provider,contribution,approved_identity);m=a['manifest']
        if type(j.get('runtime_deadline')) not in (int,float) or not math.isfinite(j['runtime_deadline']) or j['runtime_deadline']>a['lease_until']-20:
            raise ValueError('Invalid retained runtime deadline')
        state=directory/'training';state.mkdir(mode=0o700,exist_ok=True)
        artifact=state/'checkpoint.json';parent_path=directory/'parent.json'
        def read(p):
            with p.open('rb') as stream:raw=stream.read(m['max_artifact_bytes']+1)
            if not 0<len(raw)<=m['max_artifact_bytes']:raise ValueError('Checkpoint size invalid')
            return raw
        def active():
            check_stop()
            if now()>=j['runtime_deadline']:raise ValueError('Contribution runtime budget exhausted')
            value=client.status(contribution)
            if value!={'contribution':contribution,'state':'active','lease_until':a['lease_until']}:
                raise ValueError('Contribution no longer authorized under original lease')
        parent=None
        if m['start_step']:
            if parent_path.exists():parent=read(parent_path)
            elif j['phase']=='parent':
                active();parent=client.parent(m,stop=stop,timeout=min(90,j['runtime_deadline']-now()))
                check_stop();_fault('after_parent_response')
                if hashlib.sha256(parent).hexdigest()!=m['parent_sha256']:raise ValueError('Parent changed')
                atomic_bytes(parent_path,parent);_fault('after_parent_saved')
            else:raise ValueError('Retained parent missing')
            if hashlib.sha256(parent).hexdigest()!=m['parent_sha256']:raise ValueError('Retained parent changed')
            bundle=decode(parent,m['identity'])
            if bundle['latest']['step']!=m['start_step'] or bundle['target_step']!=m['target_step'] or bundle['selection']['stopped']:
                raise ValueError('Parent conflicts with assignment')
        elif parent_path.exists():raise ValueError('Unexpected initial parent')
        if j['phase']=='parent':
            active()
            if artifact.exists():
                if parent is None or read(artifact)!=parent:raise ValueError('Unexpected unjournaled checkpoint')
            elif parent is not None:atomic_bytes(artifact,parent)
            j['phase']='training';atomic_json(path,j);_fault('after_parent_seeded')
        if j['phase']=='training':
            active();complete=False
            if artifact.exists():
                raw=read(artifact);bundle=decode(raw,m['identity']);step=bundle['latest']['step']
                if step==m['start_step']:
                    if parent is None or raw!=parent:raise ValueError('Initial training checkpoint differs from parent')
                else:
                    partial=dict(m);partial['end_step']=step
                    if step>m['end_step']:raise ValueError('Checkpoint exceeds segment')
                    verify_result(partial,raw,parent)
                    complete=step==m['end_step'] or bundle['selection']['stopped']
            if not complete:
                class Adapter:
                    def status(self,_):
                        v=client.status(contribution)
                        if type(v) is not dict or set(v)!={'contribution','state','lease_until'} or v['contribution']!=contribution:raise ValueError('Invalid contribution status')
                        return {'assignment':v['contribution'],'state':v['state'],'lease_until':v['lease_until']}
                guard=CoordinatorGuard(Adapter(),{'assignment':contribution,'lease_until':a['lease_until']})
                remaining=j['runtime_deadline']-now()
                if remaining<=0:raise ValueError('Contribution runtime budget exhausted')
                execute(m,state,remaining,stop,guard);check_stop()
                if now()>=j['runtime_deadline']:raise ValueError('Executor exceeded runtime deadline')
            raw=read(artifact);result=verify_result(m,raw,parent)
            j.update(phase='result_ready',sha256=result['sha256']);atomic_json(path,j);_fault('after_result_ready')
        if j['phase']!='result_ready':raise ValueError('Unknown worker phase')
        check_stop();raw=read(artifact)
        if hashlib.sha256(raw).hexdigest()!=j['sha256']:raise ValueError('Retained result changed')
        # Stable receipt replay is allowed after lease expiry; never repeat execution.
        receipt=client.submit(m,raw);_fault('after_receipt_response')
        if (type(receipt) is not dict or set(receipt)!={'receipt','sha256','contribution'} or receipt['sha256']!=j['sha256']
            or receipt['contribution']!=contribution or type(receipt['receipt']) is not str or not re.fullmatch('[a-f0-9]{32}',receipt['receipt'])):
            raise ValueError('Receipt does not match result')
        j.update(phase='acknowledged',receipt=receipt);atomic_json(path,j)
        return receipt
