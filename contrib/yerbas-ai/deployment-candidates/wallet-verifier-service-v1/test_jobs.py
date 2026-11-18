import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'package'))
from jobs import Jobs,Journal
R='a'*32
class Executor:
 def __init__(self):self.starts=[];self.gates=[];self.ended=None;self.cancelled=0;self.fail_prepare=False;self.fail_execute=False
 def prepare(self,run):
  self.starts.append(run)
  if self.fail_prepare:raise RuntimeError('prepare uncertain')
 def execute(self,run):
  self.gates.append(run)
  if self.fail_execute:raise RuntimeError('gate uncertain')
 def poll(self):return self.ended
 def cancel(self):self.cancelled+=1
class Tests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.path=Path(self.t.name)/'jobs';self.e=Executor();self.j=Journal(self.path);self.jobs=Jobs(self.j,self.e)
 def tearDown(self):self.j.db.close();self.t.cleanup()
 def call(self,action,run=R):return self.jobs.handle({'action':action,'run_id':run})
 def test_prepare_does_not_execute(self):
  self.assertEqual(self.call('prepare')['phase'],'ready');self.assertEqual(self.e.gates,[])
 def test_execute_requires_prepare(self):
  with self.assertRaises(ValueError):self.call('execute')
  self.assertEqual(self.e.gates,[])
 def test_no_duplicate_execution(self):
  self.call('prepare');self.call('execute')
  with self.assertRaises(ValueError):self.call('execute')
  self.assertEqual(self.e.gates,[R])
 def test_status_read_only(self):
  self.assertEqual(self.call('status')['phase'],'absent');self.assertEqual(self.e.starts,[])
 def test_busy_refuses_other_job(self):
  self.call('prepare')
  with self.assertRaises(ValueError):self.call('prepare','b'*32)
  self.assertEqual(self.e.starts,[R])
 def test_uncertain_preparation_not_repeated(self):
  self.e.fail_prepare=True
  with self.assertRaises(RuntimeError):self.call('prepare')
  with self.assertRaises(ValueError):self.call('prepare')
  self.assertEqual(self.e.starts,[R]);self.assertEqual(self.e.cancelled,1)
 def test_uncertain_gate_not_repeated(self):
  self.call('prepare');self.e.fail_execute=True
  with self.assertRaises(RuntimeError):self.call('execute')
  self.assertEqual(self.call('status')['phase'],'running')
  with self.assertRaises(ValueError):self.call('execute')
  self.assertEqual(self.e.gates,[R])
 def test_restart_does_not_launch(self):
  self.call('prepare');self.call('execute');self.jobs=Jobs(self.j,self.e)
  self.assertEqual(self.call('status')['phase'],'interrupted')
  with self.assertRaises(ValueError):self.call('prepare')
  self.assertEqual(self.e.starts,[R])
 def test_completion_retained(self):
  self.call('prepare');self.call('execute');self.e.ended={'exit_code':0}
  self.assertEqual(self.call('status')['phase'],'complete')
  with self.assertRaises(ValueError):self.call('prepare')
 def test_failure_retained(self):
  self.call('prepare');self.e.ended={'exit_code':1};self.assertEqual(self.call('status')['phase'],'failed')
 def test_cancel_does_not_clear_history(self):
  self.call('prepare');self.call('cancel');self.assertEqual(self.call('status')['phase'],'cancelled')
  with self.assertRaises(ValueError):self.call('prepare')
 def test_bad_requests_rejected(self):
  for v in ({'action':'shell','run_id':R},{'action':'prepare','run_id':'../x'},{'action':'prepare','run_id':R,'dataset':'/tmp/x'}):
   with self.assertRaises(ValueError):self.jobs.handle(v)
  self.assertEqual(self.e.starts,[])
if __name__=='__main__':unittest.main()

class PublicDirectoryTests(unittest.TestCase):
 def test_supervisor_directories_under_private_umask(self):
  import ast,os
  tree=ast.parse((Path(__file__).parent/'package/start_verifier.py').read_text())
  # Execute the actual directory-creation statements with the service's umask.
  statements=[]
  for node in ast.walk(tree):
   if isinstance(node,ast.Expr) and isinstance(node.value,ast.Call):
    f=node.value.func
    if isinstance(f,ast.Attribute) and isinstance(f.value,ast.Name) and f.value.id in ('base','dataset') and f.attr in ('mkdir','chmod'):statements.append(node)
  with tempfile.TemporaryDirectory() as tmp:
   base=Path(tmp)/'public';dataset=base/'dataset';old=os.umask(0o077)
   try:
    for node in sorted(statements,key=lambda n:(n.lineno,n.col_offset)):
     exec(compile(ast.Module(body=[node],type_ignores=[]),'<actual supervisor>','exec'),{'base':base,'dataset':dataset})
   finally:os.umask(old)
   self.assertEqual(base.stat().st_mode&0o777,0o755);self.assertEqual(dataset.stat().st_mode&0o777,0o755)
