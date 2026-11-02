"""Linux per-user wallet control agent. No root, network listener, GPU or wallet keys."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import re
import socket
import sqlite3
import stat
import struct
import time
import uuid

ID = re.compile(r'[a-f0-9]{32}\Z')
MAX_REQUEST = 8192
VERSION = 1

class AgentError(Exception):
    def __init__(self, code): self.code = code

def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('duplicate key')
        result[key] = value
    return result

def read_json(directory, name, limit=16384):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_size > limit:
            raise ValueError('invalid file')
        with os.fdopen(fd, 'rb', closefd=False) as stream: data = stream.read(limit + 1)
        if len(data) > limit: raise ValueError('oversized')
        value = json.loads(data, object_pairs_hook=unique)
        if not isinstance(value, dict): raise ValueError('object required')
        return value
    finally: os.close(fd)

def open_directory(path, parent=None):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    st = os.fstat(fd)
    if st.st_uid != os.getuid() or st.st_mode & 0o022:
        os.close(fd); raise ValueError('directory must be owner controlled')
    return fd


BROKER_SOCKET = Path('/run/yerbas-ai-provider/broker.sock')

def broker_exchange(connection, method, params, rid):
    # Authenticate the privileged service independently of the socket pathname.
    _, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
    if uid != 0: raise ValueError('broker must be root owned')
    deadline = time.monotonic() + 1.0
    connection.settimeout(1.0)
    connection.sendall(json.dumps(dict(v=1, id=rid, method=method, params=params)).encode()+b'\n')
    data = bytearray()
    while b'\n' not in data:
        remaining = deadline - time.monotonic()
        if remaining <= 0: raise TimeoutError('broker deadline')
        connection.settimeout(remaining)
        block = connection.recv(min(1024, MAX_REQUEST + 1 - len(data)))
        if not block: raise ValueError('incomplete broker response')
        data.extend(block)
        if len(data) > MAX_REQUEST: raise ValueError('oversized broker response')
    if not data.endswith(b'\n') or data.count(b'\n') != 1: raise ValueError('invalid broker frame')
    response = json.loads(data, object_pairs_hook=unique)
    if not isinstance(response, dict) or type(response.get('v')) is not int or response['v'] != 1 or response.get('id') != rid or type(response.get('ok')) is not bool:
        raise ValueError('invalid broker response')
    if not response['ok']:
        if set(response) != {'v','id','ok','error'} or not isinstance(response['error'],dict) or set(response['error']) != {'code'} or not isinstance(response['error']['code'],str) or not re.fullmatch(r'[a-z_]{1,80}',response['error']['code']):
            raise ValueError('invalid broker error')
        raise AgentError(response['error']['code'])
    if set(response) != {'v','id','ok','result'}: raise ValueError('invalid broker response')
    return response['result']

def broker_capabilities(connection):
    response = {'result':broker_exchange(connection,'capabilities',{},uuid.uuid4().hex)}
    result = response['result']
    if not isinstance(result, dict) or set(result) != {'protocol','submissions_enabled','methods','gpu_submission_ready'}:
        raise ValueError('invalid broker capabilities')
    if type(result['protocol']) is not int or result['protocol'] != 1 or type(result['submissions_enabled']) is not bool or type(result['gpu_submission_ready']) is not bool:
        raise ValueError('invalid broker capability types')
    expected = ['capabilities','status','cancel'] + (['submit'] if result['submissions_enabled'] else [])
    if result['methods'] != expected: raise ValueError('unsupported broker methods')
    return {'available':True, 'authenticated_root':True, 'submissions_enabled':result['submissions_enabled'],
            'gpu_submission_ready':result['gpu_submission_ready']}

def provider_connection():
    for parent in BROKER_SOCKET.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('unsafe broker ancestry')
    info = BROKER_SOCKET.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o660:
        raise ValueError('unsafe broker socket')
    connection=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
    try:
        connection.settimeout(1.0);connection.connect(str(BROKER_SOCKET));return connection
    except BaseException:connection.close();raise

def provider_snapshot():
    try:
        with provider_connection() as connection:return broker_capabilities(connection)
    except (OSError, ValueError, TypeError, RecursionError, KeyError, AgentError):
        return {'available':False, 'authenticated_root':False, 'submissions_enabled':False, 'gpu_submission_ready':False}

def provider_control(method, run, rid):
    if method not in ('status','cancel') or not isinstance(run,str) or not ID.fullmatch(run) or not ID.fullmatch(rid):raise ValueError('invalid provider control')
    with provider_connection() as connection:
        result=broker_exchange(connection,method,{'run_id':run},rid)
    if not isinstance(result,dict):raise ValueError('invalid provider result')
    if method=='status':
        if set(result)!={'id','mode','contribution','state'} or result['id']!=run or result['mode'] not in ('train','replay') or not isinstance(result['contribution'],str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',result['contribution']) or result['state'] not in ('queued','dispatching','running','stop_requested','uncertain','completed','failed','cancelled'):
            raise ValueError('invalid provider status')
    elif set(result)!={'run_id','stop_recorded','shutdown_confirmed'} or result['run_id']!=run or result['stop_recorded'] is not True or type(result['shutdown_confirmed']) is not bool:
        raise ValueError('invalid provider stop result')
    return result

def provider_submit(run, contribution, rid):
    with provider_connection() as connection:
        result=broker_exchange(connection,'submit',{'mode':'train','run_id':run,'contribution':contribution},rid)
    if not isinstance(result,dict) or set(result)!={'run_id','request_recorded','training_started'} or result['run_id']!=run or result['request_recorded'] is not True or result['training_started'] is not False:
        raise ValueError('invalid submission acknowledgement')
    return result

def submission_blocker(provider):
    if not provider['available']: return 'provider_broker_unavailable'
    if not provider['submissions_enabled']: return 'provider_submissions_disabled'
    return 'wallet_submission_not_enabled'

class Agent:
    def __init__(self, workspace, state, *, reward_client=None):
        self.reward_client = reward_client
        self.root = open_directory(str(workspace))
        self.state = Path(state)
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.state_fd = open_directory(str(self.state))
        if os.fstat(self.state_fd).st_mode & 0o077: raise ValueError('state must be private')
        self.lock = os.open('agent.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=self.state_fd)
        if not stat.S_ISREG(os.fstat(self.lock).st_mode): raise ValueError('invalid lock')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        dbpath = self.state / 'requests.sqlite3'
        if dbpath.is_symlink(): raise ValueError('invalid request journal')
        self.db = sqlite3.connect(dbpath)
        self.db.execute('CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, response TEXT)')
        self.db.commit()

    def identity_snapshot(self):
        try:
            info=os.stat('identity-status.json',dir_fd=self.state_fd,follow_symlinks=False)
            if info.st_mode&0o077:raise ValueError('private record required')
            value=read_json(self.state_fd,'identity-status.json',4096)
            fields={'schema','provider','address','proof','active','required','checked_at','origin','profile'}
            if set(value)!=fields or type(value['schema']) is not int or value['schema']!=1:raise ValueError('invalid identity record')
            from coordinator_binding import load, LEGACY_ORIGIN
            binding_path=Path('/etc/yerbas-ai/coordinator-binding.json')
            expected_origin=load(binding_path,Path('/etc/yerbas-ai/future-coordinator-ca.pem'))['origin'] if os.path.lexists(binding_path) else LEGACY_ORIGIN
            if value['provider']!=socket.gethostname() or value['origin']!=expected_origin or value['profile']!='yerbas-private-reduced-collateral-testnet':raise ValueError('identity binding differs')
            if not isinstance(value['address'],str) or not re.fullmatch('[1-9A-HJ-NP-Za-km-z]{26,50}',value['address']):raise ValueError('invalid identity address')
            if not isinstance(value['proof'],str) or not re.fullmatch('[a-f0-9]{64}',value['proof']):raise ValueError('invalid identity proof')
            if type(value['active']) is not bool or type(value['required']) is not bool or type(value['checked_at']) is not int or not 0<value['checked_at']<=time.time():raise ValueError('invalid identity status')
            return dict(value,available=True,historical=True,live_authorization=False)
        except (OSError,ValueError,TypeError):return dict(available=False,historical=True,live_authorization=False)

    def reward_snapshot(self):
        unavailable=dict(available=False,historical=True,live_authorization=False,payments_enabled=False)
        try:
            info=os.stat('reward-status.json',dir_fd=self.state_fd,follow_symlinks=False)
            if info.st_mode&0o077:raise ValueError('private record required')
            value=read_json(self.state_fd,'reward-status.json',16384)
            if set(value)!={'schema','provider','address','checked_at','profile','rewards'} or type(value['schema']) is not int or value['schema']!=1:raise ValueError('invalid reward record')
            identity=self.identity_snapshot()
            if not identity['available'] or value['provider']!=socket.gethostname() or value['address']!=identity['address'] or value['profile']!=identity['profile']:raise ValueError('reward identity differs')
            checked=value['checked_at']
            if type(checked) is not int or not 0<checked<=time.time():raise ValueError('invalid check time')
            if not isinstance(value['rewards'],list) or len(value['rewards'])>20:raise ValueError('bounded reward list required')
            seen=set()
            for row in value['rewards']:
                if not isinstance(row,dict) or set(row)!={'receipt','txid','amount_base_units','confirmations','required_confirmations','state','block_height','tip_height'}:raise ValueError('invalid reward fields')
                if not isinstance(row['receipt'],str) or not ID.fullmatch(row['receipt']) or row['receipt'] in seen:raise ValueError('invalid/duplicate receipt')
                seen.add(row['receipt'])
                if not isinstance(row['txid'],str) or not re.fullmatch('[a-f0-9]{64}',row['txid']):raise ValueError('invalid txid')
                for key in ('amount_base_units','confirmations','required_confirmations','block_height','tip_height'):
                    if type(row[key]) is not int:raise ValueError('integer reward fields required')
                if not 0<row['amount_base_units']<=21000000*100000000 or not 1<=row['required_confirmations']<=100:raise ValueError('invalid amount/depth')
                if not 0<=row['block_height']<=row['tip_height'] or row['confirmations']!=row['tip_height']-row['block_height']+1:raise ValueError('inconsistent chain snapshot')
                expected='confirmed' if row['confirmations']>=row['required_confirmations'] else 'confirming'
                if row['state']!=expected:raise ValueError('invalid reward state')
            return dict(value,available=True,historical=True,stale=time.time()-checked>300,live_authorization=False,payments_enabled=False)
        except (OSError,ValueError,TypeError,KeyError):return unavailable

    def submission_enabled(self):
        try:
            info=os.stat('submission-policy.json',dir_fd=self.state_fd,follow_symlinks=False)
            if info.st_mode&0o077:return False
            value=read_json(self.state_fd,'submission-policy.json',1024)
            return set(value)=={'schema','enabled'} and type(value['schema']) is int and value['schema']==1 and value['enabled'] is True
        except (OSError,ValueError,TypeError):return False

    def operator_directory(self):
        work = open_directory('work', self.root)
        try: return open_directory('operator', work)
        finally: os.close(work)

    def snapshot(self):
        try:
            directory = self.operator_directory()
            try:
                lock = os.open('session.lock', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                try:
                    st = os.fstat(lock)
                    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid(): raise ValueError('invalid lock')
                    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB); active = False
                    except BlockingIOError: active = True
                    value = read_json(directory, 'active.json')
                    if not ID.fullmatch(value.get('run_id', '')) or not isinstance(value.get('phase'), str): raise ValueError('invalid session')
                    return {'available': True, 'active': active, 'run_id': value['run_id'],
                            'phase': value['phase'][:80], 'provider': str(value.get('provider', ''))[:80]}
                finally: os.close(lock)
            finally: os.close(directory)
        except (OSError, ValueError, TypeError): return {'available': False, 'active': False}

    def history(self):
        rows = []
        try: directory = open_directory('outputs', self.root)
        except (OSError, ValueError): return {'available': False, 'jobs': []}
        try:
            candidates = []
            with os.scandir(directory) as entries:
                for index, entry in enumerate(entries):
                    if index >= 4096: break
                    match = re.fullmatch(r'text-handoff-([a-f0-9]{32})\.json', entry.name)
                    if match and entry.is_file(follow_symlinks=False):
                        candidates.append((entry.stat(follow_symlinks=False).st_mtime, entry.name, match[1]))
            for _, name, run in sorted(candidates, reverse=True)[:20]:
                try:
                    value = read_json(directory, name, 262144)
                    if value.get('run_id') != run or type(value.get('passed')) is not bool: continue
                    rows.append({'run_id': run, 'reported_passed': value['passed'], 'reported_stopped': value.get('owner_stopped') is True})
                except (OSError, ValueError, TypeError): continue
        finally: os.close(directory)
        return {'available': True, 'jobs': rows, 'historical': True, 'scan_limit': 4096}

    def cancel(self, run):
        current = self.snapshot()
        directory = None
        try:
            directory = self.operator_directory()
            # A durable exact-job marker also makes recovery after a lost response safe.
            try:
                if read_json(directory, run + '.stop').get('run_id') == run:
                    return {'run_id': run, 'stop_requested': True, 'shutdown_confirmed': False}
            except FileNotFoundError: pass
            if not current.get('active') or current.get('run_id') != run: raise AgentError('job_not_active')
            name = '.agent-stop-' + uuid.uuid4().hex
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                with os.fdopen(fd, 'w') as stream:
                    json.dump({'run_id': run, 'requested_at': time.time()}, stream); stream.flush(); os.fsync(stream.fileno())
                os.rename(name, run + '.stop', src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                try: os.unlink(name, dir_fd=directory)
                except FileNotFoundError: pass
            return {'run_id': run, 'stop_requested': True, 'shutdown_confirmed': False}
        finally:
            if directory is not None: os.close(directory)

    def dispatch(self, request):
        rid = request.get('id') if isinstance(request, dict) else None
        response = {'v': VERSION, 'id': rid if isinstance(rid, str) and ID.fullmatch(rid) else None}
        try:
            if not isinstance(request, dict) or set(request) != {'v', 'id', 'method', 'params'} or type(request['v']) is not int or request['v'] != VERSION or response['id'] is None:
                raise AgentError('invalid_request')
            method, params = request['method'], request['params']
            if not isinstance(method, str) or not isinstance(params, dict): raise AgentError('invalid_request')
            if method in ('rewards.request','rewards.status'):
                if set(params)!={'receipt'} or not isinstance(params['receipt'],str) or not ID.fullmatch(params['receipt']):raise AgentError('invalid_params')
                if self.reward_client is None:raise AgentError('reward_requests_unavailable')
                try:result=self.reward_client.reward(method.split('.')[1],params['receipt'])
                except Exception:raise AgentError('reward_coordinator_unavailable')
                if result is not None:
                    from request_status import validate
                    validate(result,params['receipt'],socket.gethostname())
                response.update(ok=True,result={'receipt':params['receipt'],'request':result});return response
            if method in ('provider.status','provider.cancel','provider.submit'):
                if set(params)!=({'run_id','contribution'} if method=='provider.submit' else {'run_id'}) or not isinstance(params['run_id'],str) or not ID.fullmatch(params['run_id']):raise AgentError('invalid_params')
                if method=='provider.submit' and (not isinstance(params['contribution'],str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',params['contribution'])):raise AgentError('invalid_params')
                if method=='provider.status':
                    response.update(ok=True,result=provider_control('status',params['run_id'],rid));return response
                fingerprint=json.dumps([method,params],sort_keys=True)
                row=self.db.execute('SELECT fingerprint,response FROM requests WHERE id=?',(rid,)).fetchone()
                if row:
                    if row[0]!=fingerprint:raise AgentError('request_id_conflict')
                    if row[1]:return json.loads(row[1])
                else:
                    if method=='provider.submit' and not self.submission_enabled():raise AgentError('submission_disabled')
                    if self.db.execute('SELECT count(*) FROM requests').fetchone()[0]>=10000:raise AgentError('journal_full')
                    self.db.execute('INSERT INTO requests VALUES (?,?,NULL)',(rid,fingerprint));self.db.commit()
                # A lost reply leaves intent pending. Reuse this ID at the root
                # broker after restart; never guess whether stopping occurred.
                try:
                    if method=='provider.submit':
                        if not self.submission_enabled():raise AgentError('submission_disabled')
                        result=provider_submit(params['run_id'],params['contribution'],rid)
                    else:result=provider_control('cancel',params['run_id'],rid)
                    response.update(ok=True,result=result)
                except AgentError as exc:response.update(ok=False,error={'code':exc.code})
                except (OSError,ValueError,TypeError):
                    response.update(ok=False,error={'code':'provider_response_uncertain'});return response
                self.db.execute('UPDATE requests SET response=? WHERE id=?',(json.dumps(response),rid));self.db.commit();return response
            if method == 'jobs.cancel':
                if set(params) != {'run_id'} or not isinstance(params['run_id'], str) or not ID.fullmatch(params['run_id']): raise AgentError('invalid_params')
                fingerprint = json.dumps([method, params], sort_keys=True)
                row = self.db.execute('SELECT fingerprint,response FROM requests WHERE id=?', (rid,)).fetchone()
                if row:
                    if row[0] != fingerprint: raise AgentError('request_id_conflict')
                    if row[1]: return json.loads(row[1])
                else:
                    if self.db.execute('SELECT count(*) FROM requests').fetchone()[0] >= 10000: raise AgentError('journal_full')
                    self.db.execute('INSERT INTO requests VALUES (?,?,NULL)', (rid, fingerprint)); self.db.commit()
                try: response.update(ok=True, result=self.cancel(params['run_id']))
                except AgentError as exc: response.update(ok=False, error={'code': exc.code})
                self.db.execute('UPDATE requests SET response=? WHERE id=?', (json.dumps(response), rid)); self.db.commit()
                return response
            if params: raise AgentError('invalid_params')
            if method == 'capabilities':
                provider = provider_snapshot()
                enabled=self.submission_enabled() and provider['submissions_enabled'] and provider['authenticated_root']
                result = {'methods': ['capabilities', 'status', 'jobs.list', 'jobs.cancel', 'provider.status', 'provider.cancel']+(['provider.submit'] if enabled else []), 'training_submission': enabled, 'submission_blocker': None if enabled else submission_blocker(provider), 'provider_broker': provider, 'payments': False}
            elif method == 'status':
                provider=provider_snapshot()
                result = {'reward_requests_ready':self.reward_client is not None and self.reward_client.ready(), 'wallet_rewards':self.reward_snapshot(), 'wallet_identity':self.identity_snapshot(), 'session': self.snapshot(), 'gpu_activity_checked': False, 'submission_ready': self.submission_enabled() and provider['submissions_enabled'] and provider['authenticated_root'], 'provider_broker': provider}
            elif method == 'jobs.list': result = self.history()
            elif method == 'jobs.submit': raise AgentError('setup_required')
            else: raise AgentError('method_not_supported')
            response.update(ok=True, result=result)
        except AgentError as exc: response.update(ok=False, error={'code': exc.code})
        except (OSError, ValueError, TypeError, sqlite3.Error): response.update(ok=False, error={'code': 'state_unavailable'})
        return response

    def close(self):
        self.db.close()
        for fd in (self.lock, self.state_fd, self.root): os.close(fd)

def authorized(connection):
    _, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
    return uid == os.getuid()

def serve(agent, path):
    path = Path(path)
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid(): raise ValueError('refusing to replace non-socket')
        path.unlink()  # Singleton lock is already held; only our private stale socket.
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path)); os.chmod(path, 0o600); server.listen(4)
    try:
        while True:
            connection, _ = server.accept()
            with connection:
                connection.settimeout(2)
                try:
                    if not authorized(connection): continue
                    data = bytearray()
                    while b'\n' not in data and len(data) <= MAX_REQUEST:
                        chunk = connection.recv(min(1024, MAX_REQUEST + 1 - len(data)))
                        if not chunk: break
                        data.extend(chunk)
                    if len(data) > MAX_REQUEST or not data.endswith(b'\n') or data.count(b'\n') != 1: raise ValueError('bad framing')
                    reply = agent.dispatch(json.loads(data, object_pairs_hook=unique))
                    connection.sendall(json.dumps(reply, allow_nan=False).encode() + b'\n')
                except (ValueError, OSError):
                    try: connection.sendall(b'{"v":1,"id":null,"ok":false,"error":{"code":"invalid_request"}}\n')
                    except OSError: pass
    finally:
        server.close(); path.unlink(missing_ok=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    if os.getuid() == 0: raise SystemExit('Run the wallet agent as the wallet owner, never root')
    os.umask(0o077)
    from reward_socket import SocketClient
    client=SocketClient()
    agent = Agent(args.workspace, args.state, reward_client=client)
    try: serve(agent, args.state / 'control.sock')
    finally: agent.close()

if __name__ == '__main__': main()
