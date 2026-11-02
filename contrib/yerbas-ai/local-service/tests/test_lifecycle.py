"""Real service-process lifecycle, with a lightweight fake Ollama executable."""
import json
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from yerbas_ai.cli import Client
from yerbas_ai.lifecycle import StateLock


FAKE = '''
import json,os,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,HTTPServer
record = Path(os.environ['TEST_RUNTIME_RECORD'])
record.write_text(json.dumps({'pid':os.getpid(),'cloud':os.environ.get('OLLAMA_NO_CLOUD')}))
time.sleep(float(os.environ.get('TEST_RUNTIME_DELAY','0')))
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  self.send_response(200);self.end_headers()
  self.wfile.write(json.dumps({'version':'test','models':[]}).encode())
host,port=os.environ['OLLAMA_HOST'].split(':')
HTTPServer((host,int(port)),Handler).serve_forever()
'''


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state_dir = self.root/'state'
        self.models = self.root/'models'
        self.models.mkdir()
        self.record = self.root/'runtime.json'
        self.fake = self.root/'fake-ollama'
        self.fake.write_text('#!'+sys.executable+'\n'+FAKE)
        self.fake.chmod(0o700)
        self.processes = []
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            self.port = s.getsockname()[1]

    def tearDown(self):
        for process in reversed(self.processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()
        self.temp.cleanup()

    def launch(self, delay='0'):
        env = os.environ.copy()
        env.update(TEST_RUNTIME_RECORD=str(self.record), TEST_RUNTIME_DELAY=delay)
        process = subprocess.Popen([
            sys.executable, '-m', 'yerbas_ai.service', '--state-dir', str(self.state_dir),
            '--models-dir', str(self.models), '--port', '0', '--runtime-port', str(self.port),
            '--ollama', str(self.fake)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env)
        self.processes.append(process)
        return process

    def wait_file(self, path, process):
        for _ in range(100):
            if path.exists():
                return
            if process.poll() is not None:
                self.fail('Service failed: '+process.stderr.read())
            time.sleep(.05)
        self.fail('Service startup timed out')

    def start(self):
        process = self.launch()
        self.wait_file(self.state_dir/'session.json', process)
        return process, Client(self.state_dir)

    def assert_closed(self):
        self.assertFalse((self.state_dir/'session.json').exists())
        with socket.socket() as s:
            s.settimeout(.5)
            self.assertNotEqual(s.connect_ex(('127.0.0.1', self.port)), 0)

    def test_sigterm_cleans_runtime_and_allows_restart(self):
        process, client = self.start()
        self.assertEqual(client.request('/v1/runtime')['version']['version'], 'test')
        self.assertEqual(json.loads(self.record.read_text())['cloud'], '1')
        self.assertEqual(stat.S_IMODE((self.state_dir/'session.json').stat().st_mode), 0o600)
        process.terminate()
        self.assertEqual(process.wait(timeout=8), 0)
        self.assert_closed()
        second, client = self.start()
        self.assertFalse(client.request('/v1/status')['blockchain_required'])
        second.terminate()
        self.assertEqual(second.wait(timeout=8), 0)

    def test_second_instance_does_not_overwrite_first_session(self):
        first, client = self.start()
        original = (self.state_dir/'session.json').read_bytes()
        second = self.launch()
        self.assertEqual(second.wait(timeout=5), 1)
        self.assertEqual(original, (self.state_dir/'session.json').read_bytes())
        self.assertIsNone(first.poll())
        self.assertFalse(client.request('/v1/status')['stopping'])

    def test_runtime_exit_stops_service_without_fallback(self):
        process, client = self.start()
        os.kill(json.loads(self.record.read_text())['pid'], signal.SIGTERM)
        self.assertEqual(process.wait(timeout=8), 1)
        self.assert_closed()

    def test_shutdown_during_startup(self):
        process = self.launch(delay='20')
        self.wait_file(self.record, process)
        process.terminate()
        self.assertEqual(process.wait(timeout=8), 0)
        self.assert_closed()

    def test_occupied_runtime_port_is_not_reused(self):
        with socket.socket() as s:
            s.bind(('127.0.0.1', self.port))
            s.listen()
            process = self.launch()
            self.assertEqual(process.wait(timeout=5), 1)
            self.assertFalse(self.record.exists())
            self.assertFalse((self.state_dir/'session.json').exists())

    def test_old_lock_file_is_reusable(self):
        self.state_dir.mkdir()
        (self.state_dir/'service.lock').write_text('old stale marker')
        with StateLock(self.state_dir):
            with self.assertRaises(RuntimeError):
                with StateLock(self.state_dir):
                    pass
        with StateLock(self.state_dir):
            pass

    def test_schedule_survives_service_restart(self):
        process, client = self.start()
        schedule = {'enabled': True, 'timezone': 'America/Los_Angeles',
                    'days': [0, 2, 4], 'start': '22:00', 'end': '06:00'}
        client.request('/v1/preferences', {'revision': 0, 'changes': {'schedule': schedule}})
        process.terminate()
        self.assertEqual(process.wait(timeout=8), 0)
        second, client = self.start()
        self.assertEqual(client.request('/v1/preferences')['schedule'], schedule)
        self.assertFalse(client.request('/v1/availability')['accepting_network_jobs'])

    def test_corrupt_preferences_stop_startup_without_loading_runtime(self):
        self.state_dir.mkdir()
        path = self.state_dir/'preferences.json'
        path.write_text('{broken')
        process = self.launch()
        self.assertEqual(process.wait(timeout=5), 1)
        self.assertFalse(self.record.exists())
        self.assertFalse((self.state_dir/'session.json').exists())
        self.assertEqual(path.read_text(), '{broken')

    def test_cli_schedule_workflow(self):
        process, client = self.start()
        command = [sys.executable, '-m', 'yerbas_ai.cli', '--state-dir', str(self.state_dir)]
        result = subprocess.run(command+['schedule', 'set', '--timezone', 'America/Los_Angeles',
                                        '--days', 'mon,wed,fri', '--start', '22:00', '--end', '06:00'],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('network contribution is not implemented', result.stderr)
        saved = json.loads(result.stdout)
        self.assertEqual(saved['schedule']['days'], [0, 2, 4])
        show = subprocess.run(command+['schedule', 'show'], capture_output=True, text=True, timeout=5)
        self.assertEqual(show.returncode, 0, show.stderr)
        self.assertFalse(json.loads(show.stdout)['availability']['accepting_network_jobs'])
        disable = subprocess.run(command+['schedule', 'disable'], capture_output=True, text=True, timeout=5)
        self.assertEqual(disable.returncode, 0, disable.stderr)
        self.assertFalse(client.request('/v1/preferences')['schedule']['enabled'])

    def test_invalid_cli_schedule_does_not_modify_preferences(self):
        process, client = self.start()
        before = client.request('/v1/preferences')
        result = subprocess.run([sys.executable, '-m', 'yerbas_ai.cli', '--state-dir', str(self.state_dir),
                                 'schedule', 'set', '--timezone', 'UTC', '--days', 'notaday',
                                 '--start', '22:00', '--end', '06:00'],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(client.request('/v1/preferences'), before)
