"""Read-only contribution-to-reward review. Never grants approval or writes drafts."""
import json,os,sqlite3,stat
from contextlib import contextmanager
from pathlib import Path
from payment_draft import build_draft
from payment_store import APP_ID

@contextmanager
def saved_approvals(path):
 path=Path(path)
 if not os.path.lexists(path):
  yield {},{};return
 for p,directory in [(path.parent,True),(path,False)]:
  s=p.lstat()
  if s.st_uid!=os.getuid() or s.st_mode&0o077 or not (stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode)):raise ValueError('Private approval journal required')
 db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
 try:
  db.execute('BEGIN')
  if db.execute('PRAGMA application_id').fetchone()[0]!=APP_ID or db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Approval journal integrity failure')
  approvals={}
  for aid,rid,body in db.execute('SELECT id,receipt,body FROM approvals'):
   a=json.loads(body)
   if a.get('approval_id')!=aid or a.get('receipt')!=rid:raise ValueError('Approval journal binding differs')
   approvals[rid]=a
  drafts={}
  for rid,aid,draft in db.execute('SELECT receipt,approval,draft FROM draft_receipts'):
   if rid not in approvals or approvals[rid]['approval_id']!=aid:raise ValueError('Draft approval binding differs')
   drafts[rid]=draft
  yield approvals,drafts
 finally:db.close()

def review_row(row,record,identity_lookup,approval=None,draft=None,rate=None,timing_evidence=None):
 from timing_review import describe
 timing=describe(timing_evidence,row['id'],record)
 rid=row['id'];proof=identity_lookup(row['proof']) if row['proof'] else None
 valid_identity=bool(proof and proof['provider']==row['provider'] and proof['address']==row['address'])
 completed=bool(record and record['state']=='completed')
 confirmed=bool(record and record.get('independently_confirmed'))
 signed=bool(record and record.get('signed_verification_accepted'))
 blockers=[]
 if not completed:blockers.append('completed_settled_receipt_required')
 if not valid_identity:blockers.append('active_wallet_identity_required')
 if not confirmed:blockers.append('independent_confirmation_required')
 if not signed:blockers.append('accepted_signed_verification_required')
 plan=None;approval_valid=False
 if approval is None:blockers.append('operator_gpu_time_approval_required')
 else:
  try:
   if approval['receipt']!=rid or approval['identity_proof']!=row['proof']:raise ValueError('Current receipt identity differs')
   plan=build_draft({rid:record},[approval],rate or '1',identity_lookup);approval_valid=True
  except (ValueError,KeyError,TypeError):blockers.append('saved_approval_not_currently_valid')
 if rate is None:blockers.append('explicit_reward_rate_required')
 if draft is not None:blockers.append('receipt_already_in_unsigned_draft')
 return dict(timing_evidence=timing,receipt=rid,provider=row['provider'],address=row['address'],identity_proof=row['proof'],eligible_identity=valid_identity,completed_receipt_verified=completed,independently_confirmed=confirmed,signed_verification_accepted=signed,attestation_sha256=record.get('attestation_sha256') if record else None,approval_id=approval.get('approval_id') if approval else None,approved_gpu_ms=approval['approved_gpu_ms'] if approval_valid else None,approval_currently_valid=approval_valid,existing_unsigned_draft=draft,preview_amount_base_units=plan['total_base_units'] if plan and rate else None,reward_draft_ready=not blockers,blockers=blockers,payment_sent=None,payment_status='not_checked',payment_status_scope='Draft review does not inspect broadcast records or chain confirmations')

def inspect(db,receipt_lookup,identity_lookup,journal,rate=None,policy=None,timing_evidence=None,tracking_journal=None):
 from payment_history import read_history
 history=read_history(tracking_journal) if tracking_journal is not None else {}
 with saved_approvals(Path(journal).absolute()) as (approvals,drafts):
  rows=[]
  for row in db.execute('SELECT r.id,c.provider,i.address,i.proof FROM receipts r JOIN contributions c ON c.id=r.contribution LEFT JOIN provider_identities i ON i.provider=c.provider ORDER BY r.id'):
   rows.append(review_row(row,receipt_lookup(row['id']),identity_lookup,approvals.get(row['id']),drafts.get(row['id']),rate,timing_evidence if timing_evidence and timing_evidence['body']['receipt']==row['id'] else None))
  for row in rows:
   row['payment_history']=history.get(row['receipt'])
   if row['payment_history'] and row['existing_unsigned_draft']!=row['payment_history']['plan_sha256']:raise ValueError('Draft and payment history binding differ')
  if timing_evidence and not any(r['receipt']==timing_evidence['body']['receipt'] for r in rows):raise ValueError('Timing review receipt is not in the ledger')
 return dict(scope='read-only contribution and unsigned-reward readiness; no approvals or drafts created',payments_enabled=False,selected_policy=policy,rate_yerb_per_approved_gpu_hour=rate,receipts=rows,summary=dict(receipts=len(rows),signed_verified=sum(r['signed_verification_accepted'] for r in rows),current_time_approvals=sum(r['approval_currently_valid'] for r in rows),ready_for_unsigned_draft=sum(r['reward_draft_ready'] for r in rows),already_drafted=sum(r['existing_unsigned_draft'] is not None for r in rows)))
