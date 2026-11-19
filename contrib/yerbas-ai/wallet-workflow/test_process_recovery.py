"""Real process and loopback failures; synthetic effects, never coins or GPUs."""
import http.server,json,os,socket,sqlite3,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from workflow import STEPS
from test_workflow import authorization
HERE=Path(__file__).resolve().parent
WORKER='''import json,sys,urllib.request
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from workflow import Journal
class Adapter:
 def preflight(self,r):pass
 def perform(self,step,r,results):
  request=urllib.request.Request(sys.argv[3],json.dumps({'step':step}).encode())
  with urllib.request.urlopen(request,timeout=2) as response:return json.load(response)
p=Path(sys.argv[2]);Journal(p).run(json.loads((p/'request.json').read_text()),Adapter())
'''
class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name);self.state=self.root/'state';self.state.mkdir(mode=0o700)
  (self.state/'request.json').write_text(json.dumps(authorization()));(self.state/'request.json').chmod(0o600)
  self.db=self.root/'effects.sqlite3'
  with sqlite3.connect(self.db) as db:db.execute('CREATE TABLE effects(step TEXT)')
  self.fault=None;self.committed=threading.Event();self.release=threading.Event();outer=self
  class Handler(http.server.BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    step=json.loads(self.rfile.read(int(self.headers['Content-Length'])))['step']
    fault=outer.fault
    if fault==(step,'before'):
     self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
    with sqlite3.connect(outer.db) as db:db.execute('INSERT INTO effects VALUES(?)',(step,))
    if fault and fault[0]==step:
     outer.committed.set()
     if fault[1]=='hold':outer.release.wait(5)
     self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
    raw=json.dumps({'confirmed':step}).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
  self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
  self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.close)
 def close(self):self.release.set();self.server.shutdown();self.server.server_close();self.thread.join()
 def launch(self):
  return subprocess.Popen([sys.executable,'-I','-B','-c',WORKER,str(HERE),str(self.state),'http://127.0.0.1:'+str(self.server.server_port)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
 def run_worker(self):
  p=self.launch();self.addCleanup(lambda:p.kill() if p.poll() is None else None);return p.communicate(timeout=15),p.returncode
 def effects(self):
  with sqlite3.connect(self.db) as db:return [r[0] for r in db.execute('SELECT step FROM effects ORDER BY rowid')]
 def test_completed_restart_never_repeats_remote_effects(self):
  self.assertEqual(self.run_worker()[1],0);self.assertEqual(self.run_worker()[1],0);self.assertEqual(self.effects(),list(STEPS))
 def test_connection_lost_before_payment_is_not_blindly_retried(self):
  self.fault=('pay','before');self.assertNotEqual(self.run_worker()[1],0);before=self.effects();self.fault=None
  self.assertNotEqual(self.run_worker()[1],0);self.assertEqual(self.effects(),before);self.assertNotIn('pay',before)
 def test_reply_lost_after_payment_does_not_pay_twice(self):
  self.fault=('pay','after');self.assertNotEqual(self.run_worker()[1],0);before=self.effects();self.fault=None
  self.assertNotEqual(self.run_worker()[1],0);self.assertEqual(self.effects(),before);self.assertEqual(before.count('pay'),1)
 def test_worker_killed_after_remote_execution_does_not_restart_gpu(self):
  self.fault=('execute','hold');p=self.launch();self.addCleanup(lambda:p.kill() if p.poll() is None else None)
  self.assertTrue(self.committed.wait(10));p.kill();p.communicate(timeout=5);self.release.set();before=self.effects();self.fault=None
  self.assertNotEqual(self.run_worker()[1],0);self.assertEqual(self.effects(),before);self.assertEqual(before.count('execute'),1)
if __name__=='__main__':unittest.main()
