import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from workflow import Journal, ReconciliationRequired, STEPS


def authorization():
    return dict(schema=1, network='yerbas-private-reduced-collateral-testnet',
                quote='a' * 32, assignment='b' * 32, terms_sha256='c' * 64,
                deposit_txid='d' * 64, deposit_vout=0, maximum_base_units=101000,
                provider_reward_base_units=100000, slot='gpu-1', automatic_settlement=True)


class Adapter:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def preflight(self, request):
        if self.fail == 'preflight':
            raise ValueError('Insufficient native-backed credit')

    def perform(self, step, request, results):
        self.calls.append(step)
        if self.fail == step:
            raise TimeoutError('Reply lost after effect')
        return {'confirmed': True}


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.journal = Journal(self.root)

    def test_full_sequence_and_restart_do_not_repeat_effects(self):
        adapter = Adapter()
        first = self.journal.run(authorization(), adapter)
        second = Journal(self.root).run(authorization(), adapter)
        self.assertEqual(first, second)
        self.assertEqual(adapter.calls, list(STEPS))

    def test_lost_reply_at_every_stage_never_repeats_effect(self):
        for stage in STEPS:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as root:
                journal, adapter = Journal(root), Adapter(stage)
                with self.assertRaises(TimeoutError):
                    journal.run(authorization(), adapter)
                calls = list(adapter.calls)
                with self.assertRaises(ReconciliationRequired):
                    Journal(root).run(authorization(), adapter)
                self.assertEqual(adapter.calls, calls)

    def test_failed_readiness_creates_no_intent(self):
        adapter = Adapter('preflight')
        with self.assertRaises(ValueError):
            self.journal.run(authorization(), adapter)
        self.assertEqual(adapter.calls, [])
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['workflow.lock'])

    def test_changed_deposit_and_assignment_refused(self):
        self.journal.run(authorization(), Adapter())
        for field, value in [('deposit_txid', 'e' * 64), ('assignment', 'e' * 32)]:
            altered = authorization(); altered[field] = value
            with self.assertRaises(ValueError):
                self.journal.run(altered, Adapter())

    def test_mainnet_desktop_gpu_and_unapproved_payment_refused(self):
        for field, value in [('network', 'main'), ('slot', 'gpu-0'),
                             ('automatic_settlement', False), ('maximum_base_units', 101001),
                             ('deposit_vout', True), ('schema', True)]:
            request = authorization(); request[field] = value
            with self.assertRaises(ValueError):
                self.journal.run(request, Adapter())

    def test_symlink_journal_refused(self):
        (self.root / 'authorization.json').symlink_to(self.root / 'missing')
        with self.assertRaises(OSError):
            self.journal.run(authorization(), Adapter())

    def test_result_without_intent_refused(self):
        self.journal.retain('bind-result.json', {'value': {}})
        with self.assertRaises(ValueError):
            self.journal.run(authorization(), Adapter())

    def test_parallel_workflow_refused(self):
        import fcntl
        with (self.root / 'workflow.lock').open('w') as lock:
            os.chmod(lock.name, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.journal.run(authorization(), Adapter())


if __name__ == '__main__':
    unittest.main()
