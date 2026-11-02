import tempfile,unittest
from pathlib import Path
from identity import IdentityStore,message
class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'identity.sqlite3';self.now=1000
  self.store=IdentityStore(self.path,'https://192.168.0.102:9444','a'*64,lambda:self.now);self.address='y'+'A'*33
 def tearDown(self):self.temp.cleanup()
 def test_binding_and_one_time_proof(self):
  c=self.store.issue('provider',self.address);expected=message(c)
  self.assertIn('does not authorize payments',expected)
  r=self.store.redeem(c['nonce'],'signature',lambda a,s,m:a==self.address and s=='signature' and m==expected)
  self.assertFalse(r['payments_authorized'])
  with self.assertRaises(ValueError):self.store.redeem(c['nonce'],'signature',lambda *args:True)
 def test_rejected_signature_does_not_consume(self):
  c=self.store.issue('provider',self.address)
  with self.assertRaises(ValueError):self.store.redeem(c['nonce'],'bad',lambda *args:False)
  self.store.redeem(c['nonce'],'good',lambda *args:True)
 def test_expiry_and_clock_regression(self):
  c=self.store.issue('provider',self.address)
  for now in (999,1300):
   self.now=now
   with self.assertRaises(ValueError):self.store.redeem(c['nonce'],'signature',lambda *args:True)
 def test_expiry_during_verification(self):
  c=self.store.issue('provider',self.address)
  def slow(*args):self.now=1300;return True
  with self.assertRaises(ValueError):self.store.redeem(c['nonce'],'signature',slow)
 def test_coordinator_binding_persists(self):
  with self.assertRaises(ValueError):IdentityStore(self.path,'https://192.168.0.103:9444','a'*64)
  with self.assertRaises(ValueError):IdentityStore(self.path,'https://192.168.0.102:9444','b'*64)
 def test_public_origin_and_invalid_provider_rejected(self):
  with self.assertRaises(ValueError):IdentityStore(self.path,'https://8.8.8.8:9444','a'*64)
  with self.assertRaises(ValueError):self.store.issue('../provider',self.address)
if __name__=='__main__':unittest.main(verbosity=2)
