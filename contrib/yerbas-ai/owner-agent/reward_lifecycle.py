"""Operator-only request transitions. No provider route, signing or broadcasting."""
import hashlib,json,re,time
STATES={'pending_review','approved','payment_recorded','confirming','confirmed','reorged','unknown','rejected'}
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False)
def hex64(v):return isinstance(v,str) and re.fullmatch('[a-f0-9]{64}',v) is not None
def integer(v,lo,hi):return type(v) is int and lo<=v<=hi
def initialize(db):
 db.execute('CREATE TABLE IF NOT EXISTS reward_lifecycle(receipt TEXT PRIMARY KEY,body TEXT NOT NULL)')
 db.execute('CREATE TABLE IF NOT EXISTS reward_events(id TEXT PRIMARY KEY,receipt TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,result TEXT NOT NULL)')
 db.execute('CREATE TABLE IF NOT EXISTS reward_payments(receipt TEXT PRIMARY KEY,plan TEXT UNIQUE NOT NULL,txid TEXT UNIQUE NOT NULL)')
def transition(current,kind,data):
 if type(data) is not dict:raise ValueError('Object required')
 status=current['status'];next_value=dict(current)
 if kind=='approve':
  if status!='pending_review' or set(data)!={'amount_base_units','basis','verification_sha256'} or not integer(data['amount_base_units'],546,100000000) or data['basis']!='fixed_private_testnet_allowance' or not hex64(data['verification_sha256']):raise ValueError('Verified bounded test allowance required')
  next_value.update(data,status='approved')
 elif kind=='reject':
  if status!='pending_review' or set(data)!={'reason'} or data['reason'] not in ('duplicate_payment','verification_failed','operator_declined'):raise ValueError('Pending request and fixed reason required')
  next_value.update(data,status='rejected')
 elif kind=='bind_payment':
  if status!='approved' or set(data)!={'plan_sha256','txid'} or not all(hex64(v) for v in data.values()):raise ValueError('Approved request and verified payment binding required')
  next_value.update(data,status='payment_recorded')
 elif kind=='observe':
  if status not in ('payment_recorded','confirming','confirmed','reorged','unknown') or data.get('txid')!=current.get('txid'):raise ValueError('Immutable payment binding required')
  if set(data)!={'txid','state','confirmations','block_height','tip_height','blockhash','observed_at'}:raise ValueError('Exact observation required')
  if not integer(data['observed_at'],1,int(time.time())):raise ValueError('Invalid observation time')
  if data['state'] in ('confirming','confirmed'):
   if not integer(data['block_height'],0,2**31) or not integer(data['tip_height'],data['block_height'],2**31) or not integer(data['confirmations'],1,2**31) or data['confirmations']!=data['tip_height']-data['block_height']+1 or not hex64(data['blockhash']) or (data['state']=='confirmed')!=(data['confirmations']>=6):raise ValueError('Inconsistent chain observation')
  elif data['state'] in ('reorged','unknown'):
   if any(data[k] is not None for k in ('confirmations','block_height','tip_height','blockhash')):raise ValueError('Unavailable chain data must be null')
  else:raise ValueError('Invalid observation state')
  if current.get('observed_at',0)>data['observed_at']:raise ValueError('Older observation rejected')
  next_value.update({k:v for k,v in data.items() if k!='state'},status=data['state'])
 else:raise ValueError('Unsupported operator action')
 return next_value
def record(db,receipt,event_id,kind,data):
 if not hex64(event_id):raise ValueError('Stable event ID required')
 initialize(db)
 request=db.execute('SELECT response FROM requests WHERE receipt=?',(receipt,)).fetchone()
 if request is None:raise ValueError('Existing request required')
 payload=canonical(data);old=db.execute('SELECT receipt,kind,payload,result FROM reward_events WHERE id=?',(event_id,)).fetchone()
 if old:
  if old[:3]!=(receipt,kind,payload):raise ValueError('Conflicting event retry')
  return json.loads(old[3])
 row=db.execute('SELECT body FROM reward_lifecycle WHERE receipt=?',(receipt,)).fetchone()
 current=json.loads(row[0]) if row else {'status':'pending_review'}
 result=transition(current,kind,data)
 if kind=='bind_payment':db.execute('INSERT INTO reward_payments VALUES(?,?,?)',(receipt,data['plan_sha256'],data['txid']))
 body=canonical(result)
 db.execute('INSERT INTO reward_lifecycle VALUES(?,?) ON CONFLICT(receipt) DO UPDATE SET body=excluded.body',(receipt,body))
 db.execute('INSERT INTO reward_events VALUES(?,?,?,?,?)',(event_id,receipt,kind,payload,body))
 return result
def public(db,response):
 if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='reward_lifecycle'").fetchone():return response
 row=db.execute('SELECT body FROM reward_lifecycle WHERE receipt=?',(response['receipt'],)).fetchone()
 if row is None:return response
 lifecycle=json.loads(row[0]);return dict(response,schema=2,status=lifecycle['status'],lifecycle=lifecycle)
