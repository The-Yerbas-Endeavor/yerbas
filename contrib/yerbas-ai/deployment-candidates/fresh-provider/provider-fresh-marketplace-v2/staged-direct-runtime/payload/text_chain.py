"""Isolated schema-4 text lineage/receipt store for trusted coordinator calls.

Not wired to HTTPS, GPU execution, leases or credits. Never use provider identity
from untrusted request data as authenticated identity. No existing DB migration.
"""
from contextlib import contextmanager
import hashlib
import json
import os
import sqlite3
import uuid
from text_contribution import validate_manifest,manifest_digest,verify_result
from sustained_training import encoded
from text_contribution import initial_parent
from checkpoint_receipts import identifier
from training_contract import fields,digest,integer

APP_ID=1498698308


class ChainStore:
    APP_ID=APP_ID
    def __init__(self,path):
        self.path=str(path)
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600);os.close(fd)
        with self.tx() as db:
            tables=db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            app=db.execute('PRAGMA application_id').fetchone()[0]
            if app!=self.APP_ID and (app!=0 or tables):raise ValueError('Separate contribution database required')
            db.execute('CREATE TABLE IF NOT EXISTS chains(id TEXT PRIMARY KEY,identity TEXT NOT NULL,target INTEGER NOT NULL,head TEXT NOT NULL,step INTEGER NOT NULL,stopped INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS contributions(id TEXT PRIMARY KEY,chain TEXT NOT NULL REFERENCES chains(id),provider TEXT NOT NULL,manifest TEXT NOT NULL,state TEXT NOT NULL)')
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_active_chain ON contributions(chain) WHERE state='active'")
            db.execute('CREATE TABLE IF NOT EXISTS receipts(contribution TEXT PRIMARY KEY REFERENCES contributions(id),id TEXT UNIQUE NOT NULL,digest TEXT NOT NULL,artifact BLOB NOT NULL)')
            db.execute(f'PRAGMA application_id={self.APP_ID}')

    @contextmanager
    def tx(self):
        db=sqlite3.connect(self.path,timeout=10,isolation_level=None);db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE')
            yield db;db.execute('COMMIT')
        except BaseException:
            if db.in_transaction:db.execute('ROLLBACK')
            raise
        finally:db.close()

    def create(self,chain,identity,target):
        identifier(chain);fields(identity,('runner','dataset','config'))
        for value in identity.values():digest(value)
        integer(target,6000,6000,'target')
        with self.tx() as db:db.execute('INSERT INTO chains VALUES(?,?,?,?,0,0)',(chain,encoded(identity).decode(),target,initial_parent(identity)))

    def assign(self,chain,contribution,provider,end_step):
        with self.tx() as db:return self._assign(db,chain,contribution,provider,end_step)

    def _assign(self,db,chain,contribution,provider,end_step):
        for value in (chain,contribution,provider):identifier(value)
        row=db.execute('SELECT * FROM chains WHERE id=?',(chain,)).fetchone()
        if row is None or row['stopped'] or row['step']>=row['target']:raise ValueError('Chain does not accept more contributions')
        m={'schema':4,'recipe':'byte-context-mlp-v1','chain':chain,'contribution':contribution,'provider':provider,
           'identity':json.loads(row['identity']),'parent_sha256':row['head'],'start_step':row['step'],
           'end_step':end_step,'target_step':row['target'],'max_runtime_seconds':120,'max_artifact_bytes':16*1024*1024}
        validate_manifest(m)
        db.execute("INSERT INTO contributions VALUES(?,?,?,?,'active')",(contribution,chain,provider,encoded(m).decode()))
        return m

    def _authorize(self,db,row):pass
    def _check_active(self,db,row):pass
    def _on_accept(self,db,row,receipt):pass

    def parent(self,provider,contribution):
        with self.tx() as db:
            row=db.execute('SELECT * FROM contributions WHERE id=? AND provider=?',(contribution,provider)).fetchone()
            if row is None or row['state']!='active':raise ValueError('Contribution not active or not owned')
            self._authorize(db,row);self._check_active(db,row)
            m=json.loads(row['manifest'])
            if m['start_step']==0:return None
            raw=db.execute('SELECT r.artifact FROM receipts r JOIN contributions c ON c.id=r.contribution WHERE c.chain=? AND r.digest=?',(row['chain'],m['parent_sha256'])).fetchone()
            if raw is None:raise ValueError('Accepted parent missing')
            return bytes(raw[0])

    def cancel(self,contribution):
        with self.tx() as db:db.execute("UPDATE contributions SET state='cancelled' WHERE id=? AND state='active'",(contribution,))

    def accept(self,provider,contribution,expected_manifest,raw,*,_fault=lambda stage:None):
        with self.tx() as db:
            row=db.execute('SELECT * FROM contributions WHERE id=? AND provider=?',(contribution,provider)).fetchone()
            if row is None:raise ValueError('Contribution not owned')
            self._authorize(db,row)
            m=json.loads(row['manifest'])
            if expected_manifest!=manifest_digest(m):raise ValueError('Contribution manifest changed')
            if type(raw) is not bytes or not 0<len(raw)<=m['max_artifact_bytes']:raise ValueError('Invalid artifact size')
            sha=hashlib.sha256(raw).hexdigest()
            prior=db.execute('SELECT id,digest FROM receipts WHERE contribution=?',(contribution,)).fetchone()
            if prior:
                if prior['digest']!=sha:raise ValueError('Conflicting replay')
                return {'receipt':prior['id'],'sha256':sha,'contribution':contribution}
            head=db.execute('SELECT * FROM chains WHERE id=?',(row['chain'],)).fetchone()
            if row['state']!='active' or head['head']!=m['parent_sha256'] or head['step']!=m['start_step'] or head['stopped']:
                raise ValueError('Contribution no longer owns current parent')
            self._check_active(db,row)
            parent=None
            if m['start_step']:
                value=db.execute('SELECT r.artifact FROM receipts r JOIN contributions c ON c.id=r.contribution WHERE c.chain=? AND r.digest=?',(row['chain'],m['parent_sha256'])).fetchone()
                if value is None:raise ValueError('Accepted parent missing')
                parent=bytes(value[0])
            result=verify_result(m,raw,parent)
            self._check_active(db,row)
            receipt=uuid.uuid4().hex
            db.execute('INSERT INTO receipts VALUES(?,?,?,?)',(contribution,receipt,sha,raw))
            db.execute("UPDATE contributions SET state='completed' WHERE id=?",(contribution,))
            db.execute('UPDATE chains SET head=?,step=?,stopped=? WHERE id=?',(sha,result['step'],int(result['stopped']),row['chain']))
            self._on_accept(db,row,receipt)
            _fault('before_commit')
        _fault('after_commit')
        return {'receipt':receipt,'sha256':sha,'contribution':contribution}
