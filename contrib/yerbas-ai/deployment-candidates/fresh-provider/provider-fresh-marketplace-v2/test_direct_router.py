import unittest
import os
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch
import direct_router
from direct_router import permitted


class RoutingTests(unittest.TestCase):
    def test_disabled_blocks_new_and_resumed_training(self):
        for retained in (False, True):
            with self.assertRaises(ValueError):
                permitted({'enabled': False}, retained, False)

    def test_disabled_preserves_receipt_only_replay(self):
        permitted({'enabled': False}, True, True)

    def test_replay_never_creates_work(self):
        for enabled in (False, True):
            with self.assertRaises(ValueError):
                permitted({'enabled': enabled}, False, True)

    def test_enrolled_training_route(self):
        for retained in (False, True):
            permitted({'enabled': True}, retained, False)

    def test_no_coercion_or_extra_selector_fields(self):
        for selector in ({}, None, {'enabled': 1}, {'enabled': 'false'},
                         {'enabled': True, 'policy': '/tmp/other'}):
            with self.assertRaises(ValueError):
                permitted(selector, False, False)


class EntryPointTests(unittest.TestCase):
    def invoke(self, enabled=True, replay=False, retained=False, schema=3):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = {'run_id': 'a' * 32, 'contribution': 'approved-job'}
            if retained:
                (root / (request['run_id'] + '-approved-job')).mkdir(mode=0o700)
            policy = dict(schema=schema, measurement='direct-cupti-v1',
                          provider_uid=os.getuid(), python=sys.executable, state=directory)
            reads = []
            def read(path, **kwargs):
                reads.append(str(path))
                return {direct_router.POLICY: policy,
                        direct_router.SELECTOR: {'enabled': enabled},
                        '/request.json': request}[str(path)]
            fake = types.SimpleNamespace(read_json=read, verify_policy=lambda p: p,
                validate_request=lambda r: r, require_root_ancestry=lambda p: None,
                require_service_boundary=lambda *a, **k: None)
            argv = ['router', '--request', '/request.json'] + (['--replay-only'] if replay else [])
            with patch.dict(sys.modules, provider_executor=fake), patch.object(sys, 'argv', argv), \
                    patch.object(direct_router.os, 'execv') as execute:
                direct_router.main()
                command = execute.call_args.args[1]
            self.assertEqual(set(reads), {direct_router.POLICY, direct_router.SELECTOR, '/request.json'})
            return command

    def test_direct_entry_needs_no_historical_policies(self):
        command = self.invoke()
        self.assertIn('--policy', command)
        self.assertNotIn('--replay-only', command)

    def test_replay_flag_forwarded_when_disabled(self):
        self.assertIn('--replay-only', self.invoke(enabled=False, replay=True, retained=True))

    def test_disabled_entry_refuses_training(self):
        with self.assertRaisesRegex(ValueError, 'Training disabled'):
            self.invoke(enabled=False)

    def test_legacy_policy_rejected(self):
        with self.assertRaisesRegex(ValueError, 'pinned direct collector'):
            self.invoke(schema=1)


if __name__ == '__main__':
    unittest.main()
