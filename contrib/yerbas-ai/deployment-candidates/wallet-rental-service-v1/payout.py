"""Commit this verified unit's exact payout and use the protected proof-required signer."""
import argparse,datetime,fcntl,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent

sys.path.insert(0,str(ROOT/'wallet-consensus-rental-v1'))
from commands import digest
from paid_pilot import session as open_session
PACKAGE=Path('/opt/yerbas-ai/post-cutover-treasury-1185a6dc6b3eae65')

def treasury_proof(p):
 import sqlite3,contextlib
 journal=Path.home()/'.local/share/yerbas-consensus-treasury-v1/state.sqlite3'
 with contextlib.closing(sqlite3.connect(journal.as_uri()+'?mode=ro',uri=True)) as db:tip=db.execute('SELECT height FROM tip WHERE id=1').fetchone()[0]
 def newer():
  v=p.proof();return v if int(v['signed_header']['header']['height'])>tip else None
 current=p.wait(newer,seconds=35);height=int(current['signed_header']['header']['height'])
 if not 1<=height-tip<=99:raise ValueError('Treasury header maintenance required')
 proofs=[dict(signed_header=p.call(2,'commit',{'height':str(n)})['signed_header'],validators=p.call(2,'validators',{'height':str(n),'per_page':'100'})['validators']) for n in range(tip+1,height+1)]
 return dict(proofs=proofs,state=current['state'])

def settle(context,apply=False):
 # The owner workflow supplies its retained context; no arbitrary command or key path.
 STATE=context.state;trial=context.trial;QUOTE=context.quote
 if not __import__('re').fullmatch('[a-f0-9]{32}',QUOTE):raise ValueError('Exact wallet quote required')
 if STATE.is_symlink() or STATE.stat().st_uid!=os.getuid() or STATE.stat().st_mode&0o077:raise ValueError('Private owner workflow required')
 def session():return open_session(STATE/'commands',json.loads((STATE/'plan.json').read_text()))
 fd=os.open(STATE/'lock',os.O_RDWR|os.O_NOFOLLOW)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);trial.network()
  rows=trial.load('results.json')['results']
  if len(rows)!=1:raise ValueError('One completed work unit required')
  RUN=rows[0]['assignment'];RECEIPT=rows[0]['receipt']
  payment=trial.load('payment.json');native=payment['plan'];order=digest(dict(quote=QUOTE,assignment=RUN))
  if native['quote_id']!=QUOTE or digest(native)!=payment['plan_sha256'] or len(native['receipts'])!=1 or native['receipts'][0]['receipt']!=RECEIPT or native['receipts'][0]['assignment_id']!=RUN or native['deposit_base_units']!=101000 or native['fee_base_units']!=1000:raise ValueError('Exact paid unit required')
  reference=trial.load('verification-reference.json')
  accepted=json.loads((Path(reference['path'])/'acceptance.json').read_text())
  if accepted.get('accepted') is not True or accepted['receipt']!=RECEIPT or accepted['attestation_sha256']!=reference['attestation_sha256']:raise ValueError('Independent acceptance differs')
  if (STATE/'consensus-settle-intent.json').exists():raise ValueError('Retained settlement intent exists: observation only; never resend')
  with session() as p:
   artifact=native['receipts'][0]['artifact_sha256'];w=p.state()['orders'][order]
   if w['execution_binding']['assignment_id']!=RUN:raise ValueError('Wrong consensus work')
   if w['state']=='assigned':p.send('provider','result',dict(order=order,artifact=artifact))
   w=p.state()['orders'][order]
   if w['artifact']!=artifact:raise ValueError('Consensus artifact differs')
   if w['state']=='submitted':p.send('verifier','verify',dict(order=order,artifact=artifact))
   w=p.state()['orders'][order]
   if w['state']!='verified' or w['verifier']!=p.ids['verifier']:raise ValueError('Expected independent verified state')
   funding=dict(order=order,quote_id=QUOTE,quote_sha256=native['quote_sha256'],coordinator_ca_sha256=native['coordinator_ca_sha256'],txid=native['deposit_txid'],vout=native['deposit_vout'],amount=native['deposit_base_units'],script=native['receiving_script'],fee=native['fee_base_units'])
   ref=funding['txid']+':'+str(funding['vout'])
   expected={k:funding[k] for k in ('quote_id','quote_sha256','coordinator_ca_sha256','fee')};expected['outpoint']=ref
   if 'payout_funding' not in w:p.send('observer','order_treasury_output',funding)
   elif w['payout_funding']!=expected:raise ValueError('Retained consensus funding differs')
   if order not in p.state()['payout_plans']:p.send('observer','plan_payout',dict(order=order,inputs=[ref],fee=1000))
   record=p.state()['payout_plans'][order]
   def fresh():
    proof=p.proof();stamp=datetime.datetime.fromisoformat(proof['signed_header']['header']['time'].replace('Z','+00:00')).timestamp()
    return proof if 0<=time.time()-stamp<30 else None
   proof=treasury_proof(p)
   request=dict(proof=proof,order=order,finalized_hash=record['hash'],request=dict(action='settle' if apply else 'preview',plan=native,plan_sha256=payment['plan_sha256']))
   if apply:
    if not trial.load('consensus-preview.json')['result']['ready_for_review']:raise ValueError('Successful installed preview required')
    trial.save('consensus-settle-intent.json',dict(order=order,plan_sha256=payment['plan_sha256'],finalized_hash=record['hash']))
   trial.save('consensus-request-'+str(time.time_ns())+'.json',request)
   result=subprocess.run(['/usr/bin/python3','-I','-B',str(PACKAGE/'bootstrap.py'),'--request'],input=json.dumps(request),text=True,capture_output=True,timeout=180)
   if result.returncode:
    trial.save('consensus-error-'+str(time.time_ns())+'.json',dict(exit_code=result.returncode,error=result.stderr[-3000:]));raise RuntimeError(result.stderr[-1500:])
   response=json.loads(result.stdout);trial.save('consensus-settlement.json' if apply else 'consensus-preview.json',response)
   return response
 finally:os.close(fd)
