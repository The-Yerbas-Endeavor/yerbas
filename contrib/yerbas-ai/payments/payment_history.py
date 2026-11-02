"""Read saved payment observations without creating or updating a journal."""
import json
import os
import re
import sqlite3
import stat
from pathlib import Path
from payment_tracking import APP


def read_history(path):
    path = Path(path).absolute()
    if not os.path.lexists(path):
        return {}
    for item, directory in ((path.parent, True), (path, False)):
        info = item.lstat()
        valid = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        if not valid or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Private owner payment tracking journal required')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        db.execute('BEGIN')
        if (db.execute('PRAGMA application_id').fetchone()[0] != APP
                or db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok'
                or db.execute('PRAGMA foreign_key_check').fetchall()):
            raise ValueError('Payment tracking journal integrity failure')
        result = {}
        for receipt, plan in db.execute('SELECT receipt,plan FROM receipts'):
            if not re.fullmatch('[a-f0-9]{32}', receipt) or not re.fullmatch('[a-f0-9]{64}', plan):
                raise ValueError('Invalid payment history identity')
            intent = json.loads(db.execute('SELECT body FROM intents WHERE plan=?', (plan,)).fetchone()[0])
            if receipt not in intent['receipts'] or intent['candidate']['plan_sha256'] != plan:
                raise ValueError('Payment history receipt binding differs')
            row = db.execute('SELECT txid,body FROM bindings WHERE plan=?', (plan,)).fetchone()
            txid = None
            if row:
                txid, body = row
                binding = json.loads(body)
                if (binding != dict(plan_sha256=plan, signed_txid=txid, signed_transaction_verified=True)
                        or not re.fullmatch('[a-f0-9]{64}', txid)):
                    raise ValueError('Payment history signed binding differs')
            row = db.execute('SELECT body FROM observations WHERE plan=? ORDER BY id DESC LIMIT 1', (plan,)).fetchone()
            observation = json.loads(row[0]) if row else None
            if observation is not None:
                if txid:
                    if observation.get('plan_sha256') != plan or observation.get('signed_txid') != txid:
                        raise ValueError('Payment history observation binding differs')
                elif observation.get('status') != 'awaiting_signed_transaction_binding':
                    raise ValueError('Observation requires a signed binding')
            result[receipt] = dict(plan_sha256=plan, signed_txid=txid,
                                   last_saved_observation=observation,
                                   scope='historical journal only; current chain status not checked',
                                   current_chain_checked=False)
        return result
    finally:
        db.close()
