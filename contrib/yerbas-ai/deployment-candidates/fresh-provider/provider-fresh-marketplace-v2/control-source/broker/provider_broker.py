"""Durable request lifecycle for a future authenticated provider-service broker.

This module never starts processes. A provisioned transport supplies the kernel
peer UID; a narrow backend supplies start/stop/inspect for fixed service instances.
No production transport/backend is enabled by this module.
"""
import json
import hashlib
import time
import fcntl
import os
from pathlib import Path
import re
import sqlite3
import stat

ID=re.compile(r'[a-f0-9]{32}\Z')
CONTRIBUTION=re.compile(r'[a-zA-Z0-9_-]{1,64}\Z')
TERMINAL={'completed','failed','cancelled'}

class Rejected(ValueError):pass

def identifier(value):
    if not isinstance(value,str) or not ID.fullmatch(value):raise Rejected('invalid_id')
    return value

class Broker:
    def __init__(self,state,owner_uid,backend):
        if type(owner_uid) is not int or owner_uid<=0:raise Rejected('invalid_owner')
        self.owner_uid=owner_uid;self.backend=backend
        root=Path(state);root.mkdir(mode=0o700,parents=True,exist_ok=True)
        info=root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise Rejected('private_state_required')
        self.dispatch_path=root/'dispatcher.lock'
        path=root/'broker.sqlite3'
        fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise Rejected('unsafe_database')
        finally:os.close(fd)
        self.db=sqlite3.connect(path,isolation_level=None);self.db.row_factory=sqlite3.Row
        app=self.db.execute('PRAGMA application_id').fetchone()[0]
        tables=self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if app!=1497500491 and (app!=0 or tables):self.db.close();raise Rejected('separate_database_required')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA application_id=1497500491')
        self.db.execute('CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,body TEXT NOT NULL,response TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS rental_bindings(assignment TEXT PRIMARY KEY,run TEXT NOT NULL UNIQUE,provider TEXT NOT NULL,digest TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS run_fences(id TEXT PRIMARY KEY,request_id TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,mode TEXT NOT NULL,contribution TEXT NOT NULL,state TEXT NOT NULL)')
        self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_active ON jobs((1)) WHERE state NOT IN ('completed','failed','cancelled')")
    def close(self):self.db.close()
    def authorize(self,peer_uid):
        if type(peer_uid) is not int or peer_uid!=self.owner_uid:raise Rejected('unauthorized')
    def request(self,peer_uid,request_id,method,params):
        self.authorize(peer_uid);identifier(request_id)
        if not isinstance(params,dict):raise Rejected('invalid_params')
        if method=='submit_rental':
            if set(params)!={'run_id','contribution','assignment_id','provider','terms_sha256'}:raise Rejected('invalid_params')
            identifier(params['run_id']);identifier(params['assignment_id'])
            if params['contribution']!='text-'+params['run_id']:raise Rejected('invalid_contribution')
            if not isinstance(params['provider'],str) or not CONTRIBUTION.fullmatch(params['provider']):raise Rejected('invalid_provider')
            if not isinstance(params['terms_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',params['terms_sha256']):raise Rejected('invalid_digest')
        elif method=='submit':
            if set(params)!={'mode','run_id','contribution'} or params['mode'] not in ('train','replay','resume'):raise Rejected('invalid_params')
            identifier(params['run_id'])
            if not isinstance(params['contribution'],str) or not CONTRIBUTION.fullmatch(params['contribution']):raise Rejected('invalid_contribution')
        elif method in ('cancel','fence'):
            if set(params)!={'run_id'}:raise Rejected('invalid_params')
            identifier(params['run_id'])
        else:raise Rejected('unsupported_method')
        body=json.dumps([method,params],sort_keys=True,separators=(',',':'))
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if method in ('submit','submit_rental') and self.db.execute('SELECT 1 FROM run_fences WHERE id=?',(params['run_id'],)).fetchone():
                raise Rejected('run_permanently_fenced')
            previous=self.db.execute('SELECT * FROM requests WHERE id=?',(request_id,)).fetchone()
            if previous:
                if previous['body']!=body:raise Rejected('request_id_conflict')
                response=json.loads(previous['response'])
            else:
                if self.db.execute('SELECT count(*) FROM requests').fetchone()[0]>=10000:raise Rejected('journal_full')
                job=self.db.execute('SELECT * FROM jobs WHERE id=?',(params['run_id'],)).fetchone()
                if method in ('submit','submit_rental'):
                    mode='train' if method=='submit_rental' else params['mode']
                    if method=='submit_rental':
                        if job or self.db.execute('SELECT 1 FROM rental_bindings WHERE assignment=? OR run=?',(params['assignment_id'],params['run_id'])).fetchone():raise Rejected('rental_binding_conflict')
                        self.db.execute('INSERT INTO rental_bindings VALUES(?,?,?,?)',(params['assignment_id'],params['run_id'],params['provider'],params['terms_sha256']))
                    if mode=='resume':
                        # Explicit recovery only. Never retry an ambiguous start or
                        # override owner cancellation. Executor/worker retain the
                        # original binding, checkpoint, lease and runtime deadline.
                        if not job or job['mode']!='train' or job['state']!='failed' or job['contribution']!=params['contribution']:
                            raise Rejected('resume_requires_failed_training')
                        mode='train'
                    elif job and not (mode=='replay' and job['state'] in TERMINAL and job['contribution']==params['contribution']):
                        raise Rejected('run_id_already_used')
                    if self.db.execute("SELECT 1 FROM jobs WHERE state NOT IN ('completed','failed','cancelled')").fetchone():raise Rejected('provider_busy')
                    if job:self.db.execute("UPDATE jobs SET mode=?,state='queued' WHERE id=?",(mode,params['run_id']))
                    else:self.db.execute('INSERT INTO jobs VALUES (?,?,?,?)',(params['run_id'],mode,params['contribution'],'queued'))
                    response={'run_id':params['run_id'],'request_recorded':True,'training_started':False}
                else:
                    if not job:raise Rejected('job_unknown')
                    if method=='fence':
                        self.db.execute('INSERT OR IGNORE INTO run_fences VALUES(?,?)',(params['run_id'],request_id))
                    state=job['state']
                    if state=='queued':state='cancelled'
                    elif state not in TERMINAL:state='stop_requested'
                    self.db.execute('UPDATE jobs SET state=? WHERE id=?',(state,params['run_id']))
                    response={'run_id':params['run_id'],'stop_recorded':True,'shutdown_confirmed':state in TERMINAL}
                    if method=='fence':response.update(restart_blocked=True,slot_release_authorized=False)
                self.db.execute('INSERT INTO requests VALUES (?,?,?)',(request_id,body,json.dumps(response)))
            self.db.execute('COMMIT');return response
        except BaseException:self.db.execute('ROLLBACK');raise
    def status(self,peer_uid,run_id):
        self.authorize(peer_uid);identifier(run_id)
        row=self.db.execute('SELECT * FROM jobs WHERE id=?',(run_id,)).fetchone()
        if not row:raise Rejected('job_unknown')
        result=dict(row)
        result['restart_blocked']=bool(self.db.execute('SELECT 1 FROM run_fences WHERE id=?',(run_id,)).fetchone())
        return result
    def retire_fenced(self,peer_uid,run_id):
        """Retire a completed RemainAfterExit unit without changing its outcome."""
        self.authorize(peer_uid);identifier(run_id)
        fd=os.open(self.dispatch_path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise Rejected('unsafe_dispatch_lock')
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise Rejected('dispatcher_busy')
            if not self.db.execute('SELECT 1 FROM run_fences WHERE id=?',(run_id,)).fetchone():raise Rejected('run_not_fenced')
            row=self.db.execute('SELECT mode,state FROM jobs WHERE id=?',(run_id,)).fetchone()
            if not row:raise Rejected('job_unknown')
            if row['state'] not in TERMINAL:return False
            try:self.backend.stop(run_id,row['mode'])
            except Exception:raise Rejected('shutdown_not_confirmed')
            return True
        finally:os.close(fd)
    def shutdown_evidence(self,peer_uid,assignment):
        self.authorize(peer_uid);identifier(assignment)
        fd=os.open(self.dispatch_path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise Rejected('unsafe_dispatch_lock')
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise Rejected('dispatcher_busy')
            binding=self.db.execute('SELECT * FROM rental_bindings WHERE assignment=?',(assignment,)).fetchone()
            if not binding:raise Rejected('rental_binding_unknown')
            if not self.db.execute('SELECT 1 FROM run_fences WHERE id=?',(binding['run'],)).fetchone():raise Rejected('run_not_fenced')
            # Check both possible service modes; a terminal journal row is insufficient.
            try:observations=[self.backend.quiescent(binding['run'],mode) for mode in ('train','replay')]
            except Exception:raise Rejected('shutdown_not_confirmed')
            if any(type(x) is not dict or x.get('quiescent') is not True for x in observations):raise Rejected('shutdown_not_confirmed')
            evidence=dict(schema=1,assignment_id=assignment,run_id=binding['run'],provider=binding['provider'],
                terms_sha256=binding['digest'],fenced=True,process_running=False,pending_restarts=False,
                observed_at=int(time.time()),service_observations=observations)
            evidence['evidence_sha256']=hashlib.sha256(json.dumps(evidence,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            return evidence
        finally:os.close(fd)
    def advance(self,run_id):
        fd=os.open(self.dispatch_path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise Rejected('unsafe_dispatch_lock')
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return
            self._advance(run_id)
        finally:os.close(fd)
    def _advance(self,run_id):
        """Single dispatcher. Persist intent before side effects; never retry ambiguous start."""
        identifier(run_id)
        # Transaction claims the start so concurrent dispatchers cannot both start.
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.db.execute('SELECT * FROM jobs WHERE id=?',(run_id,)).fetchone()
            if not row:raise Rejected('job_unknown')
            job=dict(row);launch=job['state']=='queued'
            if launch:self.db.execute("UPDATE jobs SET state='dispatching' WHERE id=?",(run_id,))
            self.db.execute('COMMIT')
        except BaseException:self.db.execute('ROLLBACK');raise
        if job['state'] in TERMINAL:return
        if launch:
            try:self.backend.start(run_id,job['mode'],job['contribution'])
            except Exception:
                self.db.execute("UPDATE jobs SET state='uncertain' WHERE id=? AND state='dispatching'",(run_id,));return
            self.db.execute("UPDATE jobs SET state='running' WHERE id=? AND state='dispatching'",(run_id,))
        current=self.db.execute('SELECT state FROM jobs WHERE id=?',(run_id,)).fetchone()[0]
        if current=='stop_requested':
            try:self.backend.stop(run_id,job['mode'])
            except Exception:return
        try:observed=self.backend.inspect(run_id,job['mode'])
        except Exception:observed='unknown'
        if observed not in ('running','completed','failed','cancelled','absent','unknown'):observed='unknown'
        if observed in TERMINAL:
            self.db.execute('UPDATE jobs SET state=? WHERE id=?',(observed,run_id))
        elif observed=='running':
            self.db.execute("UPDATE jobs SET state='running' WHERE id=? AND state!='stop_requested'",(run_id,))
        elif current!='stop_requested':
            # Missing unit is NOT proof of completion or proof it never ran.
            self.db.execute("UPDATE jobs SET state='uncertain' WHERE id=?",(run_id,))
