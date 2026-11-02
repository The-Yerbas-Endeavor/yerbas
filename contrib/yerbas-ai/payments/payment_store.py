"""Private operator approval/draft journal. No wallet RPC or transaction signing."""
from contextlib import contextmanager
import json,os,sqlite3,stat
from pathlib import Path
from payment_draft import build_draft
from identity import canonical
APP_ID=1498698311
class PaymentStore:
 def __init__(self,path):
  self.path=Path(path);parent=self.path.parent.lstat()
  if not stat.S_ISDIR(parent.st_mode) or parent.st_uid!=os.getuid() or parent.st_mode&0o077:raise ValueError('Private owner directory required')
  fd=os.open(self.path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
  try:
   info=os.fstat(fd)
   if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise ValueError('Private payment journal required')
  finally:os.close(fd)
  with self.db() as db:
   app=db.execute('PRAGMA application_id').fetchone()[0]
   if app!=APP_ID and (app or db.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone()):raise ValueError('Separate payment database required')
   db.execute('CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY,receipt TEXT UNIQUE NOT NULL,body TEXT NOT NULL)')
   db.execute('CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY,body TEXT NOT NULL)')
   db.execute('CREATE TABLE IF NOT EXISTS draft_receipts(receipt TEXT PRIMARY KEY,approval TEXT UNIQUE NOT NULL REFERENCES approvals(id),draft TEXT NOT NULL REFERENCES drafts(id))')
   db.execute(f'PRAGMA application_id={APP_ID}')
 @contextmanager
 def db(self):
  db=sqlite3.connect(self.path,timeout=5);db.execute('PRAGMA foreign_keys=ON')
  try:
   with db:yield db
  finally:db.close()
 def approve(self,approval,receipt_lookup,identity_lookup):
  """Explicit operator decision. receipt_lookup must read audited coordinator data.
  Identity lookup must use an active binding. Reported worker time is not approval.
  """
  receipt=receipt_lookup(approval['receipt'])
  # Validate independently of a chosen economic rate; no draft is persisted here.
  build_draft({approval['receipt']:receipt},[approval],'1',identity_lookup)
  body=canonical(approval)
  with self.db() as db:
   db.execute('BEGIN IMMEDIATE')
   old=db.execute('SELECT body FROM approvals WHERE id=?',(approval['approval_id'],)).fetchone()
   if old:
    if old[0]!=body:raise ValueError('Approval ID conflict')
   else:
    try:db.execute('INSERT INTO approvals VALUES(?,?,?)',(approval['approval_id'],approval['receipt'],body))
    except sqlite3.IntegrityError as exc:raise ValueError('Receipt already approved') from exc
  return approval
 def draft(self,approval_ids,rate,receipt_lookup,identity_lookup):
  if not isinstance(approval_ids,list) or not 1<=len(approval_ids)<=100 or len(set(approval_ids))!=len(approval_ids):raise ValueError('Distinct bounded approvals required')
  with self.db() as db:
   db.execute('BEGIN IMMEDIATE');approvals=[]
   for aid in approval_ids:
    row=db.execute('SELECT body FROM approvals WHERE id=?',(aid,)).fetchone()
    if not row:raise ValueError('Explicit saved approval required')
    approvals.append(json.loads(row[0]))
   receipts={a['receipt']:receipt_lookup(a['receipt']) for a in approvals}
   plan=build_draft(receipts,approvals,rate,identity_lookup);body=canonical(plan)
   old=db.execute('SELECT body FROM drafts WHERE id=?',(plan['plan_sha256'],)).fetchone()
   if old:
    if old[0]!=body:raise ValueError('Plan identity conflict')
    return json.loads(old[0])
   try:
    db.execute('INSERT INTO drafts VALUES(?,?)',(plan['plan_sha256'],body))
    for a in approvals:db.execute('INSERT INTO draft_receipts VALUES(?,?,?)',(a['receipt'],a['approval_id'],plan['plan_sha256']))
   except sqlite3.IntegrityError as exc:raise ValueError('Receipt already included in another draft') from exc
   return plan
