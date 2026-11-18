import json,sys,tempfile,unittest,subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
import payout
class Trial:
 def __init__(self,path,values):self.path=path;self.values=values
 def network(self):return {'chain':'test'}
 def load(self,n):return self.values[n]
 def save(self,n,v):
  with (self.path/n).open('x') as f:json.dump(v,f)
class Pilot:
 def __init__(self,order,native):
  self.ids={'provider':'p','verifier':'v'}
  self.work={'state':'verified','execution_binding':{'assignment_id':'a'*32},'artifact':'d'*64,'verifier':'v','payout_funding':{'quote_id':native['quote_id'],'quote_sha256':native['quote_sha256'],'coordinator_ca_sha256':native['coordinator_ca_sha256'],'fee':1000,'outpoint':'e'*64+':0'}}
  self.value={'orders':{order:self.work},'payout_plans':{order:{'hash':'f'*64}}}
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def state(self):return self.value
 def send(self,*args):raise AssertionError('Unexpected mutation')
class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.state=Path(self.temp.name);(self.state/'lock').touch();(self.state/'plan.json').write_text('{}')
  quote='b'*32;n={'quote_id':quote,'quote_sha256':'c'*64,'coordinator_ca_sha256':'1'*64,'deposit_txid':'e'*64,'deposit_vout':0,'deposit_base_units':101000,'receiving_script':'76a914'+'2'*40+'88ac','fee_base_units':1000,'receipts':[{'assignment_id':'a'*32,'receipt':'3'*32,'artifact_sha256':'d'*64}]}
  (self.state/'acceptance.json').write_text(json.dumps({'accepted':True,'receipt':'3'*32,'attestation_sha256':'4'*64}))
  self.values={'results.json':{'results':[{'assignment':'a'*32,'receipt':'3'*32}]},'payment.json':{'plan':n,'plan_sha256':payout.digest(n)},'verification-reference.json':{'path':str(self.state),'attestation_sha256':'4'*64},'consensus-preview.json':{'result':{'ready_for_review':True}}}
  self.context=SimpleNamespace(state=self.state,quote=quote,trial=Trial(self.state,self.values));self.p=Pilot(payout.digest({'quote':quote,'assignment':'a'*32}),n)
  for name,value in [('open_session',lambda *args:self.p),('treasury_proof',lambda p:{'verified-test-proof':True})]:
   q=patch.object(payout,name,value);q.start();self.addCleanup(q.stop)
 def test_preview_never_creates_send_intent(self):
  with patch.object(payout.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='{"result":{"ready_for_review":true}}')) as signer:
   payout.settle(self.context)
   request=json.loads(signer.call_args.kwargs['input']);self.assertEqual(request['request']['action'],'preview')
  self.assertFalse((self.state/'consensus-settle-intent.json').exists())
 def test_uncertain_send_cannot_be_repeated(self):
  with patch.object(payout.subprocess,'run',side_effect=subprocess.TimeoutExpired('signer',180)) as signer:
   with self.assertRaises(subprocess.TimeoutExpired):payout.settle(self.context,apply=True)
   self.assertTrue((self.state/'consensus-settle-intent.json').exists())
   with self.assertRaises(ValueError):payout.settle(self.context,apply=True)
   self.assertEqual(signer.call_count,1)
 def test_wrong_quote_no_signer(self):
  self.context.quote='9'*32
  with patch.object(payout.subprocess,'run') as signer:
   with self.assertRaises(ValueError):payout.settle(self.context,apply=True)
   signer.assert_not_called()
 def test_wrong_receipt_no_signer(self):
  self.values['results.json']['results'][0]['receipt']='9'*32
  with patch.object(payout.subprocess,'run') as signer:
   with self.assertRaises(ValueError):payout.settle(self.context,apply=True)
   signer.assert_not_called()
 def test_declined_preview_no_send(self):
  self.values['consensus-preview.json']['result']['ready_for_review']=False
  with patch.object(payout.subprocess,'run') as signer:
   with self.assertRaises(ValueError):payout.settle(self.context,apply=True)
   signer.assert_not_called()
if __name__=='__main__':unittest.main()
