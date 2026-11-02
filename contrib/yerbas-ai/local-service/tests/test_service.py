import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from yerbas_ai.service import APIError, State, create_server
from yerbas_ai.cli import Client


class FakeRuntime:
    def __init__(self):
        self.release = threading.Event()
        self.fail = False
        self.received = None

    def models(self):
        return [{'name': 'test:local', 'size': 123}]

    def generate(self, job, messages, limit):
        self.received = messages
        while not self.release.wait(.01):
            if job['cancel'].is_set():
                return None
        if self.fail:
            raise OSError('private backend error')
        return {'text': 'Test response', 'input_tokens': 3, 'output_tokens': 2}


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.runtime = FakeRuntime()
        self.state = State(self.runtime)
        self.server = create_server(0, 'test-secret', self.state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name)
        (path/'session.json').write_text(json.dumps({'port': self.server.server_port, 'token': 'test-secret'}))
        self.client = Client(path)

    def tearDown(self):
        if self.state.active:
            self.state.cancel(self.state.active)
        self.runtime.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def submit(self, **updates):
        data = {'mode': 'local', 'model': 'test:local',
                'messages': [{'role': 'user', 'content': 'hello'}]}
        data.update(updates)
        return self.client.request('/v1/jobs', data)

    def finished(self, job_id):
        until = time.monotonic()+2
        while time.monotonic() < until:
            job = self.client.request('/v1/jobs/'+job_id)
            if job['state'] not in ('running', 'cancelling'):
                return job
            time.sleep(.01)
        self.fail('Job failed to terminate')

    def test_status_has_no_chain_dependency(self):
        value = self.client.request('/v1/status')
        self.assertFalse(value['blockchain_required'])
        self.assertFalse(value['network_enabled'])
        self.assertFalse(value['provider_enabled'])

    def test_auth_and_browser_origin(self):
        for headers, expected in [({}, 401),
                                  ({'Authorization': 'Bearer wrong'}, 401),
                                  ({'Authorization': 'Bearer test-secret', 'Origin': 'https://example.com'}, 403)]:
            conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
            conn.request('GET', '/v1/status', headers=headers)
            response = conn.getresponse()
            self.assertEqual(response.status, expected)
            response.read()
            conn.close()

    def test_completion_and_no_prompt_in_record(self):
        job = self.submit()
        self.runtime.release.set()
        result = self.finished(job['id'])
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['result']['text'], 'Test response')
        self.assertNotIn('messages', result)
        self.assertNotIn('cancel', result)
        self.assertIsNone(self.client.request('/v1/status')['active_job'])

    def test_concurrent_submissions_only_one_accepted(self):
        accepted, rejected = [], []
        barrier = threading.Barrier(6)
        def submit():
            barrier.wait()
            try:
                accepted.append(self.submit())
            except RuntimeError as exc:
                rejected.append(str(exc))
        workers = [threading.Thread(target=submit) for _ in range(6)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 5)

    def test_cancel_is_idempotent_and_allows_next_request(self):
        job = self.submit()
        self.client.request('/v1/jobs/'+job['id']+'/cancel', {})
        self.client.request('/v1/jobs/'+job['id']+'/cancel', {})
        result = self.finished(job['id'])
        self.assertEqual(result['state'], 'cancelled')
        self.assertNotIn('result', result)
        self.runtime.release.set()
        next_job = self.submit()
        self.assertEqual(self.finished(next_job['id'])['state'], 'completed')

    def test_runtime_failure_releases_slot_without_exposing_detail(self):
        self.runtime.fail = True
        job = self.submit()
        self.runtime.release.set()
        result = self.finished(job['id'])
        self.assertEqual(result['state'], 'failed')
        self.assertNotIn('private backend', result['error'])
        self.assertIsNone(self.state.active)

    def test_unknown_model_and_network_fail_closed(self):
        for updates in ({'model': 'not-installed'}, {'mode': 'network'}, {'mode': None}):
            with self.assertRaises(RuntimeError):
                self.submit(**updates)
        self.assertIsNone(self.state.active)

    def test_input_and_output_bounds(self):
        for updates in ({'max_output_tokens': 0}, {'max_output_tokens': True},
                        {'max_output_tokens': 1025},
                        {'messages': [{'role': 'user', 'content': 'x'*4097}]},
                        {'messages': [{'role': 'tool', 'content': 'execute'}]}):
            with self.assertRaises(RuntimeError):
                self.submit(**updates)

    def test_completed_job_cannot_be_cancelled(self):
        self.runtime.release.set()
        job = self.submit()
        self.finished(job['id'])
        result = self.client.request('/v1/jobs/'+job['id']+'/cancel', {})
        self.assertEqual(result['state'], 'completed')

    def test_job_history_is_bounded(self):
        self.runtime.release.set()
        for _ in range(35):
            self.finished(self.submit()['id'])
        self.assertEqual(len(self.state.jobs), 32)

    def test_saved_default_model_and_schedule_do_not_block_local_prompt(self):
        saved = self.client.request('/v1/preferences', {
            'revision': 0, 'changes': {'default_model': 'test:local'}})
        self.assertEqual(saved['revision'], 1)
        self.assertFalse(self.client.request('/v1/availability')['policy_allows_contribution'])
        self.runtime.release.set()
        result = self.finished(self.submit(model=None)['id'])
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['model'], 'test:local')

    def test_unknown_default_model_rejected_without_changing_settings(self):
        with self.assertRaises(RuntimeError):
            self.client.request('/v1/preferences', {
                'revision': 0, 'changes': {'default_model': 'missing:local'}})
        self.assertEqual(self.client.request('/v1/preferences')['revision'], 0)

    def test_stale_settings_revision_returns_conflict(self):
        update = {'revision': 0, 'changes': {'default_model': 'test:local'}}
        self.client.request('/v1/preferences', update)
        with self.assertRaisesRegex(RuntimeError, 'reload and retry'):
            self.client.request('/v1/preferences', update)

    def test_preferences_endpoint_requires_authentication(self):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        conn.request('POST', '/v1/preferences', json.dumps({
            'revision': 0, 'changes': {'default_model': 'test:local'}}),
            {'Content-Type': 'application/json'})
        response = conn.getresponse()
        self.assertEqual(response.status, 401)
        response.read()
        conn.close()
        self.assertEqual(self.state.preferences.snapshot()['revision'], 0)


if __name__ == '__main__':
    unittest.main()
