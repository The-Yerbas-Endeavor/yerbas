import sys,unittest,signal
from pathlib import Path
from unittest.mock import Mock,patch,call
sys.path.insert(0,str(Path(__file__).parent/'package'))
from start_verifier import signal_worker
class Tests(unittest.TestCase):
 def test_signals_only_as_worker_and_restores(self):
  child=Mock()
  with patch('start_verifier.os.geteuid',return_value=0),patch('start_verifier.os.seteuid') as switch:
   signal_worker(child,signal.SIGTERM,997)
   self.assertEqual(switch.call_args_list,[call(997),call(0)])
  child.send_signal.assert_called_once_with(signal.SIGTERM)
 def test_error_restores_identity(self):
  child=Mock();child.send_signal.side_effect=ProcessLookupError()
  with patch('start_verifier.os.geteuid',return_value=0),patch('start_verifier.os.seteuid') as switch:
   with self.assertRaises(ProcessLookupError):signal_worker(child,signal.SIGKILL,997)
   self.assertEqual(switch.call_args_list,[call(997),call(0)])
 def test_root_worker_refused(self):
  with patch('start_verifier.os.geteuid',return_value=0),patch('start_verifier.os.seteuid') as switch:
   with self.assertRaises(ValueError):signal_worker(Mock(),signal.SIGTERM,0)
   switch.assert_not_called()
