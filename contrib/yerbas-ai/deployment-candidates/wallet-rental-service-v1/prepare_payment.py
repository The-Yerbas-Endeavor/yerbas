"""Explicit fixed-price payout for the one retained independently reproduced epoch-3 unit."""
import argparse,fcntl,hashlib,json,os,secrets,shlex,subprocess,sys,time
from pathlib import Path
from context import digest,GENESIS
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'multi-gpu-slots-v1'))
from slot_attestation import verify
from rental_attestation import BINDING
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'coordinator-authority-candidate-v1'))
from assigned_execution import check_execution
from verifier_attestation import message as reproduction_message
def evidence_folder(receipt):
 matches=[]
 for p in BASE.glob('*/acceptance.json'):
  try:a=json.loads(p.read_text())
  except (ValueError,OSError):continue
  if a.get('accepted') is True and a.get('receipt')==receipt and a.get('verifier')=='anno2-u26':matches.append(p.parent)
 if len(matches)!=1:raise ValueError('Exactly one accepted independent reproduction required')
 return matches[0]

BASE=Path.home()/'.local/share/yerbas-ai-migration-v1/operator-v1/evidence'
def prepare(context):
 trial=context;STATE=context.state
 def ai(action,**args):return context.remote(action,**args)
 result=trial.load('results.json');q=trial.load('quote.json')
 if q['terms']['quote_id']!=context.quote or len(result['results'])!=1:raise ValueError('Wrong trial')
 scripts={}
 for row in result['results']:
  receipt=row['receipt'];t=row['terms'];folder=evidence_folder(receipt)
  if t.get('authority_generation')!={'authority':'anno2-coordinator-pilot','epoch':3}:raise ValueError('Assignment authority differs')
  read=lambda name:json.loads((folder/name).read_text())
  plan=read('request.json');plan['submitted']=(folder/'submitted.json').read_bytes()
  status=read('status.json');recomputed=(folder/'recomputed.json').read_bytes()
  checked=check_execution(plan,status,recomputed);envelope=read('envelope.json');claim=envelope['claim'];accept=read('acceptance.json')
  if claim['evidence_sha256']!=checked['evidence_sha256'] or claim['receipt']!=receipt or claim['artifact_sha256']!=row['artifact_sha256'] or claim['subject_provider']!=t['provider'] or claim['provider']!='anno2-u26' or plan['manifest']['contribution']!='text-'+t['run_id']:raise ValueError('Reproduction binding differs')
  ah=hashlib.sha256(reproduction_message(claim).encode()).hexdigest()
  if accept.get('accepted') is not True or accept['attestation_sha256']!=ah or accept['receipt']!=receipt or accept['verifier']!='anno2-u26':raise ValueError('Acceptance differs')
  if trial.rpc('verifymessage',claim['address'],envelope['signature'],reproduction_message(claim)) is not True:raise ValueError('Reproduction signature invalid')
  expected={k:t[k] for k in ('assignment_id','run_id','quote_id','ordinal','provider','recipe_identity','genesis','coordinator_ca_sha256')}
  expected.update(verifier='anno2-u26',verifier_address=claim['address'],terms_sha256=row['terms_sha256'],receipt=receipt,artifact_sha256=row['artifact_sha256'],verification_run_id=status['run_id'],verification_evidence_sha256=checked['evidence_sha256'],completed_at=result['observed_at'])
  if not expected['completed_at']<min(row['lease'],t['deadline']):raise ValueError('Completion outside original limit')
  name='slot-verification-'+receipt+'.json'
  if (STATE/name).exists():e=trial.load(name)
  else:
   now=int(time.time());c=dict(expected,schema=1,purpose='rental-work-unit-verification',profile=q['terms']['profile'] if 'profile' in q['terms'] else 'yerbas-private-reduced-collateral-testnet',nonce=secrets.token_hex(32),issued_at=now,expires_at=now+300)
   script='/home/anno2/.local/share/yerbas-ai-upgrades/paid-rental-v1/sign_rental.py';package='/home/anno2/.local/share/yerbas-ai-upgrades/yerbas-ai-wallet-5.0.0.0-modern6'
   out=subprocess.run(trial.SSH_ANNO2+[shlex.join(['python3','-B',script,package])],input=json.dumps(c),capture_output=True,text=True,timeout=60)
   if out.returncode:raise RuntimeError('Attestation signing failed: '+out.stderr[-1000:])
   sig=json.loads(out.stdout)
   e=verify(c,sig['signature'],expected,t,row['terms_sha256'],lambda a,s,m:trial.rpc('verifymessage',a,s,m),int(time.time()))
   trial.save(name,e);trial.save('slot-signature-'+receipt+'.json',dict(claim=c,signature=sig['signature']))
  if any(e[k]!=v for k,v in expected.items()):raise ValueError('Retained verification differs')
  trial.save_once('slot-intent-'+receipt+'.json',ai('verify',evidence=e,funding=trial.funding()))
  address=t['provider_identity']['address'];scripts[address]=trial.rpc('validateaddress',address)['scriptPubKey']
 payment=ai('payment',scripts=scripts,funding=trial.funding());trial.save_once('payment.json',payment)
 trial.save_once('verification-reference.json',dict(receipt=receipt,path=str(folder),attestation_sha256=ah))
 return {'independently_verified_units':1,'payment_prepared':True,'plan_sha256':payment['plan_sha256'],'plan':payment['plan']}
