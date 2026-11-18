"""Enrolled-owner single-unit private-testnet rental actions. Never signs or broadcasts coins.

The authenticated local owner remains a trusted operator for reproduction and
shutdown evidence, as in the existing private pilot; this is not public admission.
"""
import hashlib,json,re,time
from pathlib import Path
BUYER='u26-2T'
PROVIDER='u26-2T'
AUTHORITY='anno2-coordinator-pilot'
GPU='GPU-14d39192-0531-cf2b-eead-2f292a907fb1'
FIELDS={'status':set(),'results':set(),
 'verify':{'evidence','funding'},'payment':{'scripts','funding'},
 'preflight':{'plan_sha256','funding'},'pin':{'plan_sha256','txid'},
 'release':{'evidence','txid'}}

def validate(r):
 if type(r)is not dict or type(r.get('quote_id'))is not str or not re.fullmatch('[a-f0-9]{32}',r['quote_id']):raise ValueError('Exact wallet quote required')
 QUOTE=r['quote_id']
 action=r.get('action')
 if action not in FIELDS or set(r)!={'quote_id','action'}|FIELDS[action]:raise ValueError('Fixed action fields required')
 if len(json.dumps(r))>65536:raise ValueError('Bounded request required')
 for k in ('plan_sha256','txid'):
  if k in r and (type(r[k])is not str or not re.fullmatch('[a-f0-9]{64}',r[k])):raise ValueError('Invalid digest')
 if 'evidence' in r and (type(r['evidence'])is not dict or r['evidence'].get('quote_id',QUOTE)!=QUOTE or r['evidence'].get('provider')!=PROVIDER):raise ValueError('Evidence identity differs')
 return action,QUOTE

def store_open():
 import sys
 root=Path('/opt/yerbas-ai/coordinator-generation-candidate-558b92d8249fac0c')
 sys.path.insert(0,str(root));import coordinator_entry;coordinator_entry.checked(root)
 sys.path[:0]=[str(root),str(coordinator_entry.RUNTIME),str(coordinator_entry.BASE)]
 from work_refunds import WorkRefunds
 state=Path('/var/lib/yerbas-coordinator/cutover-6b369f541521422486b3963d9629cf83/state')
 return WorkRefunds(state/'ledger.sqlite3',hashlib.sha256((state/'server.pem').read_bytes()).hexdigest(),unit_price_base_units=100000)

def execute(r):
 action,QUOTE=validate(r);store=store_open()
 from coordinator_generation import require
 from offers import GENESIS,digest
 with store.tx() as db:
  require(db,AUTHORITY,3)
  if db.execute('SELECT 1 FROM ai_authority_maintenance_v1').fetchone():raise ValueError('Coordinator frozen')
  quote=db.execute('SELECT * FROM fixed_quotes_v1 WHERE id=?',(QUOTE,)).fetchone()
  if quote:
   t=json.loads(quote['terms'])
   if quote['buyer']!=BUYER or t['units']!=1 or t['maximum_work_cost_base_units']!=101000:raise ValueError('Trial economics differ')
  elif action not in ('status',):raise ValueError('Quote not created')
  rows=[dict(x) for x in db.execute('SELECT a.* FROM ai_gpu_assignments_v1 a WHERE json_extract(a.terms,\'$.quote_id\')=?',(QUOTE,))]
  if len(rows)>1:raise ValueError('Only one work unit allowed')
  for row in rows:
   t=json.loads(row['terms'])
   if (t['provider'],t['slot'],t['gpu_uuid'],t.get('authority_generation'))!=(PROVIDER,'gpu-1',GPU,{'authority':AUTHORITY,'epoch':3}):raise ValueError('Assignment differs')
  if action=='status':
   return dict(authority=AUTHORITY,epoch=3,quote_exists=quote is not None,trial_assignments=len(rows),held_slots=db.execute("SELECT count(*) FROM ai_gpu_assignments_v1 WHERE state!='released'").fetchone()[0],unused_destinations=db.execute('SELECT count(*) FROM buyer_destinations_v1 WHERE quote IS NULL').fetchone()[0],coins_sent=False)
 if action=='results':
  with store.tx() as db:
   results=[dict(x) for x in db.execute('SELECT e.assignment,e.provider,e.contribution,c.state,r.id receipt,r.digest artifact_sha256,a.terms,a.digest terms_sha256,a.lease FROM paid_execution_v1 e JOIN contributions c ON c.id=e.contribution JOIN ai_gpu_assignments_v1 a ON a.assignment=e.assignment LEFT JOIN receipts r ON r.contribution=e.contribution WHERE e.quote=?',(QUOTE,))]
   for x in results:x['terms']=json.loads(x['terms'])
  return dict(observed_at=int(time.time()),results=results,accounting=store.audit())
 if len(rows)!=1:raise ValueError('One bound assignment required')
 assignment=rows[0]['assignment'];terms=json.loads(rows[0]['terms'])
 class Funding:
  def revalidate(self,q):
   obs=r['funding']
   if q!=QUOTE or obs['quote_id']!=QUOTE or obs['genesis']!=GENESIS or not time.time()-10<=obs['checked_at']<=time.time()+1:raise ValueError('Fresh funding required')
   return obs
 if action=='verify':
  e=r['evidence']
  if e['assignment_id']!=assignment or e['terms_sha256']!=rows[0]['digest']:raise ValueError('Evidence binding differs')
  binding=store.receipt_binding(assignment,e['receipt'])
  if binding['artifact_sha256']!=e['artifact_sha256']:raise ValueError('Artifact changed')
  class Verifier:
   def verified(self,receipt):
    if receipt!=e['receipt']:raise ValueError('Receipt differs')
    return e
  from slot_results import SlotResults
  return SlotResults(store).prepare_verified_payout(assignment,e['receipt'],Verifier(),Funding())
 if action=='payment':
  scripts=r['scripts'];address=terms['provider_identity']['address']
  if type(scripts)is not dict or set(scripts)!={address} or not re.fullmatch('76a914[0-9a-f]{40}88ac',scripts[address]):raise ValueError('Single provider destination required')
  return store.prepare_payment(BUYER,QUOTE,Funding(),lambda a:scripts[a])
 if action=='preflight':return dict(passed=store.payment_preflight(BUYER,QUOTE,r['plan_sha256'],Funding()))
 if action=='pin':return store.pin_payment(BUYER,QUOTE,r['plan_sha256'],r['txid'])
 if action=='release':
  e=r['evidence']
  with store.tx() as db:
   paid=db.execute('SELECT txid FROM paid_settlements_v1 WHERE quote=?',(QUOTE,)).fetchone()
   if not paid or paid[0]!=r['txid']:raise ValueError('Recorded payment differs')
  class Supervisor:
   def stopped(self,a,p):
    if (a,p)!=(assignment,PROVIDER):raise ValueError('Shutdown identity differs')
    return e
  from slot_results import SlotResults
  result=SlotResults(store).release_stopped(assignment,Supervisor(),authenticated_provider=PROVIDER,require_paid=True)
  return dict(release=result,accounting_passed=store.audit()['passed'])
 raise ValueError('Unsupported operation')
