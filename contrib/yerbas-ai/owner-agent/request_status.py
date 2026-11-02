"""Validate coordinator request status before exposing it to the wallet."""
import re,time
from reward_lifecycle import hex64,integer,STATES
def validate(r,receipt,provider):
 base={'schema','request_id','receipt','provider','status','requested_at','payment_authorized','gpu_time_approved'}
 if type(r) is not dict or r.get('receipt')!=receipt or r.get('provider')!=provider or not hex64(r.get('request_id')) or r.get('payment_authorized') is not False or r.get('gpu_time_approved') is not False or not integer(r.get('requested_at'),1,int(time.time())):raise ValueError('Invalid request binding')
 if type(r.get('schema')) is not int:raise ValueError('Invalid schema')
 if r['schema']==1:
  if set(r)!=base or r['status']!='pending_review':raise ValueError('Invalid pending request')
  return r
 if r['schema']!=2 or set(r)!=base|{'lifecycle'} or type(r['lifecycle']) is not dict:raise ValueError('Invalid lifecycle')
 d=r['lifecycle'];state=r['status']
 if d.get('status')!=state or state not in STATES or state=='pending_review':raise ValueError('Invalid state')
 if state=='rejected':
  if set(d)!={'status','reason'} or d['reason'] not in ('duplicate_payment','verification_failed','operator_declined'):raise ValueError('Invalid rejection')
  return r
 keys={'status','amount_base_units','basis','verification_sha256'}
 if not integer(d.get('amount_base_units'),546,100000000) or d.get('basis')!='fixed_private_testnet_allowance' or not hex64(d.get('verification_sha256')):raise ValueError('Invalid allowance')
 if state!='approved':
  keys|={'plan_sha256','txid'}
  if not hex64(d.get('plan_sha256')) or not hex64(d.get('txid')):raise ValueError('Invalid payment binding')
 if state not in ('approved','payment_recorded'):
  keys|={'confirmations','block_height','tip_height','blockhash','observed_at'}
  if not integer(d.get('observed_at'),1,int(time.time())):raise ValueError('Invalid time')
  if state in ('confirmed','confirming'):
   if not integer(d.get('block_height'),0,2**31) or not integer(d.get('tip_height'),d['block_height'],2**31) or not integer(d.get('confirmations'),1,2**31) or d['confirmations']!=d['tip_height']-d['block_height']+1 or (state=='confirmed')!=(d['confirmations']>=6) or not hex64(d.get('blockhash')):raise ValueError('Invalid confirmation')
  elif any(d.get(k) is not None for k in ('confirmations','block_height','tip_height','blockhash')):raise ValueError('Unknown observation must be null')
 if set(d)!=keys:raise ValueError('Unexpected lifecycle fields')
 return r
