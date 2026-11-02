"""Offline testnet GPU-time reward arithmetic. Creates no transaction or RPC call."""
from decimal import Decimal
import hashlib,json,re
from identity import PROFILE
HOUR_MS=3600000
BASE_UNITS=100000000

def rate_units(rate):
 if not isinstance(rate,str) or not re.fullmatch(r'(0|[1-9][0-9]{0,8})(\.[0-9]{1,8})?',rate):raise ValueError('Explicit nonnegative decimal rate with at most 8 fractional digits required')
 value=int(Decimal(rate)*BASE_UNITS)
 if value<=0:raise ValueError('Rate must be positive')
 return value

def build_draft(receipts,approvals,rate,identity_lookup):
 """Receipts must come from audited coordinator storage; identity_lookup must
 return persisted, verified ownership proof. Approvals are explicit operator
 decisions, not worker-reported elapsed time. This function never approves time.
 """
 units=rate_units(rate)
 if not isinstance(receipts,dict) or not isinstance(approvals,list) or not 1<=len(approvals)<=100:raise ValueError('Bounded approvals required')
 seen=set();items=[];outputs={}
 for a in approvals:
  if not isinstance(a,dict) or set(a)!={'receipt','provider','address','approved_gpu_ms','approval_id','identity_proof'}:raise ValueError('Explicit approval fields required')
  for field,size in (('receipt',32),('approval_id',32),('identity_proof',64)):
   if not isinstance(a[field],str) or not re.fullmatch('[a-f0-9]{'+str(size)+'}',a[field]):raise ValueError('Invalid approval identity')
  if a['receipt'] in seen:raise ValueError('Duplicate receipt cannot earn twice')
  seen.add(a['receipt']);r=receipts.get(a['receipt'])
  if not r or r['state']!='completed' or r['provider']!=a['provider'] or not re.fullmatch('[a-f0-9]{64}',r['artifact_sha256']):raise ValueError('Completed matching receipt required')
  if r.get('independently_confirmed') is not True or not isinstance(r.get('confirmation_sha256'),str) or not re.fullmatch('[a-f0-9]{64}',r['confirmation_sha256']):raise ValueError('Independent contribution confirmation required')
  if r.get('signed_verification_accepted') is not True or not isinstance(r.get('attestation_sha256'),str) or not re.fullmatch('[a-f0-9]{64}',r['attestation_sha256']):raise ValueError('Accepted signed contribution verification required')
  ms=a['approved_gpu_ms'];cap=r['max_runtime_seconds']
  if type(ms) is not int or type(cap) is not int or not 1<=cap<=120 or not 0<ms<=cap*1000:raise ValueError('Approved GPU time exceeds fixed-recipe bound')
  proof=identity_lookup(a['identity_proof'])
  if (not proof or proof.get('provider')!=a['provider'] or proof.get('address')!=a['address'] or proof.get('profile')!=PROFILE):raise ValueError('Verified provider/address identity required')
  if not isinstance(a['address'],str) or not re.fullmatch('[1-9A-HJ-NP-Za-km-z]{26,50}',a['address']):raise ValueError('Invalid address format')
  amount=ms*units//HOUR_MS
  item={**a,'artifact_sha256':r['artifact_sha256'],'confirmation_sha256':r['confirmation_sha256'],'attestation_sha256':r['attestation_sha256'],'amount_base_units':amount}
  items.append(item);outputs[a['address']]=outputs.get(a['address'],0)+amount
 body={'schema':1,'profile':PROFILE,'kind':'unsigned-payment-plan','basis':'operator-approved GPU-active milliseconds per completed receipt','rate_base_units_per_gpu_hour':units,'rounding':'floor per receipt to 1e-8 YERB','items':sorted(items,key=lambda x:x['receipt']),'outputs':[{'address':a,'amount_base_units':v} for a,v in sorted(outputs.items())],'total_base_units':sum(outputs.values()),'transaction_created':False,'spending_authorized':False,'simulated_credits_converted':False}
 body['plan_sha256']=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 return body
