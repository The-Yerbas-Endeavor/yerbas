import sys,unittest
from pathlib import Path
from unittest.mock import patch
H=Path(__file__).resolve().parent
sys.path[:0]=[str(H/'package'),str(H.parent/'coordinator-fencing-v1'),str(H.parent/'multi-gpu-slots-v1'),str(H.parent/'work-refunds-v1')]
import rental
import test_funded_slot_scheduler as fixtures
from work_refunds import WorkRefunds
from coordinator_generation import enroll
class Tests(unittest.TestCase):
 def setUp(self):
  f=self.f=fixtures.FullStoreTests();f.setUp();self.addCleanup(f.doCleanups)
  self.store=WorkRefunds(f.path,'c'*64,clock=lambda:f.now,unit_price_base_units=100000)
  for n,v in [('store_open',lambda:self.store),('BUYER','buyer'),('PROVIDER','alice')]:
   p=patch.object(rental,n,v);p.start();self.addCleanup(p.stop)
  with self.store.tx() as db:
   enroll(db,'anno2-coordinator-pilot',1);db.execute('UPDATE ai_work_authority_v1 SET epoch=3');db.execute('CREATE TABLE ai_authority_maintenance_v1(active INTEGER)');db.execute('CREATE TABLE buyer_destinations_v1(script TEXT PRIMARY KEY,quote TEXT UNIQUE,buyer TEXT)')
 def quote(self,q='e'*32):return self.store.paid_quote('buyer',q,1,1,'76a914'+'1'*40+'88ac')
 def call(self,action='status',q='e'*32,**fields):return rental.execute(dict(action=action,quote_id=q,**fields))
 def test_multiple_quotes_no_global_binding(self):
  self.quote();self.quote('b'*32)
  self.assertTrue(self.call()['quote_exists']);self.assertTrue(self.call(q='b'*32)['quote_exists']);self.assertFalse(self.call(q='c'*32)['quote_exists'])
 def test_wrong_owner_refused(self):
  self.quote()
  with self.store.tx() as db:db.execute("UPDATE fixed_quotes_v1 SET buyer='stranger'")
  with self.assertRaises(ValueError):self.call()
 def test_multunit_refused(self):
  self.store.paid_quote('buyer','e'*32,2,1,'76a914'+'1'*40+'88ac')
  with self.assertRaises(ValueError):self.call()
 def test_frozen_refused(self):
  self.quote()
  with self.store.tx() as db:db.execute('INSERT INTO ai_authority_maintenance_v1 VALUES(1)')
  with self.assertRaises(ValueError):self.call()
 def test_no_receipt_no_payment(self):
  self.quote()
  with self.assertRaises(ValueError):self.call('payment',scripts={},funding={})
 def test_cross_quote_evidence_refused(self):
  with self.assertRaises(ValueError):self.call('verify',evidence={'quote_id':'b'*32,'provider':'alice'},funding={})
 def test_unknown_actions_refused(self):
  with self.assertRaises(ValueError):self.call('shell')
 def test_extra_fields_refused(self):
  with self.assertRaises(ValueError):self.call(path='/tmp/file')
 def test_bad_quote_refused(self):
  with self.assertRaises(ValueError):self.call(q='../bad')
 def test_result_read_does_not_create_assignments(self):
  self.quote();r=self.call('results');self.assertEqual(r['results'],[]);self.assertEqual(self.call()['trial_assignments'],0)
if __name__=='__main__':unittest.main()
