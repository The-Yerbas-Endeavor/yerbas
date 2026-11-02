"""Separate v3 contribution HTTPS transport, derived from the tested v1 bounded server.
Explicit preassigned contribution IDs; no admin, enrollment, funding or arbitrary-code routes.
"""
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import re
import ssl
import socket
import threading
import time
from urllib.parse import urlsplit
from recovery_checkpoint_v2 import MAX_BYTES
from text_contribution import validate_manifest,manifest_digest
from text_contribution import decode
from training_https import Client as OriginClient,RemoteError


def create_server(store, token_hashes, cert, key, bind='127.0.0.1', port=0):
    address=ipaddress.ip_address(bind)
    allowed=[ipaddress.ip_network(n) for n in ('127.0.0.0/8','10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')]
    if address.version!=4 or not any(address in network for network in allowed):
        raise ValueError('Explicit loopback or RFC1918 IPv4 bind required')
    credentials=dict(token_hashes)
    if not credentials or any(not re.fullmatch('[a-f0-9]{64}',k) for k in credentials):
        raise ValueError('Provider token hashes required')
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version=ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert,key)

    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.0'
        def log_message(self,*args):pass
        def reply(self,status,value):
            raw=json.dumps(value,allow_nan=False).encode()
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(raw)));self.send_header('Connection','close')
            self.end_headers();self.wfile.write(raw);self.close_connection=True
        def do_POST(self):
            try:
                headers=self.headers.get_all('Authorization',[])
                if len(headers)!=1 or not headers[0].startswith('Bearer '):
                    self.reply(401,{'error':'Provider authentication required'});return
                token=headers[0][7:]
                provider=credentials.get(hashlib.sha256(token.encode()).hexdigest())
                if provider is None:
                    self.reply(401,{'error':'Invalid provider credential'});return
                try:
                    with store.tx() as db:store.require_provider(db,provider)
                except ValueError:
                    self.reply(401,{'error':'Provider credential revoked'});return
                route=re.fullmatch('/v4/text/(assignment|status|parent|result)/([a-zA-Z0-9_-]{1,64})',self.path)
                if route is None:
                    self.reply(404,{'error':'Unknown provider route'});return
                action,contribution=route.groups();match=action=='result'
                lengths=self.headers.get_all('Content-Length',[])
                if self.headers.get_all('Transfer-Encoding') or len(lengths)!=1 or not lengths[0].isdigit():
                    self.reply(400,{'error':'One explicit Content-Length required'});return
                length=int(lengths[0]);limit=MAX_BYTES if match else 4096
                if not 0<length<=limit:
                    self.reply(413,{'error':'Request exceeds bound'});return
                expected_type='application/octet-stream' if match else 'application/json'
                if self.headers.get('Content-Type')!=expected_type:
                    self.reply(415,{'error':'Unsupported content type'});return
                if match:
                    checksums=self.headers.get_all('X-Artifact-SHA256',[])
                    if len(checksums)!=1 or not re.fullmatch('[a-f0-9]{64}',checksums[0]):
                        self.reply(400,{'error':'Artifact SHA256 required'});return
                    manifests=self.headers.get_all('X-Manifest-SHA256',[])
                    if len(manifests)!=1 or not re.fullmatch('[a-f0-9]{64}',manifests[0]):
                        self.reply(400,{'error':'Manifest SHA256 required'});return
                deadline=time.monotonic()+90;chunks=[];remaining=length
                while remaining:
                    if time.monotonic()>deadline:raise TimeoutError('Upload deadline exceeded')
                    chunk=self.rfile.read1(min(65536,remaining))
                    if not chunk:raise ValueError('Truncated request')
                    chunks.append(chunk);remaining-=len(chunk)
                raw=b''.join(chunks)
                if match:
                    if hashlib.sha256(raw).hexdigest()!=checksums[0]:raise ValueError('Transfer checksum mismatch')
                    result=store.accept(provider,contribution,manifests[0],raw)
                    self.reply(200,{'receipt':result})
                else:
                    def unique(pairs):
                        value={}
                        for k,v in pairs:
                            if k in value:raise ValueError('Duplicate JSON key')
                            value[k]=v
                        return value
                    body=json.loads(raw,object_pairs_hook=unique)
                    if type(body) is not dict or body!={}:raise ValueError('Empty request body required')
                    if action=='status':self.reply(200,{'status':store.status(provider,contribution)})
                    elif action=='assignment':self.reply(200,{'assignment':store.assignment(provider,contribution)})
                    else:
                        parent=store.parent(provider,contribution)
                        if parent is None:raise ValueError('Initial contribution has no parent artifact')
                        if len(parent)>MAX_BYTES:raise ValueError('Parent artifact exceeds limit')
                        self.send_response(200);self.send_header('Content-Type','application/octet-stream')
                        self.send_header('Content-Length',str(len(parent)));self.send_header('Connection','close')
                        self.send_header('X-Artifact-SHA256',hashlib.sha256(parent).hexdigest())
                        self.end_headers();self.wfile.write(parent);self.close_connection=True
            except (ValueError,UnicodeError) as exc:
                self.reply(400,{'error':str(exc)[:200]})
            except (TimeoutError,ConnectionError):
                self.close_connection=True
            except Exception:
                self.reply(500,{'error':'Training coordinator error'})

    class Server(ThreadingHTTPServer):
        daemon_threads=False
        block_on_close=True
        request_queue_size=4
        def __init__(self,*args):
            self.slots=threading.BoundedSemaphore(2)
            super().__init__(*args)
        def get_request(self):
            sock,peer=super().get_request();sock.settimeout(10)
            try:return context.wrap_socket(sock,server_side=True,do_handshake_on_connect=False),peer
            except BaseException:sock.close();raise
        def process_request(self,request,address):
            if not self.slots.acquire(blocking=False):
                self.shutdown_request(request);return
            try:super().process_request(request,address)
            except BaseException:self.slots.release();raise
        def process_request_thread(self,*args):
            def expire_connection():
                try:args[0].shutdown(socket.SHUT_RDWR)
                except OSError:pass
            timer=threading.Timer(100,expire_connection);timer.daemon=True;timer.start()
            try:super().process_request_thread(*args)
            finally:timer.cancel();self.slots.release()
        def handle_error(self,*args):pass
    return Server((bind,port),Handler)


class Client(OriginClient):
    def route(self,action,contribution):
        if type(contribution) is not str or not re.fullmatch('[a-zA-Z0-9_-]{1,64}',contribution):raise ValueError('Invalid contribution')
        return '/v4/text/'+action+'/'+contribution

    def assignment(self,contribution):
        return self.request(self.route('assignment',contribution),b'{}','application/json')['assignment']

    def status(self,contribution):
        return self.request(self.route('status',contribution),b'{}','application/json',timeout=3)['status']

    def submit(self,manifest,raw):
        validate_manifest(manifest)
        if type(raw) is not bytes or not 0<len(raw)<=manifest['max_artifact_bytes']:raise ValueError('Artifact size invalid')
        return self.request(self.route('result',manifest['contribution']),raw,'application/octet-stream',
            {'X-Artifact-SHA256':hashlib.sha256(raw).hexdigest(),'X-Manifest-SHA256':manifest_digest(manifest)})['receipt']

    def parent(self,manifest,stop=None,timeout=90):
        validate_manifest(manifest)
        if manifest['start_step']==0:raise ValueError('Initial contribution has no parent artifact')
        if type(timeout) not in (int,float) or not 0<timeout<=90:raise ValueError('Invalid download budget')
        if stop is not None and stop.is_set():raise RuntimeError('Owner stopped parent download')
        conn=http.client.HTTPSConnection(self.host,self.port,context=self.context,timeout=min(10,timeout))
        deadline=time.monotonic()+timeout
        finished=threading.Event();watcher=None
        def close():
            # Keep a fixed socket reference: HTTP/1.0 response handling may detach conn.sock.
            try:sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
        timer=None
        try:
            conn.connect();sock=conn.sock
            timer=threading.Timer(timeout,close);timer.daemon=True;timer.start()
            if stop is not None:
                def watch():
                    while not finished.wait(.05):
                        if stop.is_set():close();return
                watcher=threading.Thread(target=watch,daemon=True);watcher.start()
            conn.request('POST',self.route('parent',manifest['contribution']),b'{}',
                {'Authorization':'Bearer '+self.token,'Content-Type':'application/json'})
            response=conn.getresponse()
            if response.status!=200:raise RemoteError(response.status,'Parent request rejected')
            headers=response.headers;lengths=headers.get_all('Content-Length',[])
            hashes=headers.get_all('X-Artifact-SHA256',[])
            if (headers.get_all('Transfer-Encoding') or len(lengths)!=1 or not lengths[0].isdigit()
                or not 0<int(lengths[0])<=manifest['max_artifact_bytes']
                or headers.get('Content-Type')!='application/octet-stream'
                or hashes!=[manifest['parent_sha256']]):raise ValueError('Invalid parent response headers')
            remaining=int(lengths[0]);chunks=[]
            while remaining:
                if time.monotonic()>=deadline:raise TimeoutError('Parent download deadline exceeded')
                chunk=response.read(min(65536,remaining))
                if not chunk:raise ValueError('Truncated parent download')
                chunks.append(chunk);remaining-=len(chunk)
            raw=b''.join(chunks)
            if hashlib.sha256(raw).hexdigest()!=manifest['parent_sha256']:raise ValueError('Parent checksum mismatch')
            bundle=decode(raw,manifest['identity'])
            if bundle['target_step']!=manifest['target_step'] or bundle['latest']['step']!=manifest['start_step'] or bundle['selection']['stopped']:
                raise ValueError('Parent does not match assignment')
            return raw
        finally:
            finished.set()
            if timer is not None:timer.cancel()
            if watcher is not None:watcher.join(timeout=1)
            conn.close()
