import copy
import hashlib
import json
import unittest
from direct_segments import aggregate, digest


def encode(rows):
    return b''.join(json.dumps(dict(row, seq=i)).encode()+b'\n' for i,row in enumerate(rows))


def fixture(start=0):
    assignment = dict(attempt_id='a'*32, provider='u26-2T', physical_gpu='1',
        recipe_identity=dict(dataset='b'*64, config='c'*64, runner='d'*64), runtime_sha256='e'*64,
        start_step=start, end_step=start+400, initial_checkpoint_sha256='f'*64 if start else None)
    segments = []; parent = assignment['initial_checkpoint_sha256']
    for i in range(2):
        run = ('%032x' % (i+1)); checkpoint = '%064x' % (i+1)
        identity = dict(run_id=run, runtime_sha256=assignment['runtime_sha256'], recipe_sha256=digest(assignment['recipe_identity']))
        transcript = encode([dict(kind='start', schema=1, **identity),
            dict(kind='buffer_requested', buffer='b1'), dict(kind='flush_begin'),
            dict(kind='buffer_completed', buffer='b1', context='ctx', stream=0, parse_status='ok'),
            dict(kind='loss_check', buffer='b1', context='ctx', stream=0, status=0, dropped=0),
            dict(kind='flush_end', status=0), dict(kind='final_loss_check', context='ctx', stream=0, status=0, dropped=0),
            dict(kind='finish', buffers_requested=1, buffers_completed=1, loss_queries=2)])
        raw = encode([dict(kind='start', schema=1, **identity),
            dict(kind='kernel', buffer='b1', device=0, stream=0, correlation=1, start_ns=100, end_ns=200),
            dict(kind='finish', kernel_records=1)])
        binding = dict(assignment_sha256=digest(assignment), segment_index=i, run_id=run,
            start_step=start+i*200, end_step=start+(i+1)*200, parent_checkpoint_sha256=parent,
            checkpoint_sha256=checkpoint, transcript_sha256=hashlib.sha256(transcript).hexdigest(), interval_sha256=hashlib.sha256(raw).hexdigest())
        report = dict(identity=assignment['recipe_identity'], resumed_from_step=binding['start_step'],
            step=binding['end_step'], device='cuda', owner_stopped=False, checkpoint_sha256=checkpoint, kernel_records=1)
        segments.append(dict(binding=binding, report=report, transcript=transcript, intervals=raw))
        parent = checkpoint
    return assignment, segments


class SegmentTests(unittest.TestCase):
    def test_process_clocks_not_unioned_and_no_authority_granted(self):
        result = aggregate(*fixture())
        self.assertEqual(result['observed_kernel_union_ns'], 200)
        self.assertEqual(result['execution_segments'], 2)
        self.assertIs(result['reward_eligible'], False)
        self.assertIs(result['provider_execution_attested'], False)
        self.assertIsNone(result['approved_gpu_ms'])

    def test_resume_requires_correct_checkpoint_parent(self):
        assignment, segments = fixture(200)
        self.assertEqual(aggregate(assignment, segments)['start_step'], 200)
        segments[0]['binding']['parent_checkpoint_sha256'] = '0'*64
        with self.assertRaises(ValueError): aggregate(assignment, segments)

    def test_duplicate_out_of_order_and_partial_work_rejected(self):
        assignment, segments = fixture()
        for items in (segments[:1], segments[::-1], [segments[0], segments[0]], []):
            with self.assertRaises(ValueError): aggregate(assignment, items)

    def test_changed_assignment_binding_and_ranges_rejected(self):
        for key, value in (('assignment_sha256','0'*64), ('segment_index',False),
                           ('start_step',100), ('end_step',1400), ('parent_checkpoint_sha256','0'*64),
                           ('checkpoint_sha256','0'*64), ('run_id','1'*32)):
            assignment, segments = fixture(); segments[1]['binding'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): aggregate(assignment, segments)
        assignment, segments = fixture(); assignment['physical_gpu'] = '0'
        with self.assertRaises(ValueError): aggregate(assignment, segments)

    def test_tampering_replayed_and_dropped_artifacts_rejected(self):
        for artifact in ('transcript','intervals'):
            assignment, segments = fixture(); segments[1][artifact] = segments[0][artifact]
            key = 'transcript_sha256' if artifact == 'transcript' else 'interval_sha256'
            segments[1]['binding'][key] = hashlib.sha256(segments[1][artifact]).hexdigest()
            with self.subTest(artifact=artifact), self.assertRaises(ValueError): aggregate(assignment, segments)
        assignment, segments = fixture(); segments[0]['transcript'] = segments[0]['transcript'].replace(b'"dropped": 0', b'"dropped": 1')
        segments[0]['binding']['transcript_sha256'] = hashlib.sha256(segments[0]['transcript']).hexdigest()
        with self.assertRaises(ValueError): aggregate(assignment, segments)

    def test_stopped_cpu_and_reward_claims_rejected(self):
        for key, value in (('owner_stopped',True), ('device','cpu'), ('kernel_records',0), ('reward_eligible',True)):
            assignment, segments = fixture(); segments[0]['report'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): aggregate(assignment, segments)
