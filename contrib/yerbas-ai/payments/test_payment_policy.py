import json,tempfile,unittest
from pathlib import Path
from payment_policy import load_policy
from identity import PROFILE,GENESIS
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name)/'policy';self.policy=dict(schema=1,kind='testnet-unsigned-reward-draft-policy',profile=PROFILE,genesis=GENESIS,rate_yerb_per_approved_gpu_hour='1',time_basis='operator-approved GPU-active milliseconds',approval_scope='rate only; no contribution time approved',signing_authorized=False,broadcast_authorized=False,provisional=True)
 def tearDown(self):self.tmp.cleanup()
 def load(self):self.p.write_text(json.dumps(self.policy));return load_policy(self.p)
 def test_rate_only(self):
  r=self.load();self.assertEqual(r['policy']['rate_yerb_per_approved_gpu_hour'],'1');self.assertFalse(r['policy']['broadcast_authorized']);self.assertEqual(len(r['policy_sha256']),64)
 def test_spending_or_wrong_network_rejected(self):
  for field,value in [('broadcast_authorized',True),('signing_authorized',True),('profile','main'),('genesis','0'*64),('schema',True)]:
   old=self.policy[field];self.policy[field]=value
   with self.assertRaises(ValueError):self.load()
   self.policy[field]=old
 def test_bad_rates_rejected(self):
  for rate in ('0','NaN','1e3',True):
   self.policy['rate_yerb_per_approved_gpu_hour']=rate
   with self.assertRaises(ValueError):self.load()
 def test_duplicate_json_rejected(self):
  self.p.write_text('{"schema":1,"schema":1}')
  with self.assertRaises(ValueError):load_policy(self.p)
if __name__=='__main__':unittest.main()
