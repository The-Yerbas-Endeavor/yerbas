"""Isolated training assignment/receipt prototype. Trusted local calls only.

No listener, credential authentication, worker execution, or credit settlement.
Do not pass provider-supplied identity as actor without a future authenticated API.
"""
from contextlib import contextmanager
import hashlib
import json
import math
import os
import sqlite3
import time
import uuid
from checkpoint_receipts import identifier
from selected_checkpoint import MAX_BYTES, validate_bundle
import recovery_checkpoint_v2 as v2

APP_ID=1498698305


def decode(raw,recipe="validation-v1"):
    if recipe not in ("validation-v1","validation-v2"):raise ValueError("Unknown recipe")
    limit=v2.MAX_BYTES if recipe=="validation-v2" else MAX_BYTES
    if type(raw) is not bytes or not 0<len(raw)<=limit:raise ValueError('Artifact size invalid')
    def unique(pairs):
        result={}
        for k,v in pairs:
            if k in result:raise ValueError('Duplicate JSON key')
            result[k]=v
        return result
    envelope=json.loads(raw,object_pairs_hook=unique)
    if type(envelope) is not dict or set(envelope)!={'sha256','bundle'}:raise ValueError('Invalid artifact envelope')
    from sustained_training import encoded
    if hashlib.sha256(encoded(envelope['bundle'])).hexdigest()!=envelope['sha256']:
        raise ValueError('Artifact envelope checksum mismatch')
    validator=v2.validate_bundle if recipe=='validation-v2' else validate_bundle
    return validator(envelope['bundle'])


class Store:
    def __init__(self,path,clock=time.time):
        self.path=str(path);self.clock=clock
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600);os.close(fd)
        with self.tx() as db:
            app=db.execute('PRAGMA application_id').fetchone()[0]
            tables=db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if app!=APP_ID and (app!=0 or tables):raise ValueError('Not a training assignment database')
            for sql in [
                'CREATE TABLE IF NOT EXISTS providers(id TEXT PRIMARY KEY,enabled INTEGER NOT NULL)',
                'CREATE TABLE IF NOT EXISTS control(id INTEGER PRIMARY KEY,paused INTEGER NOT NULL)',
                '''CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,state TEXT NOT NULL,
                   max_steps INTEGER NOT NULL,deadline REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0)''',
                '''CREATE TABLE IF NOT EXISTS job_recipes(job TEXT PRIMARY KEY REFERENCES jobs(id),recipe TEXT NOT NULL)''',
                '''CREATE TABLE IF NOT EXISTS assignments(id TEXT PRIMARY KEY,job TEXT NOT NULL REFERENCES jobs(id),
                   provider TEXT NOT NULL REFERENCES providers(id),request TEXT NOT NULL,expires REAL NOT NULL,state TEXT NOT NULL,
                   UNIQUE(provider,request))''',
                "CREATE UNIQUE INDEX IF NOT EXISTS active_job ON assignments(job) WHERE state='active'",
                "CREATE UNIQUE INDEX IF NOT EXISTS active_provider ON assignments(provider) WHERE state='active'",
                '''CREATE TABLE IF NOT EXISTS receipts(job TEXT PRIMARY KEY REFERENCES jobs(id),
                   assignment TEXT UNIQUE NOT NULL REFERENCES assignments(id),id TEXT UNIQUE NOT NULL,
                   digest TEXT NOT NULL,artifact BLOB NOT NULL)''']:
                db.execute(sql)
            db.execute('INSERT OR IGNORE INTO control VALUES(1,0)')
            db.execute(f'PRAGMA application_id={APP_ID}')

    @contextmanager
    def tx(self):
        db=sqlite3.connect(self.path,timeout=10,isolation_level=None);db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE')
            yield db
            db.execute('COMMIT')
        except BaseException:
            if db.in_transaction:db.execute('ROLLBACK')
            raise
        finally:db.close()

    def now(self):
        value=self.clock()
        if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('Invalid coordinator clock')
        return value

    def register(self,provider):
        identifier(provider)
        with self.tx() as db:db.execute('INSERT INTO providers VALUES(?,1)',(provider,))

    def enqueue(self,job,max_steps=10000,recipe="validation-v1"):
        with self.tx() as db:self._enqueue(db,job,max_steps,recipe)

    def _enqueue(self,db,job,max_steps,recipe):
        if recipe not in ("validation-v1","validation-v2"):raise ValueError("Unknown recipe")
        identifier(job)
        if type(max_steps) is not int or not 500<=max_steps<=10000:raise ValueError('Invalid step bound')
        db.execute('INSERT INTO jobs(id,state,max_steps,deadline) VALUES(?,?,?,?)',
                   (job,'queued',max_steps,self.now()+3600))
        if recipe!='validation-v1':db.execute('INSERT INTO job_recipes VALUES(?,?)',(job,recipe))

    def recipe(self,db,job):
        row=db.execute('SELECT recipe FROM job_recipes WHERE job=?',(job,)).fetchone()
        return row[0] if row else 'validation-v1'

    def require_provider(self,db,provider):
        row=db.execute('SELECT enabled FROM providers WHERE id=?',(provider,)).fetchone()
        if not row or not row[0]:raise ValueError('Unknown or revoked provider')

    def expire(self,db,now):
        rows=db.execute("SELECT a.id,a.job,j.attempts,j.deadline FROM assignments a JOIN jobs j ON a.job=j.id WHERE a.state='active' AND a.expires<=?",(now,)).fetchall()
        for row in rows:
            db.execute("UPDATE assignments SET state='expired' WHERE id=?",(row['id'],))
            db.execute('UPDATE jobs SET state=? WHERE id=?',('queued' if row['attempts']<2 and row['deadline']>now else 'failed',row['job']))
        db.execute("UPDATE jobs SET state='failed' WHERE state='queued' AND deadline<=?",(now,))

    def describe(self,row,max_steps,recipe="validation-v1"):
        return {'assignment':row['id'],'job':row['job'],'provider':row['provider'],
                'lease_until':row['expires'],'state':row['state'],'recipe':recipe,
                'max_steps':max_steps,'max_runtime_seconds':120,'max_artifact_bytes':v2.MAX_BYTES if recipe=='validation-v2' else MAX_BYTES}

    def claim(self,provider,request):
        identifier(provider);identifier(request)
        with self.tx() as db:
            self.require_provider(db,provider);now=self.now();self.expire(db,now)
            prior=db.execute('SELECT a.*,j.max_steps FROM assignments a JOIN jobs j ON j.id=a.job WHERE a.provider=? AND a.request=?',(provider,request)).fetchone()
            if prior:return self.describe(prior,prior['max_steps'],self.recipe(db,prior['job']))
            if db.execute('SELECT paused FROM control').fetchone()[0]:return None
            if db.execute("SELECT 1 FROM assignments WHERE provider=? AND state='active'",(provider,)).fetchone():
                raise ValueError('Provider already has an active assignment')
            job=db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY rowid LIMIT 1").fetchone()
            if job is None:return None
            assignment=uuid.uuid4().hex
            db.execute('INSERT INTO assignments VALUES(?,?,?,?,?,?)',
                       (assignment,job['id'],provider,request,min(now+180,job['deadline']),'active'))
            db.execute("UPDATE jobs SET state='assigned',attempts=attempts+1 WHERE id=?",(job['id'],))
            row=db.execute('SELECT * FROM assignments WHERE id=?',(assignment,)).fetchone()
            return self.describe(row,job['max_steps'],self.recipe(db,job['id']))

    def status(self,provider,assignment):
        # A status check never extends a lease or changes assignment ownership.
        with self.tx() as db:
            self.require_provider(db,provider)
            row=db.execute('SELECT state,expires FROM assignments WHERE id=? AND provider=?',
                           (assignment,provider)).fetchone()
            if row is None:raise ValueError('Assignment does not belong to provider')
            state=row['state']
            if state=='active' and self.now()>=row['expires']:state='expired'
            return {'assignment':assignment,'state':state,'lease_until':row['expires']}

    def pause(self,paused=True):
        if type(paused) is not bool:raise ValueError('Expected boolean')
        with self.tx() as db:db.execute('UPDATE control SET paused=?',(int(paused),))

    def cancel(self,job):
        with self.tx() as db:
            row=db.execute('SELECT state FROM jobs WHERE id=?',(job,)).fetchone()
            if row is None:raise ValueError('Unknown job')
            if row[0]=='completed':return
            db.execute("UPDATE jobs SET state='cancelled' WHERE id=?",(job,))
            db.execute("UPDATE assignments SET state='cancelled' WHERE job=? AND state='active'",(job,))

    def revoke(self,provider):
        with self.tx() as db:
            if db.execute('UPDATE providers SET enabled=0 WHERE id=?',(provider,)).rowcount!=1:
                raise ValueError('Unknown provider')
            for row in db.execute("SELECT a.id,a.job,j.attempts FROM assignments a JOIN jobs j ON a.job=j.id WHERE a.provider=? AND a.state='active'",(provider,)).fetchall():
                db.execute("UPDATE assignments SET state='revoked' WHERE id=?",(row['id'],))
                db.execute('UPDATE jobs SET state=? WHERE id=?',('queued' if row['attempts']<2 else 'failed',row['job']))

    def accept(self,provider,assignment,raw,digest,*,_fault=lambda stage:None):
        # Check the authenticated caller's assignment before costly artifact decoding.
        with self.tx() as db:
            self.require_provider(db,provider)
            row=db.execute('SELECT a.*,j.max_steps,j.state AS job_state FROM assignments a JOIN jobs j ON j.id=a.job WHERE a.id=? AND a.provider=?',(assignment,provider)).fetchone()
            if row is None:raise ValueError('Assignment does not belong to provider')
            if type(raw) is not bytes or len(raw)>MAX_BYTES or hashlib.sha256(raw).hexdigest()!=digest:
                raise ValueError('Transfer checksum/size mismatch')
            prior=db.execute('SELECT id,digest FROM receipts WHERE assignment=?',(assignment,)).fetchone()
            if prior:
                if prior['digest']!=digest:raise ValueError('Conflicting result replay')
                return {'receipt':prior['id'],'sha256':digest,'job':row['job']}
            if row['state']!='active' or row['job_state']!='assigned' or self.now()>=row['expires']:
                raise ValueError('Assignment no longer active')
            recipe=self.recipe(db,row['job'])
            bundle=decode(raw,recipe);step=bundle['latest']['step']
            if recipe=='validation-v2' and bundle['target_step']!=row['max_steps']:raise ValueError('Result target differs from assignment')
            if step>row['max_steps'] or (not bundle['selection']['stopped'] and step!=row['max_steps']):
                raise ValueError('Result is not a bounded completed job')
            # Validate again after decoding: verification time must not extend a lease.
            if self.now()>=row['expires']:raise ValueError('Lease expired during verification')
            receipt=uuid.uuid4().hex
            db.execute('INSERT INTO receipts VALUES(?,?,?,?,?)',(row['job'],assignment,receipt,digest,raw))
            db.execute("UPDATE assignments SET state='completed' WHERE id=?",(assignment,))
            db.execute("UPDATE jobs SET state='completed' WHERE id=?",(row['job'],))
            _fault('before_commit')
            result={'receipt':receipt,'sha256':digest,'job':row['job']}
        _fault('after_commit')
        return result
