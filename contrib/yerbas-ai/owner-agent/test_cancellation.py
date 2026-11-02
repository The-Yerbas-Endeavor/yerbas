import json,sqlite3,tempfile,unittest,socket
from pathlib import Path
from unittest.mock import patch
from cancellation_outbox import Outbox
from wallet_agent import Agent
RUN='a'*32;REQ='b'*32
class Client:
 def __init__(self):self.fail=False;self.calls=0;self.bad=False
 def cancel_contribution(self,key):
  self.calls+=1
  if self.fail:raise OSError('offline')
  return dict(schema=1,provider='wrong' if self.bad else socket.gethostname(),contribution=key,state='cancelled',reservation_state='released',payments_authorized=False)
class Tests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.path=Path(self.t.name)/'db';self.db=sqlite3.connect(self.path);self.addCleanup(self.db.close);self.o=Outbox(self.db);self.client=Client();self.running=False
 def control(self,method,run,rid):
  if method=='cancel':return dict(run_id=run,stop_recorded=True)
  return dict(id=run,state='running' if self.running else 'cancelled',contribution='text-'+run)
 def tick(self):self.o.next_poll=0;self.o.tick(self.control,self.client,socket.gethostname())
 def response(self):return self.db.execute('SELECT response FROM cancellation_outbox').fetchone()[0]
 def test_restart_retry_duplicate(self):
  self.o.enqueue(RUN,REQ);self.client.fail=True;self.tick();self.assertIsNone(self.response())
  self.o=Outbox(self.db);self.client.fail=False;self.tick();self.assertIsNotNone(self.response());self.tick();self.assertEqual(self.client.calls,2)
  self.o.enqueue(RUN,'c'*32);self.assertEqual(self.db.execute('select count(*) from cancellation_outbox').fetchone()[0],1)
 def test_waits_for_gpu_stop(self):
  self.o.enqueue(RUN,REQ);self.running=True;self.tick();self.assertEqual(self.client.calls,0)
  self.running=False;self.tick();self.assertIsNotNone(self.response())
 def test_forged_response_remains_pending(self):
  self.o.enqueue(RUN,REQ);self.client.bad=True;self.tick();self.assertIsNone(self.response())
 def test_pending_stop_does_not_starve_other_job(self):
  self.o.enqueue(RUN,REQ);self.o.enqueue('c'*32,'d'*32);self.running=True;self.tick()
  self.running=False;self.tick();self.assertIsNone(self.response());self.assertIsNotNone(self.db.execute('SELECT response FROM cancellation_outbox WHERE run_id=?',('c'*32,)).fetchone()[0])
 def test_conflicting_request_does_not_enqueue(self):
  a=Agent(Path(self.t.name),Path(self.t.name)/'agent',reward_client=self.client);self.addCleanup(a.close)
  a.db.execute('INSERT INTO requests VALUES(?,?,?)',(REQ,json.dumps(['provider.submit',{}],sort_keys=True),'{}'));a.db.commit()
  r=a.dispatch(dict(v=1,id=REQ,method='provider.cancel',params={'run_id':RUN}))
  self.assertFalse(r['ok']);self.assertEqual(a.db.execute('SELECT count(*) FROM cancellation_outbox').fetchone()[0],0)
 def test_broker_reply_lost_keeps_intent(self):
  a=Agent(Path(self.t.name),Path(self.t.name)/'agent',reward_client=self.client);self.addCleanup(a.close)
  with patch('wallet_agent.provider_control',side_effect=OSError('lost')):
   r=a.dispatch(dict(v=1,id=REQ,method='provider.cancel',params={'run_id':RUN}))
  self.assertFalse(r['ok']);self.assertEqual(a.db.execute('SELECT run_id FROM cancellation_outbox').fetchone()[0],RUN)
if __name__=='__main__':unittest.main()
