"""Reconcile this exact confirmed payout and completed work; never send or execute."""
import base64,fcntl,json,os,sqlite3,sys,tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
OUT=HERE.parent
PACKAGE=Path('/opt/yerbas-ai/post-cutover-treasury-1185a6dc6b3eae65')
sys.path.insert(0,str(PACKAGE))
import bootstrap
bootstrap.checked(PACKAGE,0)
from signer_policy import read_protected
from authority_fence import AuthorityFence
from retained_settlement import RetainedJournal
from signature_verifier import Consensus,verify_signed
sys.path.insert(0,str(OUT/'coordinator-fencing-v1'))
from payout_reconciliation import reconcile
from payment_chain_anchor import anchor,agree
sys.path.insert(0,str(HERE))
from context import digest
from chain_reader import node
from rental_funding import base_units
from wallet_rpc import request as owner_request
sys.path.insert(0,str(OUT/'wallet-consensus-rental-v1'))
from paid_pilot import session as open_session
def copydb(source,dest):
 a=sqlite3.connect(Path(source).as_uri()+'?mode=ro',uri=True);b=sqlite3.connect(dest)
 try:a.backup(b)
 finally:a.close();b.close()
def close(context):
 STATE=context.state;trial=context;QUOTE=context.quote
 settled=context.load("consensus-settlement.json");TX=settled["result"]["txid"]
 RUN=context.load("results.json")["results"][0]["assignment"]
 ORDER=digest(dict(quote=QUOTE,assignment=RUN))
 def session():return open_session(STATE/"commands",context.load("plan.json"))
 os.umask(0o077)
 fd=os.open(STATE/'lock',os.O_RDWR|os.O_NOFOLLOW)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  payment=trial.load('payment.json');plan=payment['plan'];settled=trial.load('consensus-settlement.json')
  if settled['result']['txid']!=TX or plan['quote_id']!=QUOTE or digest(plan)!=payment['plan_sha256'] or plan['receipts'][0]['assignment_id']!=RUN:raise ValueError('Exact completed payout required')
  anchors=[anchor(node(h),genesis=plan['genesis'],txid=TX) for h in ('u26-2T','anno2-u26')];agree(*anchors)
  tx=node('u26-2T')('getrawtransaction',TX,True)
  if len(tx['vout'])!=1 or tx['vout'][0]['scriptPubKey']['hex']!=plan['outputs'][0]['script'] or base_units(tx['vout'][0]['value'])!=100000:raise ValueError('Reward output differs')
  status=owner_request('provider.slot_status',{'run_id':RUN})
  if status['state']!='completed' or status['slot']!='gpu-1' or not status['restart_blocked']:raise ValueError('Completed fenced run required')
  shutdown=owner_request('provider.slot_shutdown',{'run_id':RUN})
  if shutdown['assignment_id']!=RUN or not shutdown['fenced'] or shutdown['process_running'] or shutdown['pending_restarts']:raise ValueError('Quiescent exact work required')
  release=context.remote('release',evidence=shutdown,txid=TX)
  if not release['release']['released'] or not release['accounting_passed']:raise ValueError('Release failed')
  trial.save_once('paid-release.json',dict(txid=TX,result=release,shutdown=shutdown))
  policy=read_protected(Path('/etc/yerbas-ai/local-settlement-v1.json'))
  if (policy['runtime']['authority'],policy['runtime']['epoch'])!=('anno2-coordinator-pilot',3):raise ValueError('Wrong authority')
  native=policy['native'];consensus=Consensus(native['consensus_binary'],native['consensus_sha256'])
  verify=lambda raw,expected,script:verify_signed(raw,expected,script,consensus)
  def observe(txid):
   if txid!=TX:raise ValueError('Unexpected transaction')
   v=node('u26-2T')('getrawtransaction',txid,True)
   return dict(txid=v['txid'],known=True,confirmations=v.get('confirmations',0))
  guard=Path(policy['runtime']['guard']);journal=RetainedJournal(Path(policy['runtime']['journal']),'payout')
  def retire(g,j):return reconcile(g,j,plan,payment['plan_sha256'],observe,verify,[node('u26-2T'),node('anno2-u26')])
  with tempfile.TemporaryDirectory(prefix='paid-retirement-') as tmp:
   root=Path(tmp);(root/'payout').mkdir()
   with journal.locked():
    copydb(guard,root/'guard.sqlite3');copydb(journal.path,root/'payout/payout-signing.sqlite3')
   (root/'payout/payout-signing.lock').touch(mode=0o600)
   g=AuthorityFence(root/'guard.sqlite3');j=RetainedJournal(root/'payout','payout')
   first=retire(g,j);second=retire(g,j)
   if not second['duplicate'] or first['proof_sha256']!=second['proof_sha256']:raise ValueError('Replay rehearsal failed')
  retirement=retire(AuthorityFence(guard),journal)
  (STATE/'live-payout-retirement.json').write_text(json.dumps(retirement,indent=2)+'\n')
  with session() as p:
   work=p.state()['orders'][ORDER]
   artifact=plan['receipts'][0]['artifact_sha256']
   if work['artifact']!=artifact:raise ValueError('Committed artifact differs')
   if work['state']=='verified':p.send('observer','payout_observed',dict(order=ORDER,txid=TX,vout=0,amount=100000,recipient=p.ids['provider']))
   elif work['state']!='paid' or work['payout']!=TX+':0':raise ValueError('Conflicting payout')
   claim=dict(order=ORDER,artifact=artifact,payout=TX+':0',evidence_sha256=shutdown['evidence_sha256'],fenced=True,process_running=False,pending_restarts=False)
   old=p.state()['orders'][ORDER].get('shutdown_attestations',{})
   if old:
    claim=next(iter(old.values()))
    if claim['order']!=ORDER or claim['payout']!=TX+':0' or not claim['fenced'] or claim['process_running'] or claim['pending_restarts']:raise ValueError('Retained shutdown differs')
   for role in ('provider','observer'):
    prior=p.state()['orders'][ORDER].get('shutdown_attestations',{}).get(p.ids[role])
    if prior is None:p.send(role,'attest_shutdown',claim)
    elif prior!=claim:raise ValueError('Conflicting shutdown')
   if not p.state()['orders'][ORDER].get('capacity_released'):p.send('provider','release_capacity',dict(order=ORDER,evidence_sha256=claim['evidence_sha256']))
   def replicated():
    states=[json.loads(base64.b64decode(p.call(i,'abci_query')['response']['value'])) for i in range(4)]
    return len({digest(s['orders'][ORDER]) for s in states})==1 and all(s['orders'][ORDER]['state']=='paid' and s['orders'][ORDER]['capacity_released'] for s in states)
   p.wait(replicated)
   proof=p.proof();(STATE/'paid-released-proof.json').write_text(json.dumps(proof))
  db=sqlite3.connect((Path.home()/'.local/share/yerbas-consensus-provider-v1/state.sqlite3').as_uri()+'?mode=ro',uri=True)
  try:
   matches=[(json.loads(r),s,json.loads(c) if c else None) for r,s,c in db.execute('SELECT request,status,receipt FROM actions') if json.loads(r).get('order')==ORDER]
   if len(matches)!=1 or matches[0][1]!='complete' or matches[0][2].get('completed') is not True:raise ValueError('Retained no-resend completion missing')
  finally:db.close()
  result=dict(passed=True,quote_id=QUOTE,run_id=RUN,txid=TX,reward_base_units=100000,confirmations=anchors[0]['confirmations'],tip_height=anchors[0]['tip_height'],independent_verification=True,coordinator_slot_released=True,consensus_replicas=4,consensus_paid=True,consensus_capacity_released=True,signer_admission_closed=retirement['authority_admission_closed'],provider_completion_retained=True,same_owner_test=True,independent_operators_demonstrated=False,coins_sent=False,gpu_started=False,scope='Successful paid-work pilot without rented AI server; trusted committee and custodial treasury, not permissionless admission')
  context.save_once('acceptance.json',result)
  return result
 finally:os.close(fd)
