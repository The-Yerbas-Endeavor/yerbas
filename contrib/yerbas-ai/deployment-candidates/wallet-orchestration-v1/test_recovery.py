import tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
from workflow import validate_request
from recover_unissued_verification import eligible
class Tests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name)
  self.request=dict(schema=1,network='yerbas-private-reduced-collateral-testnet',quote='a'*32,assignment='b'*32,terms_sha256='c'*64,deposit_txid='d'*64,deposit_vout=0,maximum_base_units=101000,provider_reward_base_units=100000,slot='gpu-1',automatic_settlement=True)
  self.records={'authorization.json':self.request,'verify-intent.json':dict(step='verify',authorization_sha256=validate_request(self.request)),'verification-command-result.json':dict(exit_code=1),'verification-intent.json':dict(receipt='e'*32,evidence=str(self.root/('f'*32)))}
  self.j=Mock();self.j.read.side_effect=self.records.get
 def test_returned_unissued_failure(self):self.assertEqual(eligible(self.j,self.root)[0],self.request)
 def test_unknown_exit_refused(self):
  del self.records['verification-command-result.json']
  with self.assertRaises(ValueError):eligible(self.j,self.root)
 def test_success_without_reply_refused(self):
  self.records['verification-command-result.json']['exit_code']=0
  with self.assertRaises(ValueError):eligible(self.j,self.root)
 def test_existing_assignment_evidence_refused(self):
  (self.root/('f'*32)).mkdir()
  with self.assertRaises(ValueError):eligible(self.j,self.root)
 def test_dangling_symlink_refused(self):
  (self.root/('f'*32)).symlink_to(self.root/'absent')
  with self.assertRaises(ValueError):eligible(self.j,self.root)
 def test_changed_authorization_refused(self):
  self.request['deposit_vout']=1
  with self.assertRaises(ValueError):eligible(self.j,self.root)
if __name__=='__main__':unittest.main()
