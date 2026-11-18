"""Noninteractive verification with a durable intent and observation-only recovery."""
import hashlib,json,re,subprocess,uuid
from pathlib import Path

def acceptance(folder,receipt):
 p=folder/'acceptance.json'
 if not p.exists():return None
 value=json.loads(p.read_text())
 if value.get('accepted') is not True or value.get('receipt')!=receipt or value.get('verifier')!='anno2-u26' or not re.fullmatch('[a-f0-9]{64}',value.get('attestation_sha256','')):raise ValueError('Verification acceptance differs')
 return dict(receipt=receipt,path=str(folder),attestation_sha256=value['attestation_sha256'])

def verify(context,evidence_root,command,run=subprocess.run):
 rows=context.load('results.json')['results']
 if len(rows)!=1 or not re.fullmatch('[a-f0-9]{32}',rows[0].get('receipt','')):raise ValueError('One completed receipt required')
 receipt=rows[0]['receipt'];intent_path=context.state/'verification-intent.json'
 if intent_path.exists():
  intent=context.load('verification-intent.json')
  if set(intent)!={'receipt','evidence'} or intent['receipt']!=receipt:raise ValueError('Conflicting verification intent')
  folder=Path(intent['evidence'])
  if folder.parent!=evidence_root or not re.fullmatch('[a-f0-9]{32}',folder.name):raise ValueError('Retained evidence path differs')
  result=acceptance(folder,receipt)
  if result is None:raise ValueError('Verification requires reconciliation; no automatic GPU retry')
 else:
  matches=[]
  for folder in evidence_root.iterdir():
   if not folder.is_dir() or folder.is_symlink():continue
   p=folder/'acceptance.json'
   if not p.exists():continue
   value=json.loads(p.read_text())
   if value.get('receipt')==receipt:matches.append(acceptance(folder,receipt))
  if len(matches)>1:raise ValueError('Ambiguous verification history')
  if matches:result=matches[0]
  else:
   folder=evidence_root/uuid.uuid4().hex
   argv=command(receipt,folder) # Pin/configuration checks precede retention.
   context.save('verification-intent.json',dict(receipt=receipt,evidence=str(folder)))
   response=run(argv,check=False,timeout=300,capture_output=True,text=True)
   context.save('verification-command-result.json',dict(exit_code=response.returncode,
    stderr=getattr(response,'stderr','')[-6000:],stdout=getattr(response,'stdout','')[-6000:]))
   if response.returncode:raise ValueError('Verification refused; reconcile retained run before retry')
   result=acceptance(folder,receipt)
   if result is None:raise ValueError('Missing accepted evidence; no automatic GPU retry')
 context.save_once('verification-reference.json',result)
 return result

def installed_command(receipt,evidence):
 base=Path.home()/'.local/share/yerbas-ai-migration-v1';addon=base/'operator-v4'
 manifest=json.loads((addon/'OPERATOR.json').read_text())
 for name,pin in manifest['files'].items():
  rel=Path(name)
  if rel.is_absolute() or '..' in rel.parts:raise ValueError('Unsafe operator path')
  p=addon/rel
  if p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=pin:raise ValueError('Operator addon changed')
 config=base/'operator-v1'
 # Fixed enrolled paths are loaded by the same owner operator entrypoint.
 import importlib.util
 entry=Path(__file__).resolve().parent.parent/'yerbas-ai-operator.py'
 spec=importlib.util.spec_from_file_location('wallet_verification_owner',entry);operator=importlib.util.module_from_spec(spec);spec.loader.exec_module(operator)
 return ['/usr/bin/python3','-I','-B',str(addon/'coordinator-authority-candidate-v1/operator_command.py'),'--state',str(operator.STATE),'--binding',str(base/'binding.json'),'--dataset',str(operator.DATASET),'--confirmations',str(operator.CONFIRMATIONS),'--verifier','anno2-u26','--intake-config',str(config/'anno2-intake.json'),'--executor-config',str(config/'anno2-executor.json'),'--receipt',receipt,'--evidence',str(evidence),'--run']
