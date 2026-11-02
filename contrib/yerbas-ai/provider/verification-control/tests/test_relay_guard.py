import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
import relay_guard as g
class GuardTests(unittest.TestCase):
 def exercise(self,initial,body_error=False,stop_error=False,start_error=False):
  live=dict(zip(g.UNITS,initial));calls=[]
  def control(action,units):
   calls.append((action,tuple(units)))
   for u in units:live[u]='inactive' if action=='stop' else 'active'
   if action=='stop' and stop_error:raise RuntimeError('stop failed')
   if action=='start' and start_error:raise RuntimeError('start failed')
  try:
   with patch.object(g,'state',side_effect=lambda u:live[u]),patch.object(g,'control',side_effect=control):
    with g.paused():
     self.assertTrue(all(v=='inactive' for v in live.values()))
     if body_error:raise ValueError('GPU blocked')
  finally:
   if not start_error:self.assertEqual(live,dict(zip(g.UNITS,initial)))
  return calls
 def test_active_restored(self):self.assertEqual(self.exercise(['active','active'])[-1],('start',g.UNITS))
 def test_socket_only_restored(self):self.assertEqual(self.exercise(['active','inactive'])[-1],('start',(g.UNITS[0],)))
 def test_inactive_not_started(self):self.assertEqual(len(self.exercise(['inactive','inactive'])),1)
 def test_body_failure_restores(self):
  with self.assertRaisesRegex(ValueError,'GPU blocked'):self.exercise(['active','active'],body_error=True)
 def test_partial_stop_restores(self):
  with self.assertRaisesRegex(RuntimeError,'stop failed'):self.exercise(['active','active'],stop_error=True)
 def test_restore_failure_visible(self):
  with self.assertRaisesRegex(RuntimeError,'start failed'):self.exercise(['active','active'],start_error=True)
 def test_transition_refused(self):
  with patch.object(g,'state',return_value='activating'),patch.object(g,'control') as c:
   with self.assertRaises(RuntimeError):
    with g.paused():self.fail('body ran')
   c.assert_not_called()
if __name__=='__main__':unittest.main()
