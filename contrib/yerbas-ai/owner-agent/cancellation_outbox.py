"""Durable owner-stop reconciliation. Retry the same broker request after restart."""
import json,re,time
ID=re.compile('[a-f0-9]{32}')
class Outbox:
 def __init__(self,db):
  self.db=db;self.next_poll=0
  db.execute('CREATE TABLE IF NOT EXISTS cancellation_outbox(run_id TEXT PRIMARY KEY,request_id TEXT NOT NULL,response TEXT,last_attempt REAL NOT NULL DEFAULT 0,last_error TEXT)');db.commit()
 def enqueue(self,run,request):
  if not ID.fullmatch(run) or not ID.fullmatch(request):raise ValueError('Invalid stop identity')
  with self.db:
   if self.db.execute('SELECT 1 FROM cancellation_outbox WHERE run_id=?',(run,)).fetchone():return
   if self.db.execute('SELECT count(*) FROM cancellation_outbox').fetchone()[0]>=10000:raise ValueError('Cancellation queue full')
   self.db.execute('INSERT INTO cancellation_outbox(run_id,request_id,response) VALUES(?,?,NULL)',(run,request))
 def tick(self,control,client,provider,clock=time.monotonic):
  now=clock()
  if now<self.next_poll:return
  self.next_poll=now+5
  row=self.db.execute('SELECT run_id,request_id FROM cancellation_outbox WHERE response IS NULL ORDER BY last_attempt,rowid LIMIT 1').fetchone()
  if row is None or client is None:return
  run,request=row
  with self.db:self.db.execute('UPDATE cancellation_outbox SET last_attempt=? WHERE run_id=?',(time.time(),run))
  try:
   # Recover lost broker acknowledgement with the original idempotency key.
   ack=control('cancel',run,request)
   if ack.get('run_id')!=run or ack.get('stop_recorded') is not True:raise ValueError('Stop not acknowledged')
   status=control('status',run,request)
   if status.get('id')!=run or status.get('state') not in ('cancelled','failed','completed'):return
   contribution=status.get('contribution')
   if not isinstance(contribution,str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}',contribution):raise ValueError('Invalid contribution')
   result=client.cancel_contribution(contribution)
   if (set(result)!={'schema','provider','contribution','state','reservation_state','payments_authorized'} or result['schema']!=1 or result['provider']!=provider or result['contribution']!=contribution or result['payments_authorized'] is not False or (result['state'],result['reservation_state']) not in (('cancelled','released'),('expired','released'),('revoked','released'),('completed','settled'))):raise ValueError('Invalid cancellation response')
   with self.db:self.db.execute('UPDATE cancellation_outbox SET response=?,last_error=NULL WHERE run_id=? AND response IS NULL',(json.dumps(result,sort_keys=True),run))
  except Exception as exc:
   # Keep durable pending intent; service loop retries without a new job/payment.
   with self.db:self.db.execute('UPDATE cancellation_outbox SET last_error=? WHERE run_id=?',(type(exc).__name__,run))
   return
