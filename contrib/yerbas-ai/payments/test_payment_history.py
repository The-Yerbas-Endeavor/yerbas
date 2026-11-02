import json
import tempfile
import unittest
from pathlib import Path
from payment_tracking import TrackingStore
from payment_history import read_history

class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'tracking.sqlite3'
  self.receipt='a'*32;self.plan='b'*64;self.txid='c'*64
 def tearDown(self):self.tmp.cleanup()
 def store(self):
  store=TrackingStore(self.path)
  with store.db() as db:
   db.execute('INSERT INTO intents VALUES (?,?)',(self.plan,json.dumps(dict(receipts=[self.receipt],candidate=dict(plan_sha256=self.plan)))))
   db.execute('INSERT INTO receipts VALUES (?,?)',(self.receipt,self.plan))
  return store
 def bind(self,store):
  with store.db() as db:db.execute('INSERT INTO bindings VALUES (?,?,?)',(self.plan,self.txid,json.dumps(dict(plan_sha256=self.plan,signed_txid=self.txid,signed_transaction_verified=True))))
 def observe(self,store,status,txid=None):
  with store.db() as db:db.execute('INSERT INTO observations(plan,body) VALUES (?,?)',(self.plan,json.dumps(dict(plan_sha256=self.plan,signed_txid=txid or self.txid,status=status,confirmed=status=='confirmed'))))
 def test_missing_does_not_create(self):
  self.assertEqual(read_history(self.path),{});self.assertFalse(self.path.exists())
 def test_unsigned_and_signed_are_not_payment_observations(self):
  store=self.store();self.assertIsNone(read_history(self.path)[self.receipt]['last_saved_observation'])
  self.bind(store);row=read_history(self.path)[self.receipt];self.assertEqual(row['signed_txid'],self.txid);self.assertIsNone(row['last_saved_observation'])
 def test_latest_observation_only_and_no_writes(self):
  store=self.store();self.bind(store);self.observe(store,'confirmed');self.observe(store,'reorged')
  before=self.path.read_bytes();row=read_history(self.path)[self.receipt]
  self.assertEqual(row['last_saved_observation']['status'],'reorged');self.assertFalse(row['current_chain_checked']);self.assertEqual(before,self.path.read_bytes())
 def test_confirmed_is_historical(self):
  store=self.store();self.bind(store);self.observe(store,'confirmed');row=read_history(self.path)[self.receipt]
  self.assertTrue(row['last_saved_observation']['confirmed']);self.assertFalse(row['current_chain_checked'])
 def test_wrong_transaction_refused(self):
  store=self.store();self.bind(store);self.observe(store,'confirmed','d'*64)
  with self.assertRaises(ValueError):read_history(self.path)
 def test_wrong_receipt_binding_refused(self):
  store=self.store()
  with store.db() as db:db.execute('UPDATE receipts SET receipt=?',('e'*32,))
  with self.assertRaises(ValueError):read_history(self.path)
 def test_symlink_refused(self):
  self.store();link=self.path.parent/'link';link.symlink_to(self.path)
  with self.assertRaises(ValueError):read_history(link)
 def test_wrong_database_refused(self):
  store=self.store()
  with store.db() as db:db.execute('PRAGMA application_id=1')
  with self.assertRaises(ValueError):read_history(self.path)
if __name__=='__main__':unittest.main()
