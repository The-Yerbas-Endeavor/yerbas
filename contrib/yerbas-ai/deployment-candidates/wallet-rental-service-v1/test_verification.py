import json,tempfile,unittest,subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from verification import verify
class Context:
 def __init__(self,state):self.state=state
 def load(self,n):return json.loads((self.state/n).read_text())
 def save(self,n,v):
  with (self.state/n).open('x') as f:json.dump(v,f)
 def save_once(self,n,v):
  if (self.state/n).exists():
   if self.load(n)!=v:raise ValueError('Changed retained evidence')
  else:self.save(n,v)
class Tests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name);self.e=self.root/'evidence';self.e.mkdir();self.c=Context(self.root);self.c.save('results.json',{'results':[{'receipt':'a'*32}]});self.folder=None
 def command(self,receipt,folder):self.folder=folder;return ['fixed-operator']
 def complete(self,*args,**kwargs):
  self.folder.mkdir();(self.folder/'acceptance.json').write_text(json.dumps({'accepted':True,'receipt':'a'*32,'verifier':'anno2-u26','attestation_sha256':'b'*64}));return SimpleNamespace(returncode=0)
 def test_acceptance_recovered_without_repeat(self):
  run=Mock(side_effect=self.complete);first=verify(self.c,self.e,self.command,run);second=verify(self.c,self.e,self.command,run)
  self.assertEqual(first,second);self.assertEqual(run.call_count,1)
 def test_lost_reply_never_restarts(self):
  run=Mock(side_effect=subprocess.TimeoutExpired('fixed',300))
  with self.assertRaises(subprocess.TimeoutExpired):verify(self.c,self.e,self.command,run)
  with self.assertRaises(ValueError):verify(self.c,self.e,self.command,run)
  self.assertEqual(run.call_count,1)
 def test_nonzero_return_never_restarts(self):
  run=Mock(return_value=SimpleNamespace(returncode=1))
  for _ in range(2):
   with self.assertRaises(ValueError):verify(self.c,self.e,self.command,run)
  self.assertEqual(run.call_count,1)
 def test_missing_acceptance_never_restarts(self):
  run=Mock(return_value=SimpleNamespace(returncode=0))
  for _ in range(2):
   with self.assertRaises(ValueError):verify(self.c,self.e,self.command,run)
  self.assertEqual(run.call_count,1)
 def test_changed_receipt_refused(self):
  run=Mock(side_effect=self.complete);verify(self.c,self.e,self.command,run)
  (self.root/'results.json').write_text(json.dumps({'results':[{'receipt':'c'*32}]}))
  with self.assertRaises(ValueError):verify(self.c,self.e,self.command,run)
  self.assertEqual(run.call_count,1)
 def test_existing_accepted_receipt_needs_no_execution(self):
  self.folder=self.e/('d'*32);self.complete();run=Mock();r=verify(self.c,self.e,self.command,run);self.assertEqual(r['receipt'],'a'*32);run.assert_not_called()
if __name__=='__main__':unittest.main()
