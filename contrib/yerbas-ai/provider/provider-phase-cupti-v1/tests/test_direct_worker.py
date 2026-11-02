import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from direct_attempt import run
from direct_evidence import bind
from direct_segments import digest
from test_direct_segments import fixture

class Process:
    returncode=0
    def poll(self): return self.returncode

class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.state=self.root/'state';self.state.mkdir()
        self.attempt=self.root/'attempt';self.attempt.mkdir();self.calls=0;self.mode='ok';self.stop=threading.Event()
        a,_=fixture()
        self.start=dict(schema=1,attempt_id=a['attempt_id'],physical_gpu=a['physical_gpu'],start_step=0,initial_checkpoint_sha256=None,
            manifest=dict(provider=a['provider'],contribution='test-contribution',identity=a['recipe_identity'],start_step=0,end_step=6000))
    def launch(self,argv,**kw):
        self.calls+=1;state,segment=Path(argv[-3]),Path(argv[-2]);s=json.loads((segment/'start.json').read_text())
        raw=('checkpoint-%d'%s['end_step']).encode();(state/'checkpoint.json').write_bytes(raw)
        r=dict(identity=s['recipe_identity'],resumed_from_step=s['start_step'],step=s['end_step'],device='cpu' if self.mode=='cpu' else 'cuda',
            owner_stopped=False,checkpoint_sha256=hashlib.sha256(raw).hexdigest(),kernel_records=1)
        (segment/'report.json').write_text(json.dumps(r))
        full={k:v for k,v in r.items() if k!='kernel_records'};full.update(initial_bits_per_byte=8,elapsed_training_seconds=.1)
        (segment/'full-report.json').write_text(json.dumps(full))
        _,items=fixture()
        for field,name in [('transcript','collector.jsonl'),('intervals','collector.jsonl.kernels')]:
            rows=[json.loads(line) for line in items[0][field].splitlines()]
            rows[0].update(run_id=s['run_id'],runtime_sha256=s['runtime_sha256'],recipe_sha256=digest(s['recipe_identity']))
            if self.mode=='dropped' and field=='transcript':rows[4]['dropped']=1
            (segment/name).write_text(''.join(json.dumps(x)+'\n' for x in rows))
        from direct_attempt import __file__ as attempt_source
        doc=dict(identity=dict(run_id=s['run_id'],runtime_sha256=s['runtime_sha256'],recipe_sha256=digest(s['recipe_identity'])),interval_sha256=hashlib.sha256((segment/'collector.jsonl.kernels').read_bytes()).hexdigest(),instrumentation_sha256=hashlib.sha256(Path(attempt_source).with_name('phase_scope.py').read_bytes()).hexdigest(),phases=[dict(phase='loop',cupti_start_ns=1,cupti_end_ns=500),dict(phase='checkpoint',cupti_start_ns=300,cupti_end_ns=400)])
        (segment/'phases.json').write_text(json.dumps(doc))
        p=Process()
        if self.mode=='failed':p.returncode=1
        if self.mode=='stop':self.stop.set()
        return p
    def execute(self,clock=lambda:0):
        (self.attempt/'start.json').write_text(json.dumps(self.start))
        return run(self.root,self.state,self.attempt,6000-self.start['start_step'],120,stop=self.stop,clock=clock,
                   launch=self.launch,runtime=lambda:Path('/fake'))
    def receipt(self,report):return dict(receipt='9'*32,sha256=report['checkpoint_sha256'],contribution='test-contribution')
    def test_full_attempt_binds_to_receipt_without_approval(self):
        report=self.execute();measurement=json.loads((self.attempt/'measurement.json').read_text())
        result=bind(self.start,measurement,report,self.receipt(report))
        self.assertEqual(self.calls,6);self.assertEqual(result['observed_kernel_union_ns'],600)
        self.assertEqual(result['schema'],2);self.assertFalse(result['reward_eligible']);self.assertIsNone(result['approved_gpu_ms'])
    def test_resumed_attempt_starts_at_retained_step(self):
        raw=b'checkpoint-2000';(self.state/'checkpoint.json').write_bytes(raw)
        self.start.update(start_step=2000,initial_checkpoint_sha256=hashlib.sha256(raw).hexdigest())
        report=self.execute();self.assertEqual(self.calls,4);self.assertEqual(report['resumed_from_step'],2000)
    def test_bad_parent_launches_nothing(self):
        (self.state/'checkpoint.json').write_bytes(b'unexpected')
        with self.assertRaises(ValueError):self.execute()
        self.assertEqual(self.calls,0)
    def test_failed_stopped_invalid_or_lossy_child_never_publishes_measurement(self):
        for mode in ('failed','stop','cpu','dropped'):
            with self.subTest(mode=mode):
                self.mode=mode;self.calls=0;self.stop.clear()
                import shutil
                shutil.rmtree(self.attempt);self.attempt.mkdir()
                (self.state/'checkpoint.json').unlink(missing_ok=True)
                with self.assertRaises((ValueError,RuntimeError)):self.execute()
                self.assertEqual(self.calls,1);self.assertFalse((self.attempt/'measurement.json').exists())
    def test_deadline_is_not_extended(self):
        times=iter((0,121))
        with self.assertRaises(RuntimeError):self.execute(clock=lambda:next(times))
        self.assertEqual(self.calls,0)
    def test_receipt_recipe_attempt_and_approval_tampering_rejected(self):
        report=self.execute();measurement=json.loads((self.attempt/'measurement.json').read_text());receipt=self.receipt(report)
        changes=[('receipt',{'sha256':'0'*64}),('receipt',{'contribution':'other'}),('measurement',{'attempt_sha256':'0'*64}),
                 ('measurement',{'approved_gpu_ms':1}),('measurement',{'reward_eligible':True}),('measurement',{'schema':1}),
                 ('report',{'device':'cpu'}),('report',{'owner_stopped':True})]
        for target,delta in changes:
            values=dict(receipt=copy.deepcopy(receipt),measurement=copy.deepcopy(measurement),report=copy.deepcopy(report));values[target].update(delta)
            with self.subTest(target=target,delta=delta),self.assertRaises(ValueError):bind(self.start,values['measurement'],values['report'],values['receipt'])
        measurement['direct']['segments'][1]['binding']['parent_checkpoint_sha256']='0'*64
        with self.assertRaises(ValueError):bind(self.start,measurement,report,receipt)
