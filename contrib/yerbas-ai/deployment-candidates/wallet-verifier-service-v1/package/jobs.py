"""Durable, non-repeating execution intents for the fixed testnet verifier."""
import json,re,sqlite3,time
class Journal:
 def __init__(self,path):
  self.db=sqlite3.connect(path)
  self.db.execute('PRAGMA synchronous=FULL')
  self.db.execute('CREATE TABLE IF NOT EXISTS jobs(run TEXT PRIMARY KEY,phase TEXT NOT NULL,created INTEGER NOT NULL,result TEXT)');self.db.commit()
 def recover(self):
  with self.db:self.db.execute("UPDATE jobs SET phase='interrupted' WHERE phase IN ('preparing','ready','running')")
 def create(self,run):
  with self.db:self.db.execute("INSERT INTO jobs VALUES (?,'preparing',?,NULL)",(run,int(time.time())))
 def set(self,run,phase,result=None):
  with self.db:self.db.execute('UPDATE jobs SET phase=?,result=? WHERE run=?',(phase,json.dumps(result) if result is not None else None,run))
 def get(self,run):
  row=self.db.execute('SELECT phase,result FROM jobs WHERE run=?',(run,)).fetchone()
  if row is None:return {'run_id':run,'phase':'absent'}
  return {'run_id':run,'phase':row[0],'result':json.loads(row[1]) if row[1] else None}

def request(value):
 if type(value)is not dict or set(value)!={'action','run_id'} or value['action'] not in ('prepare','execute','status','cancel') or type(value['run_id'])is not str or not re.fullmatch('[a-f0-9]{32}',value['run_id']):raise ValueError('Fixed verifier action and run identifier required')
 return value['action'],value['run_id']

class Jobs:
 def __init__(self,journal,executor):self.journal=journal;self.executor=executor;self.active=None;journal.recover()
 def handle(self,value):
  action,run=request(value)
  if self.active:
   ended=self.executor.poll()
   if ended is not None:self.journal.set(self.active,'complete' if ended['exit_code']==0 else 'failed',ended);self.active=None
  record=self.journal.get(run)
  if action=='status':return record
  if action=='prepare':
   if self.active:raise ValueError('Verifier busy')
   if record['phase']!='absent':raise ValueError('Retained run: observation only, no restart')
   self.journal.create(run);self.active=run
   try:self.executor.prepare(run)
   except BaseException:
    # Retain the launch intent even if preparation raised after spawning.
    self.executor.cancel();self.journal.set(run,'failed');self.active=None;raise
   self.journal.set(run,'ready')
  elif action=='execute':
   if self.active!=run or record['phase']!='ready':raise ValueError('Fresh prepared run required')
   self.journal.set(run,'running') # Durable intent precedes opening the GPU gate.
   self.executor.execute(run)
  elif action=='cancel':
   if self.active==run:self.executor.cancel();self.journal.set(run,'cancelled');self.active=None
  return self.journal.get(run)
 def close(self):
  if self.active:self.executor.cancel();self.journal.set(self.active,'interrupted');self.active=None
