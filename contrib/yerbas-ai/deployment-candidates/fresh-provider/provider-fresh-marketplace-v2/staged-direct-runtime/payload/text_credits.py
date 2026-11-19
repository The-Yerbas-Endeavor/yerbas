"""Leased schema-4 text contributions with atomic simulated credit settlement; local API only."""
import math
import re
import json
from pathlib import Path
import sqlite3
import time
from text_chain import ChainStore
from checkpoint_receipts import identifier
from training_contract import integer


class ContributionStore(ChainStore):
    APP_ID=1498698309  # Refuse both older lineage-only and v2 credit databases.

    def __init__(self,path,clock=time.time):
        self.clock=clock
        super().__init__(path)
        with self.tx() as db:
            db.execute('CREATE TABLE IF NOT EXISTS providers(id TEXT PRIMARY KEY,enabled INTEGER NOT NULL CHECK(enabled IN (0,1)))')
            db.execute('CREATE TABLE IF NOT EXISTS identity_policy(id INTEGER PRIMARY KEY CHECK(id=1),required INTEGER NOT NULL CHECK(required=1))')
            db.execute('CREATE TABLE IF NOT EXISTS provider_identities(provider TEXT PRIMARY KEY REFERENCES providers(id),address TEXT NOT NULL,proof TEXT NOT NULL,active INTEGER NOT NULL CHECK(active IN (0,1)))')
            db.execute('CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY,funded INTEGER NOT NULL CHECK(funded>=0),available INTEGER NOT NULL CHECK(available>=0),reserved INTEGER NOT NULL CHECK(reserved>=0),earned INTEGER NOT NULL CHECK(earned>=0))')
            db.execute('''CREATE TABLE IF NOT EXISTS reservations(contribution TEXT PRIMARY KEY REFERENCES contributions(id),
                buyer TEXT NOT NULL REFERENCES accounts(id),amount INTEGER NOT NULL CHECK(amount>0),
                lease_until REAL NOT NULL,state TEXT NOT NULL CHECK(state IN ('reserved','settled','released')),
                receipt TEXT UNIQUE REFERENCES receipts(id))''')
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_active_provider ON contributions(provider) WHERE state='active'")

    def now(self):
        value=self.clock()
        if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('Invalid clock')
        return value

    def register(self,provider):
        identifier(provider)
        with self.tx() as db:db.execute('INSERT INTO providers VALUES(?,1)',(provider,))

    def fund(self,buyer,credits):
        identifier(buyer);integer(credits,0,10**12,'simulated funding')
        with self.tx() as db:db.execute('INSERT INTO accounts VALUES(?,?,?,0,0)',(buyer,credits,credits))

    def _authorize(self,db,row):
        provider=db.execute('SELECT enabled FROM providers WHERE id=?',(row['provider'],)).fetchone()
        if provider is None or not provider[0]:raise ValueError('Provider disabled or unknown')
        if db.execute('SELECT 1 FROM identity_policy WHERE id=1').fetchone():
            binding=db.execute('SELECT active FROM provider_identities WHERE provider=?',(row['provider'],)).fetchone()
            if binding is None or binding[0]!=1:raise ValueError('Active verified wallet identity required')

    def enable_wallet_identities(self,proofs):
        """Operator-only migration using proofs from the trusted identity registry.
        No network endpoint accepts these records. No token or balance changes.
        """
        if not isinstance(proofs,list) or not 1<=len(proofs)<=8:raise ValueError('Bounded proofs required')
        with self.tx() as db:
            if db.execute("SELECT 1 FROM contributions WHERE state='active'").fetchone():raise ValueError('Idle coordinator required')
            enabled={r[0] for r in db.execute('SELECT id FROM providers WHERE enabled=1')}
            if {p['provider'] for p in proofs}!=enabled or len(proofs)!=len(enabled):raise ValueError('Proofs for every enabled provider required')
            for p in proofs:
                if (p.get('profile')!='yerbas-private-reduced-collateral-testnet' or p.get('payments_authorized') is not False
                    or not re.fullmatch('[1-9A-HJ-NP-Za-km-z]{26,50}',p.get('address',''))
                    or not re.fullmatch('[a-f0-9]{64}',p.get('proof_sha256',''))):raise ValueError('Invalid verified identity')
                expected=(p['address'],p['proof_sha256'],1)
                old=db.execute('SELECT address,proof,active FROM provider_identities WHERE provider=?',(p['provider'],)).fetchone()
                if old is not None and tuple(old)!=expected:raise ValueError('Existing identity preserved')
                db.execute('INSERT OR IGNORE INTO provider_identities VALUES(?,?,?,1)',(p['provider'],p['address'],p['proof_sha256']))
            db.execute('INSERT OR IGNORE INTO identity_policy VALUES(1,1)')

    def revoke_wallet_identity(self,provider):
        with self.tx() as db:
            if db.execute('UPDATE provider_identities SET active=0 WHERE provider=?',(provider,)).rowcount!=1:raise ValueError('Unknown wallet identity')
            for row in db.execute("SELECT id FROM contributions WHERE provider=? AND state='active'",(provider,)).fetchall():self._release(db,row[0],'revoked')

    def _check_active(self,db,row):
        r=db.execute('SELECT * FROM reservations WHERE contribution=?',(row['id'],)).fetchone()
        if r is None or r['state']!='reserved' or row['state']!='active' or self.now()>=r['lease_until']:
            raise ValueError('Contribution lease is no longer active')

    def assign(self,chain,contribution,provider,end_step,*,buyer,amount,lease_seconds=180):
        identifier(buyer);integer(amount,1,10**9,'simulated price');integer(lease_seconds,1,180,'lease duration')
        with self.tx() as db:
            self._authorize(db,{'provider':provider})
            account=db.execute('SELECT available FROM accounts WHERE id=?',(buyer,)).fetchone()
            if account is None or account[0]<amount:raise ValueError('Insufficient simulated credits')
            m=self._assign(db,chain,contribution,provider,end_step)
            deadline=self.now()+lease_seconds
            db.execute("INSERT INTO reservations VALUES(?,?,?,?,'reserved',NULL)",(contribution,buyer,amount,deadline))
            db.execute('UPDATE accounts SET available=available-?,reserved=reserved+? WHERE id=?',(amount,amount,buyer))
            return {'manifest':m,'lease_until':deadline}

    def _release(self,db,contribution,state):
        r=db.execute("SELECT * FROM reservations WHERE contribution=? AND state='reserved'",(contribution,)).fetchone()
        if r is None:return
        db.execute('UPDATE contributions SET state=? WHERE id=? AND state=\'active\'',(state,contribution))
        db.execute('UPDATE accounts SET available=available+?,reserved=reserved-? WHERE id=?',(r['amount'],r['amount'],r['buyer']))
        db.execute("UPDATE reservations SET state='released' WHERE contribution=?",(contribution,))

    def cancel(self,contribution):
        with self.tx() as db:self._release(db,contribution,'cancelled')

    def expire(self):
        # Explicit bounded coordinator sweep; rejection alone never silently refunds.
        with self.tx() as db:
            ids=[r[0] for r in db.execute("SELECT contribution FROM reservations WHERE state='reserved' AND lease_until<=?",(self.now(),))]
            for value in ids:self._release(db,value,'expired')
            return len(ids)

    def revoke(self,provider):
        with self.tx() as db:
            if db.execute('UPDATE providers SET enabled=0 WHERE id=?',(provider,)).rowcount!=1:raise ValueError('Unknown provider')
            ids=[r[0] for r in db.execute("SELECT id FROM contributions WHERE provider=? AND state='active'",(provider,))]
            for value in ids:self._release(db,value,'revoked')

    def _on_accept(self,db,row,receipt):
        r=db.execute('SELECT * FROM reservations WHERE contribution=?',(row['id'],)).fetchone()
        if r is None or r['state']!='reserved':raise ValueError('Missing credit reservation')
        db.execute('INSERT OR IGNORE INTO accounts VALUES(?,0,0,0,0)',(row['provider'],))
        db.execute('UPDATE accounts SET reserved=reserved-? WHERE id=?',(r['amount'],r['buyer']))
        db.execute('UPDATE accounts SET earned=earned+? WHERE id=?',(r['amount'],row['provider']))
        db.execute("UPDATE reservations SET state='settled',receipt=? WHERE contribution=?",(receipt,row['id']))

    def require_provider(self,db,provider):
        self._authorize(db,{'provider':provider})

    def assignment(self,provider,contribution):
        with self.tx() as db:
            row=db.execute('SELECT * FROM contributions WHERE id=? AND provider=?',(contribution,provider)).fetchone()
            if row is None:raise ValueError('Contribution not owned')
            self._authorize(db,row);self._check_active(db,row)
            lease=db.execute('SELECT lease_until FROM reservations WHERE contribution=?',(contribution,)).fetchone()[0]
            return {'manifest':json.loads(row['manifest']),'lease_until':lease}

    def status(self,provider,contribution):
        with self.tx() as db:
            row=db.execute('SELECT * FROM contributions WHERE id=? AND provider=?',(contribution,provider)).fetchone()
            if row is None:raise ValueError('Contribution not owned')
            self._authorize(db,row)
            r=db.execute('SELECT lease_until FROM reservations WHERE contribution=?',(contribution,)).fetchone()
            state=row['state']
            if state=='active' and self.now()>=r[0]:state='expired'
            return {'contribution':contribution,'state':state,'lease_until':r[0]}

    def audit(self):
        db=sqlite3.connect(Path(self.path).resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
        try:
            db.execute('BEGIN')
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Integrity failure')
            accounts=[dict(r) for r in db.execute('SELECT * FROM accounts ORDER BY id')]
            rows=db.execute('''SELECT r.*,c.state AS contribution_state,c.provider,p.id AS actual_receipt
                FROM reservations r JOIN contributions c ON c.id=r.contribution LEFT JOIN receipts p ON p.contribution=c.id''').fetchall()
            if len(rows)!=db.execute('SELECT count(*) FROM contributions').fetchone()[0]:raise ValueError('Missing reservation')
            for r in rows:
                states={'active':'reserved','completed':'settled','cancelled':'released','expired':'released','revoked':'released'}
                if r['contribution_state'] not in states or r['state']!=states[r['contribution_state']]:raise ValueError('Reservation state mismatch')
                if r['state']=='settled':
                    if not r['receipt'] or r['receipt']!=r['actual_receipt']:raise ValueError('Settlement receipt mismatch')
                elif r['receipt'] is not None or r['actual_receipt'] is not None:raise ValueError('Unsettled receipt')
            for a in accounts:
                spent=sum(r['amount'] for r in rows if r['buyer']==a['id'] and r['state']!='released')
                reserved=sum(r['amount'] for r in rows if r['buyer']==a['id'] and r['state']=='reserved')
                earned=sum(r['amount'] for r in rows if r['provider']==a['id'] and r['state']=='settled')
                if (a['available'],a['reserved'],a['earned'])!=(a['funded']-spent,reserved,earned):raise ValueError('Balance mismatch')
            totals={k:sum(a[k] for a in accounts) for k in ('funded','available','reserved','earned')}
            if totals['funded']!=totals['available']+totals['reserved']+totals['earned']:raise ValueError('Credits not conserved')
            return {'passed':True,'simulated_only':True,'totals':totals,'settlements':sum(r['state']=='settled' for r in rows),'accounts':accounts}
        finally:db.close()
