import unittest
from unittest.mock import patch
from types import SimpleNamespace
from chain_reader import node,TransactionNotYetKnown
class Tests(unittest.TestCase):
 def test_missing_transaction_is_observation_only(self):
  with patch('chain_reader.subprocess.run',return_value=SimpleNamespace(returncode=1,stderr='error code: -5\nerror message:\nNo information available about transaction')):
   with self.assertRaises(TransactionNotYetKnown):node('anno2-u26')('getrawtransaction','a'*64,True)
 def test_other_errors_not_hidden(self):
  with patch('chain_reader.subprocess.run',return_value=SimpleNamespace(returncode=1,stderr='error: connection failed')):
   with self.assertRaises(RuntimeError) as e:node('anno2-u26')('getrawtransaction','a'*64,True)
   self.assertNotIsInstance(e.exception,TransactionNotYetKnown)
 def test_writes_refused(self):
  with self.assertRaises(ValueError):node('u26-2T')('sendrawtransaction','00')
if __name__=='__main__':unittest.main()
