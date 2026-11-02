"""Exercise real HTTP transport against a controlled Ollama-shaped server."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
import unittest
from yerbas_ai.service import Runtime, State


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.stall = False
        self.received = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({'models': [
                    {'name': 'test:local'}, {'name': 'test:cloud'},
                    {'name': 'remote', 'remote_host': 'example.com'}]}).encode())

            def do_POST(self):
                owner.received = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.send_response(200)
                self.end_headers()
                owner.started.set()
                if owner.stall:
                    owner.release.wait(3)
                    return
                for item in ({'message': {'content': 'Hello '}, 'done': False},
                             {'message': {'content': 'world'}, 'done': True,
                              'prompt_eval_count': 4, 'eval_count': 2}):
                    self.wfile.write(json.dumps(item).encode()+b'\n')
                    self.wfile.flush()

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.runtime = Runtime(self.server.server_port)
        self.state = State(self.runtime)

    def tearDown(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def submit(self):
        return self.state.submit({'mode': 'local', 'model': 'test:local',
                                  'messages': [{'role': 'user', 'content': 'Hi'}]})

    def wait_done(self, job):
        deadline = time.monotonic()+2
        while time.monotonic() < deadline:
            with self.state.lock:
                result = self.state.public(self.state.jobs[job['id']])
            if result['state'] not in ('running', 'cancelling'):
                return result
            time.sleep(.01)
        self.fail('Transport did not stop within two seconds')

    def test_stream_and_runtime_parameters(self):
        result = self.wait_done(self.submit())
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['result']['text'], 'Hello world')
        self.assertEqual(result['result']['output_tokens'], 2)
        self.assertEqual(self.received['keep_alive'], 0)
        self.assertEqual(self.received['options']['num_predict'], 256)

    def test_cancel_interrupts_stalled_http_response(self):
        self.stall = True
        job = self.submit()
        self.assertTrue(self.started.wait(1))
        self.state.cancel(job['id'])
        self.assertEqual(self.wait_done(job)['state'], 'cancelled')

    def test_remote_models_are_excluded(self):
        self.assertEqual([m['name'] for m in self.runtime.models()], ['test:local'])
