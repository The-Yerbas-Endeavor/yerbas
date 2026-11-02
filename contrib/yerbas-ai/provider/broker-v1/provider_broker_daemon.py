"""Root systemd-activated broker entry point. Requires reviewed installation.

No self-installation, enrollment, downloads, arbitrary commands or root GPU work.
"""
import argparse
import grp
import json
import os
from pathlib import Path
import pwd
import signal
import socket
import stat
import threading

from provider_broker import Broker
from provider_broker_transport import Transport
from provider_executor import read_json,require_root_ancestry,verify_policy,verify_installed_files
from provider_service_adapter import RequestSpool,PrivateRecords,ServiceAdapter

STATE=Path('/var/lib/yerbas-ai-broker')
POLICY=Path('/etc/yerbas-ai/provider.json')
SOCKET=Path('/run/yerbas-ai-provider/broker.sock')


def validate_config(config):
    if set(config)!={'schema','owner_uid','socket_gid','submissions_enabled'} or type(config['schema']) is not int or config['schema']!=1:
        raise ValueError('Unsupported broker configuration')
    if any(type(config[k]) is not int or config[k]<=0 for k in ('owner_uid','socket_gid')):
        raise ValueError('Explicit non-root owner and socket group required')
    if type(config['submissions_enabled']) is not bool:raise ValueError('Explicit submission setting required')
    return config


def preflight(config):
    owner=pwd.getpwuid(config['owner_uid']);group=grp.getgrgid(config['socket_gid'])
    if owner.pw_gid!=group.gr_gid and owner.pw_name not in group.gr_mem:raise ValueError('Owner cannot access configured socket group')
    provider=pwd.getpwnam('yerbas-provider')
    if provider.pw_uid<=0 or provider.pw_uid==owner.pw_uid:raise ValueError('Separate provider account required')
    for path in (STATE,STATE/'records',Path('/var/lib/yerbas-ai-provider/requests')):
        require_root_ancestry(path/'sentinel')
        info=path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:raise ValueError('Unsafe provisioned broker directory')
    if config['submissions_enabled']:
        require_root_ancestry(POLICY)
        policy=verify_policy(read_json(POLICY,owner=0))
        if policy['provider_uid']!=provider.pw_uid:raise ValueError('Provider policy/account mismatch')
        verify_installed_files(policy)
        # Enrollment validity is also enforced independently in each executor.
        credentials=read_json(policy['credentials'],owner=0)
        if set(credentials)!={'url','token','ca','provider'} or not credentials['token'] or credentials['ca'] not in policy['files']:
            raise ValueError('Provider enrollment incomplete')
        for mode in ('provider','replay'):
            unit=Path('/etc/systemd/system/yerbas-text-'+mode+'@.service')
            require_root_ancestry(unit)
            info=unit.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:raise ValueError('Unsafe executor unit')
            text=unit.read_text()
            if 'KillMode=control-group' not in text or 'BindsTo=yerbas-provider-broker.service' not in text:
                raise ValueError('Executor lifetime must be bound to broker')
    return provider


def inherited_socket(config):
    if os.environ.get('LISTEN_PID')!=str(os.getpid()) or os.environ.get('LISTEN_FDS')!='1' or os.environ.get('LISTEN_FDNAMES')!='provider-broker':
        raise ValueError('Exactly one named systemd socket required')
    listener=socket.socket(fileno=os.dup(3))
    try:
        if listener.family!=socket.AF_UNIX or listener.type!=socket.SOCK_STREAM or not listener.getsockopt(socket.SOL_SOCKET,socket.SO_ACCEPTCONN) or listener.getsockname()!=str(SOCKET):
            raise ValueError('Wrong activation socket')
        require_root_ancestry(SOCKET)
        info=SOCKET.lstat();parent=SOCKET.parent.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid!=0 or info.st_gid!=config['socket_gid'] or stat.S_IMODE(info.st_mode)!=0o660:
            raise ValueError('Unsafe activation socket permissions')
        if parent.st_uid!=0 or parent.st_gid!=config['socket_gid'] or stat.S_IMODE(parent.st_mode)!=0o750:
            raise ValueError('Unsafe socket directory permissions')
        listener.settimeout(.2);return listener
    except BaseException:listener.close();raise


def dispatch_tick(broker,enabled):
    row=broker.db.execute("SELECT id,state FROM jobs WHERE state NOT IN ('completed','failed','cancelled') LIMIT 1").fetchone()
    if row and (row['state']!='queued' or enabled):broker.advance(row['id'])


def shutdown_job(broker):
    row=broker.db.execute("SELECT id FROM jobs WHERE state NOT IN ('completed','failed','cancelled') LIMIT 1").fetchone()
    if row:
        import uuid
        broker.request(broker.owner_uid,uuid.uuid4().hex,'cancel',{'run_id':row['id']})
        broker.advance(row['id'])


def run(listener,broker,adapter,stop,config):
    errors=[]
    def dispatch():
        # Independent SQLite connection keeps slow systemctl calls off the socket loop.
        worker=None
        try:
            worker=Broker(STATE,config['owner_uid'],adapter)
            while not stop.is_set():dispatch_tick(worker,config['submissions_enabled']);stop.wait(.5)
        except BaseException:errors.append('dispatcher_failed');stop.set()
        finally:
            if worker:
                try:shutdown_job(worker)
                except BaseException:errors.append('shutdown_unconfirmed')
                worker.close()
    thread=threading.Thread(target=dispatch,name='provider-dispatcher')
    transport=Transport(broker,submissions_enabled=config['submissions_enabled'])
    thread.start()
    try:
        while not stop.is_set():
            try:connection,_=listener.accept()
            except socket.timeout:continue
            with connection:transport.handle(connection)
    finally:
        stop.set();thread.join(timeout=60)
    if thread.is_alive() or errors:raise RuntimeError('Broker shutdown or dispatcher requires inspection')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path('/etc/yerbas-ai/broker.json'))
    args=parser.parse_args()
    if os.geteuid()!=0:raise SystemExit('Requires installed root broker service; do not run from development files')
    # Root execution must use an immutable installed source tree, never Documents.
    require_root_ancestry(Path(__file__))
    info=Path(__file__).lstat()
    if info.st_uid!=0 or info.st_mode&0o022:raise ValueError('Installed broker source required')
    os.umask(0o077);require_root_ancestry(args.config)
    config=validate_config(read_json(args.config,owner=0));provider=preflight(config)
    adapter=ServiceAdapter(RequestSpool('/var/lib/yerbas-ai-provider/requests',provider.pw_uid,provider.pw_gid),PrivateRecords(STATE/'records'))
    broker=Broker(STATE,config['owner_uid'],adapter);stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    try:
        with inherited_socket(config) as listener:run(listener,broker,adapter,stop,config)
    finally:broker.close()

if __name__=='__main__':main()
