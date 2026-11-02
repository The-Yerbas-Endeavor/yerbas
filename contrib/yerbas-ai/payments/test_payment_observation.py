import unittest
from payment_observation import assess
class Tests(unittest.TestCase):
 def setUp(self):
  self.b=dict(plan_sha256='a'*64,signed_txid='b'*64,signed_transaction_verified=True)
  self.o=dict(available=True,txid='b'*64,confirmations=6,block_height=12,tip_height=17,blockhash='c'*64,active_hash_at_height='c'*64)
 def test_unsigned_is_never_confirmed(self):
  self.assertEqual(assess(None,self.o)['status'],'awaiting_signed_transaction_binding')
 def test_valid_confirmation_is_not_irreversible(self):
  result=assess(self.b,self.o);self.assertTrue(result['confirmed']);self.assertFalse(result['irreversible']);self.assertFalse(result['automatic_retry'])
 def test_insufficient_depth(self):
  self.assertEqual(assess(self.b,dict(self.o,confirmations=5,tip_height=16))['status'],'confirming')
 def test_reorg_revokes_confirmation(self):
  previous=assess(self.b,self.o)
  for o in (dict(self.o,active_hash_at_height='d'*64),dict(self.o,confirmations=0,in_mempool=True)):
   result=assess(self.b,o,previous);self.assertEqual(result['status'],'reorged');self.assertFalse(result['confirmed'])
 def test_depth_loss_revokes_confirmation(self):
  previous=assess(self.b,self.o)
  result=assess(self.b,dict(self.o,confirmations=5,tip_height=16),previous)
  self.assertTrue(result['confirmation_lost']);self.assertFalse(result['confirmed'])
 def test_conflict_and_disappearance_never_retry(self):
  for o,status in [(dict(self.o,confirmations=-1),'conflicted'),(dict(self.o,confirmations=0,in_mempool=False),'not_seen'),(None,'unknown')]:
   result=assess(self.b,o);self.assertEqual(result['status'],status);self.assertFalse(result['automatic_retry'])
 def test_stale_confirmation_count_fails_closed(self):
  self.assertEqual(assess(self.b,dict(self.o,tip_height=18))['status'],'inconsistent_snapshot')
 def test_cross_payment_or_missing_chain_lookup_rejected(self):
  for o in (dict(self.o,txid='d'*64),dict(self.o,active_hash_at_height=None),dict(self.o,confirmations=True)):
   with self.assertRaises(ValueError):assess(self.b,o)
  with self.assertRaises(ValueError):assess(self.b,self.o,dict(plan_sha256='d'*64))
 def test_unverified_signed_binding_rejected(self):
  with self.assertRaises(ValueError):assess(dict(self.b,signed_transaction_verified=False),self.o)
 def test_reconfirmation_after_reorg(self):
  old=assess(self.b,dict(self.o,active_hash_at_height='d'*64))
  new=assess(self.b,self.o,old);self.assertTrue(new['confirmed'])
if __name__=='__main__':unittest.main()
