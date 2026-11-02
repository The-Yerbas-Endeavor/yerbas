"""Experimental durable receipts for the fixed step-20 handoff checkpoint.

Trusted local coordinator calls only. No network API, training execution or credits.
Checkpoint bytes, receipt and lineage advance commit in one SQLite transaction.
"""
import hashlib
import json
import re
import sqlite3
import uuid
from handoff_training import MAX_BYTES, identity, validate


def identifier(value):
    if type(value) is not str or not re.fullmatch('[a-zA-Z0-9_-]{1,64}', value):
        raise ValueError('Invalid identifier')


def decode(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError('Invalid checkpoint size')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    return validate(json.loads(raw, object_pairs_hook=unique))


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, head TEXT NOT NULL, step INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS assignments (
                id TEXT PRIMARY KEY, job TEXT NOT NULL REFERENCES jobs(id),
                parent TEXT NOT NULL, state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS receipts (
                assignment TEXT PRIMARY KEY REFERENCES assignments(id),
                receipt TEXT UNIQUE NOT NULL, digest TEXT NOT NULL, artifact BLOB NOT NULL);
        ''')

    def close(self):
        self.db.close()

    def transaction(self, operation):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            result = operation()
            self.db.execute('COMMIT')
            return result
        except BaseException:
            if self.db.in_transaction:
                self.db.execute('ROLLBACK')
            raise

    def create_job(self, job):
        identifier(job)
        self.db.execute('INSERT INTO jobs VALUES(?,?,0)', (job, identity()['initial_sha256']))

    def assign(self, assignment, job):
        identifier(assignment); identifier(job)
        def operation():
            head = self.db.execute('SELECT head,step FROM jobs WHERE id=?', (job,)).fetchone()
            if head is None or head[1] != 0:
                raise ValueError('Job does not accept a step-20 assignment')
            self.db.execute('INSERT INTO assignments VALUES(?,?,?,?)',
                            (assignment, job, head[0], 'active'))
        self.transaction(operation)

    def stop(self, assignment):
        # Owner stop prevents new acceptance; a previously committed receipt is retained.
        if self.db.execute('UPDATE assignments SET state=? WHERE id=?',
                           ('stopped', assignment)).rowcount != 1:
            raise ValueError('Unknown assignment')

    def accept(self, assignment, raw, expected_digest, *, _fault=lambda stage: None):
        identifier(assignment)
        decode(raw)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != expected_digest:
            raise ValueError('Transfer checksum mismatch')
        def operation():
            prior = self.db.execute('SELECT receipt,digest FROM receipts WHERE assignment=?',
                                    (assignment,)).fetchone()
            if prior:
                if prior[1] != digest:
                    raise ValueError('Conflicting replay')
                return {'receipt': prior[0], 'sha256': digest, 'step': 20}
            row = self.db.execute('SELECT job,parent,state FROM assignments WHERE id=?',
                                  (assignment,)).fetchone()
            if row is None or row[2] != 'active':
                raise ValueError('Assignment is unknown or stopped')
            head = self.db.execute('SELECT head,step FROM jobs WHERE id=?', (row[0],)).fetchone()
            if head != (row[1], 0):
                raise ValueError('Stale checkpoint parent')
            receipt = uuid.uuid4().hex
            self.db.execute('INSERT INTO receipts VALUES(?,?,?,?)',
                            (assignment, receipt, digest, raw))
            self.db.execute('UPDATE jobs SET head=?,step=20 WHERE id=?', (digest, row[0]))
            _fault('before_commit')
            return {'receipt': receipt, 'sha256': digest, 'step': 20}
        result = self.transaction(operation)
        _fault('after_commit')
        return result
