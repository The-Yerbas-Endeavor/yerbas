"""Private payment-intent journal. No signing, broadcasting or retry capability.
Registration takes a candidate already revalidated against approved live evidence.
Signed bindings require a trusted verifier callback; no signed-binding CLI exists.
"""
import hashlib,json,os,re,sqlite3,stat
from contextlib import contextmanager
from pathlib import Path
from identity import canonical
from payment_observation import assess
APP=1498698320

class TrackingStore:
 def __init__(self,path):
  self.path=Path(path)
  info=self.path.parent.lstat()
  if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise ValueError('Private owner directory required')
  fd=os.open(self.path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
  try:
   info=os.fstat(fd)
   if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise ValueError('Private owner journal required')
  finally:os.close(fd)
  with self.db() as db:
   app=db.execute('PRAGMA application_id').fetchone()[0]
   if app!=APP and (app or db.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone()):raise ValueError('Wrong tracking database')
   db.execute('CREATE TABLE IF NOT EXISTS intents(plan TEXT PRIMARY KEY,body TEXT NOT NULL)')
   db.execute('CREATE TABLE IF NOT EXISTS receipts(receipt TEXT PRIMARY KEY,plan TEXT NOT NULL REFERENCES intents(plan))')
   db.execute('CREATE TABLE IF NOT EXISTS inputs(outpoint TEXT PRIMARY KEY,plan TEXT NOT NULL REFERENCES intents(plan))')
   db.execute('CREATE TABLE IF NOT EXISTS bindings(plan TEXT PRIMARY KEY REFERENCES intents(plan),txid TEXT UNIQUE NOT NULL,body TEXT NOT NULL)')
   db.execute('CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY,plan TEXT NOT NULL REFERENCES intents(plan),body TEXT NOT NULL)')
   db.execute(f'PRAGMA application_id={APP}')
 @contextmanager
 def db(self):
  db=sqlite3.connect(self.path,timeout=10);db.execute('PRAGMA foreign_keys=ON')
  try:
   with db:yield db
  finally:db.close()
 def register(self,candidate,receipts):
  plan=candidate['plan_sha256'];raw=candidate['raw_unsigned_hex']
  if not re.fullmatch('[a-f0-9]{64}',plan) or hashlib.sha256(bytes.fromhex(raw)).hexdigest()!=candidate['raw_bytes_sha256']:raise ValueError('Candidate identity mismatch')
  if candidate.get('signed') is not False or candidate.get('broadcast') is not False:raise ValueError('Unsigned candidate required')
  if not receipts or len(set(receipts))!=len(receipts) or any(not re.fullmatch('[a-f0-9]{32}',r) for r in receipts):raise ValueError('Distinct receipts required')
  # Store immutable economic/transaction fields; changing tip observations is harmless.
  keys=('plan_sha256','raw_unsigned_hex','raw_bytes_sha256','inputs','outputs','scripts','input_base_units','fee_base_units','reward_base_units','change_base_units')
  body=canonical(dict(candidate={k:candidate[k] for k in keys},receipts=sorted(receipts)))
  with self.db() as db:
   db.execute('BEGIN IMMEDIATE')
   old=db.execute('SELECT body FROM intents WHERE plan=?',(plan,)).fetchone()
   if old:
    if old[0]!=body:raise ValueError('Existing payment intent differs; manual review required')
    return self.status(plan)
   try:
    db.execute('INSERT INTO intents VALUES(?,?)',(plan,body))
    for receipt in receipts:db.execute('INSERT INTO receipts VALUES(?,?)',(receipt,plan))
    for item in candidate['inputs']:db.execute('INSERT INTO inputs VALUES(?,?)',(item['txid']+':'+str(item['vout']),plan))
   except sqlite3.IntegrityError as exc:raise ValueError('Receipt or input already assigned to an intent') from exc
  return self.status(plan)
 def bind_verified(self,plan,signed_raw,verifier):
  """Trusted verifier must check signatures, exact outputs/input, fee and txid.
  No supplied CLI exposes this API until such a verifier is integrated.
  """
  with self.db() as db:
   db.execute('BEGIN IMMEDIATE')
   row=db.execute('SELECT body FROM intents WHERE plan=?',(plan,)).fetchone()
   if not row:raise ValueError('Registered intent required')
   txid=verifier(signed_raw,json.loads(row[0])['candidate'])
   if not isinstance(txid,str) or not re.fullmatch('[a-f0-9]{64}',txid):raise ValueError('Verifier did not return a valid txid')
   binding=dict(plan_sha256=plan,signed_txid=txid,signed_transaction_verified=True)
   body=canonical(binding);old=db.execute('SELECT body FROM bindings WHERE plan=?',(plan,)).fetchone()
   if old and old[0]!=body:raise ValueError('Signed binding already exists; no automatic replacement')
   if not old:db.execute('INSERT INTO bindings VALUES(?,?,?)',(plan,txid,body))
  return binding
 def observe(self,plan,collector,depth=6):
  with self.db() as db:
   db.execute('BEGIN IMMEDIATE')
   if not db.execute('SELECT 1 FROM intents WHERE plan=?',(plan,)).fetchone():raise ValueError('Unknown intent')
   row=db.execute('SELECT body FROM bindings WHERE plan=?',(plan,)).fetchone()
   binding=json.loads(row[0]) if row else None
   previous=db.execute('SELECT body FROM observations WHERE plan=? ORDER BY id DESC LIMIT 1',(plan,)).fetchone()
   previous=json.loads(previous[0]) if previous else None
   if previous and 'signed_txid' not in previous:previous=None
   result=assess(binding,collector(binding['signed_txid']) if binding else None,previous,depth)
   db.execute('INSERT INTO observations(plan,body) VALUES(?,?)',(plan,canonical(result)))
  return result
 def status(self,plan):
  with self.db() as db:
   if not db.execute('SELECT 1 FROM intents WHERE plan=?',(plan,)).fetchone():raise ValueError('Unknown intent')
   bound=db.execute('SELECT txid FROM bindings WHERE plan=?',(plan,)).fetchone()
   return dict(plan_sha256=plan,signed_txid=bound[0] if bound else None,
               state='signed_binding_present' if bound else 'awaiting_signed_transaction_binding',
               automatic_retry=False,wallet_input_lock=False,broadcast_authorized=False)

def collect(rpc,txid):
 """Trusted wallet-scoped read RPC. Unavailable data stays unknown, not unpaid."""
 try:
  before=rpc('getblockchaininfo');tx=rpc('gettransaction',txid)
  if tx.get('txid')!=txid:raise ValueError('Wallet transaction mismatch')
  confirmations=tx['confirmations']
  obs=dict(available=True,txid=txid,confirmations=confirmations,conflicted=bool(tx.get('walletconflicts')))
  if confirmations>0:
   block=rpc('getblock',tx['blockhash'],'1')
   if txid not in block['tx']:raise ValueError('Transaction missing from claimed block')
   obs.update(block_height=block['height'],blockhash=tx['blockhash'],tip_height=before['blocks'],active_hash_at_height=rpc('getblockhash',str(block['height'])))
  elif confirmations==0:
   obs['in_mempool']=txid in rpc('getrawmempool')
  after=rpc('getblockchaininfo')
  if before['bestblockhash']!=after['bestblockhash']:return None
  return obs
 except (OSError,TimeoutError):return None
