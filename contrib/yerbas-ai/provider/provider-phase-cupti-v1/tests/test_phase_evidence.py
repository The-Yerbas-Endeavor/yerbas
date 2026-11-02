import json
from phase_evidence import bind_directory
from test_direct_worker import WorkerTests


class PhaseEvidenceTests(WorkerTests):
    def test_invalid_phase_prevents_completed_measurement(self):
        from pathlib import Path
        original=self.launch
        def corrupted(argv,**kw):
            process=original(argv,**kw)
            path=Path(argv[-2])/'phases.json'
            document=json.loads(path.read_text());document['interval_sha256']='0'*64
            path.write_text(json.dumps(document));return process
        self.launch=corrupted
        with self.assertRaises(ValueError):self.execute()
        self.assertFalse((self.attempt/'measurement.json').exists())
        self.assertEqual(self.calls,1)

    def test_receipt_bound_phase_totals(self):
        report=self.execute();measurement=json.loads((self.attempt/'measurement.json').read_text())
        result=bind_directory(self.attempt,self.start,measurement,report,self.receipt(report))
        self.assertEqual(result['observed_kernel_union_ns'],{'training':600,'checkpoint':0})
        self.assertEqual(len(result['segments']),6)
        self.assertFalse(result['reward_eligible'])
        self.assertIsNone(result['approved_gpu_ms'])

    def test_missing_or_changed_phase_cannot_bind(self):
        report=self.execute();measurement=json.loads((self.attempt/'measurement.json').read_text())
        path=self.attempt/'direct-segment-00/phases.json';original=path.read_text()
        for key,value in [('interval_sha256','0'*64),('instrumentation_sha256','0'*64),('phases',[])]:
            document=json.loads(original);document[key]=value;path.write_text(json.dumps(document))
            with self.assertRaises(ValueError):bind_directory(self.attempt,self.start,measurement,report,self.receipt(report))
        path.unlink()
        with self.assertRaises(FileNotFoundError):bind_directory(self.attempt,self.start,measurement,report,self.receipt(report))

    def test_resumed_phase_range_not_invented(self):
        import hashlib
        raw=b'checkpoint-2000';(self.state/'checkpoint.json').write_bytes(raw)
        self.start.update(start_step=2000,initial_checkpoint_sha256=hashlib.sha256(raw).hexdigest())
        report=self.execute();measurement=json.loads((self.attempt/'measurement.json').read_text())
        result=bind_directory(self.attempt,self.start,measurement,report,self.receipt(report))
        self.assertEqual(result['start_step'],2000)
        self.assertEqual(len(result['segments']),4)
