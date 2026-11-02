import socket,tempfile,time,unittest
from pathlib import Path
from wallet_agent import Agent
class Bridge:
 def __init__(self):self.bad=False
 def reward(self,action,receipt):
  return dict(schema=2,receipt=receipt,provider=socket.gethostname(),request_id='b'*64,requested_at=int(time.time()),payment_authorized=self.bad,gpu_time_approved=False,status='approved',lifecycle=dict(status='approved',amount_base_units=1000000,basis='fixed_private_testnet_allowance',verification_sha256='c'*64))
class Tests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name)
 def test_disabled_bridge_fails_closed(self):
  a=Agent(self.root,self.root/'agent');self.addCleanup(a.close)
  r=a.dispatch(dict(v=1,id='d'*32,method='rewards.request',params={'receipt':'a'*32}))
  self.assertFalse(r['ok']);self.assertEqual(r['error']['code'],'reward_requests_unavailable')
 def test_lifecycle_bound_and_forgery_rejected(self):
  bridge=Bridge();a=Agent(self.root,self.root/'agent',reward_client=bridge);self.addCleanup(a.close)
  r=dict(v=1,id='d'*32,method='rewards.status',params={'receipt':'a'*32})
  self.assertEqual(a.dispatch(r)['result']['request']['status'],'approved')
  bridge.bad=True;self.assertFalse(a.dispatch(r)['ok'])
if __name__=='__main__':unittest.main()
