import json,sys,unittest
from types import SimpleNamespace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import remote_commands as adapter
R='a'*32
class Fake(adapter.Anno2):
 def __init__(self):self.ready=True;self.run=R;self.plan={'x':1};self.calls=[];self.service_pending=True;self.phase='complete';self.error=False
 def service(self,action):
  self.calls.append(action)
  if self.error and action=='execute':raise TimeoutError('lost reply')
  return {'run_id':R,'phase':'running' if action=='execute' else self.phase,'result':{'exit_code':0}}
 def remote(self,args,**kwargs):return SimpleNamespace(stdout='{}' if kwargs.get('text') else b'artifact')
class Tests(unittest.TestCase):
 def test_execute_then_observe(self):
  f=Fake();self.assertEqual(f.execute(f.plan),({},b'artifact'));self.assertEqual(f.calls,['execute','status']);self.assertFalse(f.service_pending)
 def test_uncertain_execute_never_retried(self):
  f=Fake();f.error=True
  with self.assertRaises(TimeoutError):f.execute(f.plan)
  with self.assertRaises(ValueError):f.execute(f.plan)
  self.assertEqual(f.calls,['execute']);f.close();self.assertEqual(f.calls,['execute','cancel'])
 def test_failed_run_not_signed_or_repeated(self):
  f=Fake();f.phase='failed'
  with self.assertRaises(RuntimeError):f.execute(f.plan)
  self.assertEqual(f.calls,['execute','status']);self.assertFalse(f.service_pending)
 def test_changed_plan_refused(self):
  f=Fake()
  with self.assertRaises(ValueError):f.execute({'x':2})
  self.assertEqual(f.calls,[])
 def test_complete_close_does_not_cancel(self):
  f=Fake();f.execute(f.plan);f.close();self.assertEqual(f.calls,['execute','status'])
if __name__=='__main__':unittest.main()
