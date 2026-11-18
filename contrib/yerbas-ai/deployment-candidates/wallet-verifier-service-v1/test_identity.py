import sys,unittest,subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).parent/'package'))
from server import check_worker_identity
class Tests(unittest.TestCase):
 def test_actual_launch_parameters(self):
  runner=Mock(return_value=SimpleNamespace(stdout='997\n'))
  check_worker_identity(runner,SimpleNamespace(pw_uid=997,pw_gid=973))
  self.assertEqual(runner.call_args.args,(['/usr/bin/id','-u'],))
  for key,value in dict(user=997,group=973,extra_groups=[],start_new_session=True,timeout=10,check=True).items():self.assertEqual(runner.call_args.kwargs[key],value)
 def test_missing_capability_refuses_startup(self):
  runner=Mock(side_effect=PermissionError(1,'Operation not permitted'))
  with self.assertRaises(PermissionError):check_worker_identity(runner,SimpleNamespace(pw_uid=997,pw_gid=973))
 def test_wrong_account_refuses_startup(self):
  with self.assertRaises(ValueError):check_worker_identity(Mock(return_value=SimpleNamespace(stdout='0\n')),SimpleNamespace(pw_uid=997,pw_gid=973))
if __name__=='__main__':unittest.main()
