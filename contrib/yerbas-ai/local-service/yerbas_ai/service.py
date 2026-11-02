"""Authenticated loopback API and single-request local inference service."""
import argparse
import hashlib
import hmac
import http.client
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .hardware import inventory, resolve_gpu
from .preferences import Preferences, RevisionConflict, availability

MAX_BODY = 65536


class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


class Runtime:
    def __init__(self, port):
        self.port = port
        self.process = None

    def check_alive(self):
        if self.process is not None and self.process.poll() is not None:
            raise APIError(503, 'Managed runtime exited; restart the service')

    def request(self, path, body=None):
        self.check_alive()
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        try:
            conn.request('POST' if body is not None else 'GET', path,
                         json.dumps(body) if body is not None else None,
                         {'Content-Type': 'application/json'})
            response = conn.getresponse()
            raw = response.read(2 * 1024 * 1024 + 1)
            if response.status != 200 or len(raw) > 2 * 1024 * 1024:
                raise APIError(503, 'Local runtime request failed')
            return json.loads(raw)
        finally:
            conn.close()

    def models(self):
        models = self.request('/api/tags').get('models', [])
        return [m for m in models if not m.get('remote_host')
                and not m.get('remote_model') and 'cloud' not in m['name'].lower()]

    def generate(self, job, messages, limit):
        self.check_alive()
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=120)
        transport = [None]
        def interrupt():
            sock = transport[0] or conn.sock
            if sock:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        job['interrupt'] = interrupt
        try:
            if job['cancel'].is_set():
                return None
            conn.request('POST', '/api/chat', json.dumps({
                'model': job['model'], 'messages': messages, 'stream': True,
                'keep_alive': 0,
                'options': {'num_predict': limit, 'num_ctx': 4096},
            }), {'Content-Type': 'application/json'})
            transport[0] = conn.sock
            if job['cancel'].is_set():
                interrupt()
                return None
            response = conn.getresponse()
            if response.status != 200:
                raise APIError(502, 'Local model rejected the request')
            output = []
            output_size = 0
            while not job['cancel'].is_set():
                line = response.readline(MAX_BODY + 1)
                if not line:
                    raise APIError(502, 'Runtime stream ended without completion')
                if len(line) > MAX_BODY:
                    raise APIError(502, 'Runtime response exceeded limits')
                item = json.loads(line)
                if item.get('error'):
                    raise APIError(502, 'Local inference failed')
                piece = item.get('message', {}).get('content', '')
                output_size += len(piece)
                if output_size > MAX_BODY:
                    raise APIError(502, 'Output exceeded limits')
                output.append(piece)
                if item.get('done'):
                    return {'text': ''.join(output),
                            'input_tokens': item.get('prompt_eval_count'),
                            'output_tokens': item.get('eval_count')}
            return None
        finally:
            interrupt()
            conn.close()


class State:
    def __init__(self, runtime):
        self.runtime = runtime
        self.lock = threading.RLock()
        self.jobs = {}
        self.active = None
        self.settings = {'gpu_selection': 'runtime default', 'cloud_enabled': False}
        self.stopping = False
        self.preferences = Preferences()
        self.instance_id = uuid.uuid4().hex
        self.provider_enabled = False
        self.provider_watchdog_seconds = 30
        self.provider_paused = False
        self.provider_models = {}
        self.personal_priority_until = 0.0
        self.personal_waiting = False

    def provider_status(self):
        with self.lock:
            window = availability(self.preferences.snapshot()['schedule'])
            reason = ('disabled' if not self.provider_enabled else
                      'stopping' if self.stopping else
                      'paused' if self.provider_paused else
                      'outside_schedule' if not window['policy_allows_contribution'] else
                      'busy' if self.active else
                      'personal_priority' if time.monotonic() < self.personal_priority_until else 'ready')
            return {'enabled': self.provider_enabled, 'paused': self.provider_paused,
                    'eligible_for_coordinator_job': reason == 'ready', 'reason': reason,
                    'allowed_models': list(self.provider_models), 'active_job': self.active,
                    'approved_model_digests': dict(self.provider_models),
                    'instance_id': self.instance_id, 'automatic_network_connection': False,
                    'provider_watchdog_seconds': self.provider_watchdog_seconds}

    def public(self, job):
        return {k: v for k, v in job.items()
                if k not in ('cancel', 'interrupt', 'request_hash', 'last_heartbeat')}

    def submit(self, data, provider=False):
        if data.get('mode') != 'local':
            raise APIError(400, 'Explicit mode=local required; network is not implemented')
        assignment = data.get('assignment_id') if provider else None
        fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest() if provider else None
        job_id = 'provider-'+assignment if isinstance(assignment, str) else None
        if provider:
            if not isinstance(assignment, str) or not re.fullmatch('[0-9a-f]{32}', assignment):
                raise APIError(400, 'assignment_id must be a 32-character lowercase hex ID')
            with self.lock:
                if job_id in self.jobs:
                    old = self.jobs[job_id]
                    if old['request_hash'] != fingerprint:
                        raise APIError(409, 'Assignment ID reused with a different request')
                    return self.public(old)
        model = data.get('model')
        if model is None:
            model = self.preferences.snapshot()['default_model']
        messages = data.get('messages')
        limit = data.get('max_output_tokens', 256)
        if not isinstance(model, str) or not model:
            raise APIError(400, 'Specify a model or save a default_model first')
        if type(limit) is not int or not 1 <= limit <= 1024:
            raise APIError(400, 'max_output_tokens must be 1..1024')
        if not isinstance(messages, list) or not 1 <= len(messages) <= 40:
            raise APIError(400, 'messages must contain 1..40 entries')
        for message in messages:
            if (not isinstance(message, dict)
                    or set(message) != {'role', 'content'}
                    or message['role'] not in ('user', 'assistant')
                    or not isinstance(message['content'], str)):
                raise APIError(400, 'Only user/assistant text messages are accepted')
        if messages[-1]['role'] != 'user':
            raise APIError(400, 'Final message must be from user')
        if sum(len(m['content'].encode()) for m in messages) > 4096:
            raise APIError(400, 'Conversation exceeds 4096 UTF-8 bytes; start a new chat')
        installed = {m['name']: m for m in self.runtime.models()}
        if model not in installed:
            raise APIError(400, 'Choose an installed local model; automatic downloads are disabled')
        with self.lock:
            if provider:
                # Another HTTP thread may have submitted the same assignment while
                # this one was checking the runtime model inventory.
                if job_id in self.jobs:
                    old = self.jobs[job_id]
                    if old['request_hash'] != fingerprint:
                        raise APIError(409, 'Assignment ID reused with a different request')
                    return self.public(old)
                if not self.provider_status()['eligible_for_coordinator_job']:
                    raise APIError(409, 'Provider is not accepting new assignments')
                if model not in self.provider_models or installed[model].get('digest') != self.provider_models[model]:
                    raise APIError(409, 'Model is not approved or its digest changed')
            else:
                # Give the owner a retry window after an occupied-slot response,
                # and prevent a worker immediately taking the next free slot.
                self.personal_priority_until = time.monotonic()+5
                if self.active and self.jobs[self.active].get('source') == 'coordinator':
                    self.personal_waiting = True
            if self.stopping:
                raise APIError(503, 'Service is stopping')
            if self.active:
                raise APIError(409, 'Another local request is active')
            # Bound memory retention; prompts are never stored in job records.
            now = time.time()
            self.jobs = {k: j for k, j in self.jobs.items() if now-j['created'] < 600}
            while len(self.jobs) >= 32:
                self.jobs.pop(next(iter(self.jobs)))
            job = {'id': job_id if provider else uuid.uuid4().hex, 'model': model, 'mode': 'local',
                   'source': 'coordinator' if provider else 'personal',
                   'state': 'running', 'created': now, 'cancel': threading.Event(),
                   'request_hash': fingerprint, 'last_heartbeat': time.monotonic()}
            self.jobs[job['id']] = job
            self.active = job['id']
            threading.Thread(target=self.run, args=(job, messages, limit), daemon=True).start()
            return self.public(job)

    def heartbeat(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job.get('source') != 'coordinator':
                raise APIError(404, 'Provider job not found')
            if job['state'] != 'running' or job['cancel'].is_set():
                raise APIError(409, 'Provider job is no longer running')
            if time.monotonic()-job['last_heartbeat'] >= self.provider_watchdog_seconds:
                job['watchdog_expired'] = True
                self.cancel(job_id)
                raise APIError(409, 'Provider heartbeat deadline elapsed')
            job['last_heartbeat'] = time.monotonic()
            return {'job': job_id, 'accepted': True}

    def run(self, job, messages, limit):
        done = threading.Event()
        deadline = time.monotonic()+120
        def watch():
            while not done.wait(min(.25, self.provider_watchdog_seconds/4)):
                with self.lock:
                    if job['state'] not in ('running', 'cancelling'):
                        return
                    now = time.monotonic()
                    if now >= deadline:
                        job['deadline_expired'] = True
                    elif job['source'] == 'coordinator' and now-job['last_heartbeat'] >= self.provider_watchdog_seconds:
                        job['watchdog_expired'] = True
                    else:
                        continue
                    self.cancel(job['id'])
                    return
        watchdog = threading.Thread(target=watch, daemon=True)
        watchdog.start()
        try:
            result = self.runtime.generate(job, messages, limit)
            with self.lock:
                if not job['cancel'].is_set():
                    if result is None:
                        raise APIError(502, 'Missing completion result')
                    if not isinstance(result.get('text'), str) or not result['text'].strip():
                        raise APIError(502, 'Model produced no visible response within its output budget; try a larger max_output_tokens')
                    job['result'] = result
                    job['state'] = 'completed'
        except Exception as exc:
            with self.lock:
                if not job['cancel'].is_set():
                    job['state'] = 'failed'
                    job['error'] = exc.message if isinstance(exc, APIError) else 'Local runtime unavailable or failed'
        finally:
            done.set()
            watchdog.join()
            with self.lock:
                if job['cancel'].is_set():
                    job['state'] = 'failed' if job.get('deadline_expired') or job.get('watchdog_expired') else 'cancelled'
                    job.pop('result', None)
                    if job.get('deadline_expired'):
                        job['error'] = 'Request exceeded 120-second deadline'
                    elif job.get('watchdog_expired'):
                        job['error'] = 'Provider worker heartbeat expired'
                job.pop('interrupt', None)
                job['finished'] = time.time()
                self.active = None
                if job.get('source') == 'coordinator' and self.personal_waiting:
                    self.personal_priority_until = time.monotonic()+5
                    self.personal_waiting = False

    def cancel(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                raise APIError(404, 'Unknown job')
            if job['state'] in ('running', 'cancelling'):
                job['cancel'].set()
                job['state'] = 'cancelling'
                if job.get('interrupt'):
                    job['interrupt']()
            return self.public(job)


def create_server(port, token, state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log prompts, secrets, or request bodies.

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def read_json(self):
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= MAX_BODY:
                raise APIError(413, 'Request body missing or too large')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise APIError(400, 'JSON object required')
            return data

        def dispatch(self):
            status = 200
            try:
                if self.headers.get('Origin') is not None:
                    raise APIError(403, 'Browser-origin requests are not accepted')
                provided = self.headers.get('Authorization', '')
                if not hmac.compare_digest(provided.encode(), ('Bearer '+token).encode()):
                    raise APIError(401, 'Authentication required')
                if self.command == 'GET' and self.path == '/v1/status':
                    with state.lock:
                        value = {'api_version': 1, 'mode': 'local',
                                 'active_job': state.active, 'blockchain_required': False,
                                 'network_enabled': False, 'provider_enabled': state.provider_enabled,
                                 'instance_id': state.instance_id,
                                 'stopping': state.stopping, 'settings': state.settings,
                                 'availability': availability(state.preferences.snapshot()['schedule'])}
                elif self.command == 'GET' and self.path == '/v1/provider/status':
                    value = state.provider_status()
                elif self.command == 'POST' and self.path == '/v1/provider/control':
                    data = self.read_json()
                    if set(data) != {'paused'} or type(data['paused']) is not bool:
                        raise APIError(400, 'paused must be boolean')
                    with state.lock:
                        state.provider_paused = data['paused']
                        value = state.provider_status()
                elif self.command == 'POST' and self.path == '/v1/provider/jobs':
                    value = state.submit(self.read_json(), provider=True)
                    status = 202
                elif self.command == 'POST' and self.path == '/v1/provider/heartbeat':
                    data = self.read_json()
                    if set(data) != {'job'} or not isinstance(data['job'], str):
                        raise APIError(400, 'job must be a string')
                    value = state.heartbeat(data['job'])
                elif self.command == 'GET' and self.path == '/v1/preferences':
                    value = state.preferences.snapshot()
                elif self.command == 'GET' and self.path == '/v1/availability':
                    value = availability(state.preferences.snapshot()['schedule'])
                elif self.command == 'POST' and self.path == '/v1/preferences':
                    data = self.read_json()
                    if set(data) != {'revision', 'changes'} or not isinstance(data['changes'], dict):
                        raise APIError(400, 'revision and changes are required')
                    model = data['changes'].get('default_model')
                    if model is not None and model not in [m['name'] for m in state.runtime.models()]:
                        raise APIError(400, 'Default model must be installed locally')
                    try:
                        with state.lock:
                            if state.stopping:
                                raise APIError(503, 'Service is stopping')
                            value = state.preferences.update(data['changes'], data['revision'])
                    except RevisionConflict as exc:
                        raise APIError(409, str(exc)) from None
                    except ValueError as exc:
                        raise APIError(400, str(exc)) from None
                elif self.command == 'GET' and self.path == '/v1/hardware':
                    value = inventory()
                    value['gpu_selection'] = state.settings['gpu_selection']
                elif self.command == 'GET' and self.path == '/v1/runtime':
                    value = {'version': state.runtime.request('/api/version'),
                             'loaded_models': state.runtime.request('/api/ps').get('models', []),
                             'settings': state.settings}
                elif self.command == 'GET' and self.path == '/v1/models':
                    value = {'models': state.runtime.models()}
                elif self.command == 'GET' and self.path.startswith('/v1/jobs/'):
                    with state.lock:
                        job = state.jobs.get(self.path.removeprefix('/v1/jobs/'))
                        if not job:
                            raise APIError(404, 'Unknown job')
                        value = state.public(job)
                elif self.command == 'POST' and self.path == '/v1/jobs':
                    value = state.submit(self.read_json())
                    status = 202
                elif self.command == 'POST' and self.path.endswith('/cancel') and self.path.startswith('/v1/jobs/'):
                    value = state.cancel(self.path[len('/v1/jobs/'):-len('/cancel')])
                else:
                    raise APIError(404, 'Unknown API endpoint')
            except APIError as exc:
                status, value = exc.status, {'error': exc.message}
            except (ValueError, UnicodeError):
                status, value = 400, {'error': 'Invalid request'}
            except Exception:
                status, value = 503, {'error': 'Local service dependency unavailable'}
            raw = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        do_GET = dispatch
        do_POST = dispatch
    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    if os.name != 'posix':
        print('This prototype currently supports POSIX systems; Windows lifecycle support is pending.', file=sys.stderr)
        return 1
    from .lifecycle import StateLock, stop_runtime
    parser = argparse.ArgumentParser(description='Yerbas local AI service; no wallet or blockchain required')
    parser.add_argument('--state-dir', required=True, type=Path)
    parser.add_argument('--models-dir', required=True, type=Path,
                        help='Existing local Ollama model store; no downloads performed')
    parser.add_argument('--port', type=int, default=18450)
    parser.add_argument('--runtime-port', type=int, default=18451)
    parser.add_argument('--ollama', default='ollama')
    parser.add_argument('--gpu', help='NVIDIA host index or GPU UUID; missing devices are rejected')
    parser.add_argument('--allow-provider-jobs', action='store_true', help='Explicitly allow jobs from the local coordinator bridge')
    parser.add_argument('--provider-model', action='append', default=[], help='Exact approved model name; repeat for multiple models')
    args = parser.parse_args()
    if not args.models_dir.is_dir():
        parser.error('--models-dir must be an existing directory')
    if args.allow_provider_jobs != bool(args.provider_model):
        parser.error('--allow-provider-jobs and at least one --provider-model must be supplied together')
    if not (0 <= args.port <= 65535 and 1 <= args.runtime_port <= 65535):
        parser.error('Invalid service/runtime port')
    if args.port == args.runtime_port:
        parser.error('Service and runtime ports must differ')
    executable = shutil.which(args.ollama)
    if not executable:
        parser.error('Ollama executable not found')
    try:
        gpu = resolve_gpu(args.gpu, inventory()) if args.gpu is not None else None
    except ValueError as exc:
        parser.error(str(exc))
    token = secrets.token_urlsafe(32)
    state = State(Runtime(args.runtime_port))
    state.settings.update(gpu_selection=gpu or os.environ.get('CUDA_VISIBLE_DEVICES', 'runtime default'),
                          models_dir=str(args.models_dir.resolve()), runtime_executable=executable)
    server = None
    process = None
    stop = threading.Event()
    previous_signals = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    for sig in previous_signals:
        signal.signal(sig, lambda *_: stop.set())
    try:
        with StateLock(args.state_dir) as owner:
            try:
                # Malformed preferences fail startup rather than silently resetting policy.
                state.preferences = Preferences(args.state_dir/'preferences.json')
                server = create_server(args.port, token, state)
                server.timeout = .2
                # Refuse to reuse a runtime with unknown cloud settings.
                with socket.socket() as probe:
                    # Allow a clean restart while prior connections are in TIME_WAIT.
                    # This does not permit sharing an actively listening socket.
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    probe.bind(('127.0.0.1', args.runtime_port))
                env = os.environ.copy()
                env.update(OLLAMA_HOST=f'127.0.0.1:{args.runtime_port}', OLLAMA_NO_CLOUD='1',
                           OLLAMA_MODELS=str(args.models_dir.resolve()), OLLAMA_NUM_PARALLEL='1',
                           OLLAMA_MAX_LOADED_MODELS='1', OLLAMA_MAX_QUEUE='1', OLLAMA_KEEP_ALIVE='0')
                if gpu is not None:
                    env['CUDA_VISIBLE_DEVICES'] = gpu
                    # Explicit NVIDIA selection must not choose an AMD device instead.
                    env['ROCR_VISIBLE_DEVICES'] = ''
                    env['HIP_VISIBLE_DEVICES'] = ''
                process = subprocess.Popen([executable, 'serve'], env=env, start_new_session=True,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                state.runtime.process = process
                ready = False
                for _ in range(100):
                    if stop.is_set():
                        return 0
                    if process.poll() is not None:
                        raise RuntimeError('Managed Ollama runtime exited during startup')
                    try:
                        state.runtime.request('/api/version')
                        ready = True
                        break
                    except (OSError, APIError, ValueError):
                        stop.wait(.1)
                if not ready:
                    raise RuntimeError('Managed runtime did not become ready')
                if args.allow_provider_jobs:
                    installed = {m['name']: m for m in state.runtime.models()}
                    for name in args.provider_model:
                        if name not in installed or not isinstance(installed[name].get('digest'), str):
                            raise RuntimeError('Approved provider model must be installed with a digest: '+name)
                        state.provider_models[name] = installed[name]['digest']
                    state.provider_enabled = True
                owner.write_session({'port': server.server_port, 'token': token, 'pid': os.getpid()})
                print(f'Yerbas AI local service ready on 127.0.0.1:{server.server_port}', flush=True)
                print('Local only. No wallet, blockchain sync, or automatic downloads.', flush=True)
                while not stop.is_set():
                    if process.poll() is not None:
                        raise RuntimeError('Managed runtime exited; service stopped without fallback')
                    server.handle_request()
            finally:
                with state.lock:
                    state.stopping = True
                    if state.active:
                        state.cancel(state.active)
                if server is not None:
                    server.server_close()
                stop_runtime(process)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    finally:
        for sig, handler in previous_signals.items():
            signal.signal(sig, handler)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
