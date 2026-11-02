"""Receipt-only transport bridge. Caller must load a root-approved per-run plan.
Not a training/resume adapter; deployment/privileged plan issuance is separate.
"""
import hashlib,json,re
from pathlib import Path

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
def origin(config,ca_sha):
 return hashlib.sha256(json.dumps([config['url'],hashlib.sha256(config['token'].encode()).hexdigest(),ca_sha]).encode()).hexdigest()
def validate(plan,executor,config,new_credentials,request):
 fields={'schema','request','executor_binding','worker_config_sha256','old_ca_sha256','new_ca_sha256','new_credentials_sha256','receipt','manifest_sha256'}
 if set(plan)!=fields or type(plan['schema']) is not int or plan['schema']!=1:raise ValueError('Exact per-run migration plan required')
 for k in ('worker_config_sha256','old_ca_sha256','new_ca_sha256','new_credentials_sha256','manifest_sha256'):
  if not isinstance(plan[k],str) or not re.fullmatch('[a-f0-9]{64}',plan[k]):raise ValueError('Invalid plan digest')
 if plan['request']!=request or set(request)!={'run_id','contribution'} or executor.get('binding')!=plan['executor_binding'] or plan['executor_binding'].get('request')!=request:raise ValueError('Original executor binding differs')
 if digest(config)!=plan['worker_config_sha256'] or config['contribution']!=request['contribution']:raise ValueError('Retained worker configuration differs')
 if set(new_credentials)!={'provider','token','url','ca'} or digest(new_credentials)!=plan['new_credentials_sha256']:raise ValueError('New transport differs')
 if any(new_credentials[k]!=config[k] for k in ('provider','token')):raise ValueError('Provider or token rotation forbidden')
 if plan['executor_binding'].get('enrollment')!=digest({k:config[k] for k in ('provider','token','url','ca')}):raise ValueError('Original enrollment differs')
 receipt=plan['receipt']
 if set(receipt)!={'receipt','contribution','sha256'} or receipt['contribution']!=request['contribution'] or not re.fullmatch('[a-f0-9]{32}',receipt['receipt']) or not re.fullmatch('[a-f0-9]{64}',receipt['sha256']):raise ValueError('Reviewed completed receipt required')
 if hashlib.sha256(Path(new_credentials['ca']).read_bytes()).hexdigest()!=plan['new_ca_sha256']:raise ValueError('New CA differs')
 return origin(config,plan['old_ca_sha256'])

def replay(directory,plan,executor,config,new_credentials,request,approved_identity,stop):
 from text_https import Client
 from text_worker import run_once
 from text_contribution import manifest_digest
 old_origin=validate(plan,executor,config,new_credentials,request)
 if config['expected_identity']!=approved_identity:raise ValueError('Approved recipe differs')
 client=Client(new_credentials['url'],new_credentials['token'],new_credentials['ca'])
 class ReceiptOnly:
  def submit(self,manifest,raw):
   if manifest_digest(manifest)!=plan['manifest_sha256'] or hashlib.sha256(raw).hexdigest()!=plan['receipt']['sha256']:raise ValueError('Reviewed result differs')
   receipt=client.submit(manifest,raw)
   if receipt!=plan['receipt']:raise ValueError('Migrated receipt differs')
   return receipt
 def never_execute(*args):raise RuntimeError('Migration replay cannot train')
 return run_once(directory,ReceiptOnly(),config['provider'],request['contribution'],old_origin,approved_identity,never_execute,stop,result_only=True)
