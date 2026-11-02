import socket,unittest
from reward_daemon import dispatch
from reward_socket import frame
class Fake:
 config={'owner_uid':1000}
 def __init__(self):self.calls=[]
 def reward(self,*args):self.calls.append(args);return {'status':'pending_review'}
class Tests(unittest.TestCase):
 def setUp(self):self.c=Fake();self.r=dict(v=1,id='a'*32,method='rewards.request',params={'receipt':'b'*32})
 def test_owner_request(self):
  self.assertTrue(dispatch(self.c,1000,self.r)['ok']);self.assertEqual(self.c.calls,[('request','b'*32)])
 def test_unauthorized(self):
  self.assertFalse(dispatch(self.c,1001,self.r)['ok']);self.assertEqual(self.c.calls,[])
 def test_unsupported_and_extra_fields(self):
  for method in ('send','provider.submit','rewards.send'):
   self.assertFalse(dispatch(self.c,1000,dict(self.r,method=method))['ok'])
  for key in ('url','amount','provider','token'):
   self.assertFalse(dispatch(self.c,1000,dict(self.r,params=dict(self.r['params'],**{key:'bad'})))['ok'])
  self.assertEqual(self.c.calls,[])
 def test_coordinator_failure_not_success(self):
  def fail(*_):raise ConnectionError('private details')
  self.c.reward=fail;r=dispatch(self.c,1000,self.r);self.assertFalse(r['ok']);self.assertNotIn('private details',str(r))
 def test_capabilities_no_network(self):
  r=dispatch(self.c,1000,dict(self.r,method='rewards.capabilities',params={}));self.assertEqual(r['result'],{'requests_enabled':True,'payments_enabled':False});self.assertEqual(self.c.calls,[])
 def test_framing(self):
  for payload in (b'{"v":1,"v":2}\n',b'{}\n{}\n',b'x'*8193):
   a,b=socket.socketpair()
   try:
    a.sendall(payload)
    with self.assertRaises(ValueError):frame(b)
   finally:a.close();b.close()
 def test_valid_frame(self):
  a,b=socket.socketpair()
  try:a.sendall(b'{"v":1}\n');self.assertEqual(frame(b),{'v':1})
  finally:a.close();b.close()
if __name__=='__main__':unittest.main()
