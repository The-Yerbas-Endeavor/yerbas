"""Linux private-socket transport for the provider broker. No privileged adapter.

Submission is disabled unless trusted startup configuration enables it. Owner
cancellation remains available for already-recorded jobs. The
caller identity comes only from SO_PEERCRED, never from request JSON.
"""
import fcntl
import json
import os
from pathlib import Path
import socket
import stat
import struct
import time
from provider_broker import Rejected,identifier

MAX_FRAME=8192
TIMEOUT=2.0


def peer_uid(connection):
    return struct.unpack('3i',connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,struct.calcsize('3i')))[1]


def unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate field')
        result[key]=value
    return result


def read_frame(connection):
    deadline=time.monotonic()+TIMEOUT;data=bytearray()
    while b'\n' not in data:
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('request deadline')
        connection.settimeout(remaining)
        block=connection.recv(min(1024,MAX_FRAME+1-len(data)))
        if not block:raise ValueError('incomplete request')
        data.extend(block)
        if len(data)>MAX_FRAME:raise ValueError('request too large')
    if not data.endswith(b'\n') or data.count(b'\n')!=1:raise ValueError('one frame required')
    return json.loads(data,object_pairs_hook=unique,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite')))


class Transport:
    def __init__(self,broker,*,submissions_enabled=False):
        if type(submissions_enabled) is not bool:raise ValueError('explicit boolean required')
        self.broker=broker;self.enabled=submissions_enabled
    def dispatch(self,uid,request):
        response={'v':1,'id':None}
        try:
            self.broker.authorize(uid)
            if not isinstance(request,dict) or set(request)!={'v','id','method','params'} or type(request['v']) is not int or request['v']!=1:
                raise Rejected('invalid_request')
            response['id']=identifier(request['id'])
            method=request['method'];params=request['params']
            if not isinstance(params,dict):raise Rejected('invalid_params')
            if method=='capabilities':
                if params:raise Rejected('invalid_params')
                value={'protocol':1,'submissions_enabled':self.enabled,'methods':['capabilities','status','cancel']+(['submit'] if self.enabled else []),'gpu_submission_ready':False}
            elif method=='status':
                if set(params)!={'run_id'}:raise Rejected('invalid_params')
                value=self.broker.status(uid,params['run_id'])
            elif method in ('submit','cancel'):
                if method=='submit' and not self.enabled:raise Rejected('setup_required')
                value=self.broker.request(uid,request['id'],method,params)
            else:raise Rejected('unsupported_method')
            response.update(ok=True,result=value)
        except Rejected as exc:response.update(ok=False,error={'code':str(exc)})
        return response
    def handle(self,connection):
        response={'v':1,'id':None,'ok':False,'error':{'code':'invalid_request'}}
        try:
            uid=peer_uid(connection)
            self.broker.authorize(uid)  # Reject unauthorized peers before reading JSON.
            response=self.dispatch(uid,read_frame(connection))
        except Rejected as exc:response['error']['code']=str(exc)
        except (ValueError,UnicodeError,RecursionError,TimeoutError):pass
        except Exception:response['error']['code']='state_unavailable'
        try:
            connection.settimeout(TIMEOUT)
            raw=json.dumps(response,allow_nan=False).encode()+b'\n'
            if len(raw)>MAX_FRAME:raise ValueError('oversized reply')
            connection.sendall(raw)
        except (OSError,ValueError):pass


class PrivateListener:
    """Single same-user listener; future cross-account provisioning is separate."""
    def __init__(self,directory):
        self.path=Path(directory);self.fd=None;self.lock=None;self.socket=None
        self.path.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.endpoint=self.path/'broker.sock';self.bound=False
        try:
            self.fd=os.open(self.path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            info=os.fstat(self.fd)
            if info.st_uid!=os.getuid() or info.st_mode&0o077:raise ValueError('private socket directory required')
            self.lock=os.open('listener.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600,dir_fd=self.fd)
            info=os.fstat(self.lock)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid():raise ValueError('invalid listener lock')
            fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if os.path.lexists(self.endpoint):
                info=self.endpoint.lstat()
                if not stat.S_ISSOCK(info.st_mode) or info.st_uid!=os.getuid():raise ValueError('refusing to replace non-socket')
                self.endpoint.unlink()
            self.socket=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
            self.socket.bind(str(self.endpoint));self.bound=True;self.endpoint.chmod(0o600)
            self.socket.listen(4);self.socket.settimeout(.2)
        except BaseException:self.close();raise
    def serve_once(self,transport):
        try:connection,_=self.socket.accept()
        except socket.timeout:return
        with connection:transport.handle(connection)
    def close(self):
        if self.socket is not None:self.socket.close();self.socket=None
        if self.bound:self.endpoint.unlink(missing_ok=True);self.bound=False
        if self.lock is not None:os.close(self.lock);self.lock=None
        if self.fd is not None:os.close(self.fd);self.fd=None
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
