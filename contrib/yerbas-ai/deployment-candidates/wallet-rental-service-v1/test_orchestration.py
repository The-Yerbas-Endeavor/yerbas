import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import orchestration as flow


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.context=Mock(state=self.root, quote='a'*32)
        self.adapter=flow.Adapter(self.context)
        self.request=dict(quote='a'*32, assignment='b'*32,terms_sha256='c'*64,
                          deposit_txid='d'*64,deposit_vout=0,maximum_base_units=101000,
                          provider_reward_base_units=100000)

    def test_changed_review_refused(self):
        terms=dict(quote_id='e'*32,assignment_id='b'*32)
        with patch.object(flow,'wallet',return_value={'terms':terms,'assignment_sha256':'c'*64}):
            with self.assertRaises(ValueError):self.adapter.review(self.request)

    def test_run_wrong_assignment_acknowledgment_refused(self):
        response=dict(assignment='e'*32,protected_receipt=dict(run_id='b'*32,submission_acknowledged=True))
        with patch.object(flow.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(response))):
            with self.assertRaises(ValueError):self.adapter.helper_request('run',self.request)

    def test_run_failed_reply_refused(self):
        with patch.object(flow.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout='{}')):
            with self.assertRaises(ValueError):self.adapter.helper_request('run',self.request)

    def test_exact_run_acknowledgment(self):
        response=dict(assignment='b'*32,protected_receipt=dict(run_id='b'*32,submission_acknowledged=True))
        with patch.object(flow.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(response))):
            self.assertEqual(self.adapter.helper_request('run',self.request),response)

    def test_incomplete_work_never_collects_or_pays(self):
        with patch.object(flow,'wallet',return_value={'state':'failed'}) as rpc:
            with self.assertRaises(ValueError):self.adapter.perform('collect',self.request,{})
            self.assertEqual(rpc.call_count,1)
        self.context.remote.assert_not_called()

    def test_collection_requires_restart_fence(self):
        with patch.object(flow,'wallet',side_effect=[{'state':'completed'},{}, {'state':'completed','restart_blocked':False}]):
            with self.assertRaises(ValueError):self.adapter.perform('collect',self.request,{})
        self.context.remote.assert_not_called()

    def test_wrong_receipt_assignment_refused(self):
        self.context.remote.return_value={'results':[dict(assignment='e'*32,terms_sha256='c'*64,receipt='f'*32)]}
        with patch.object(flow,'wallet',side_effect=[{'state':'completed'},{}, {'state':'completed','restart_blocked':True}]):
            with self.assertRaises(ValueError):self.adapter.perform('collect',self.request,{})
        self.context.save_once.assert_not_called()


if __name__=='__main__':unittest.main()
